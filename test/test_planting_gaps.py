"""Gap length, threshold, NoData and undilated image measurement regressions."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('planting_gaps',ROOT/'planting_gaps.py')
gaps=importlib.util.module_from_spec(spec); spec.loader.exec_module(gaps)


class GapTests(unittest.TestCase):
    def test_native_tile_gather_matches_pixels_across_tile_boundaries(self):
        from osgeo import gdal,osr
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'native_values.tif')
            ds=gdal.GetDriverByName('GTiff').Create(path,600,20,3,gdal.GDT_Byte)
            ds.SetGeoTransform((600000,.05,0,8090000,0,-.05));srs=osr.SpatialReference();srs.ImportFromEPSG(31982);ds.SetProjection(srs.ExportToWkt())
            yy,xx=np.mgrid[:20,:600]
            for i,values in enumerate(((3*xx+yy)%251,(xx+5*yy)%251,(2*xx+7*yy)%251),1):ds.GetRasterBand(i).WriteArray(values.astype(np.uint8))
            ds=None;sampler=gaps.GapRasterSampler(path,srs.ExportToWkt(),temp)
            try:
                cols=np.array([0,255,256,599,-1,600]);rows=np.array([0,0,7,19,8,1])
                xy=np.column_stack([sampler.gt[0]+(cols+.5)*sampler.gt[1],sampler.gt[3]+(rows+.5)*sampler.gt[5]])
                values,valid=sampler._native_sample(xy,(1,2,3,sampler.ds.RasterCount))
                np.testing.assert_array_equal(valid,[1,1,1,1,0,0])
                for band in range(3):
                    expected=sampler.ds.GetRasterBand(band+1).ReadAsArray()[rows[:4],cols[:4]]
                    np.testing.assert_array_equal(values[band,:4],expected)
                np.testing.assert_array_equal(sampler.valid_points(xy),valid)
            finally:sampler.close()

    def short_gap_scene(self):
        offsets=np.linspace(-.675,.675,45)
        rgb=np.tile(np.array([168.,152.,125.]),(70,45,1))
        rgb[:25,np.abs(offsets)<.12]=[40,150,30]
        rgb[35:,np.abs(offsets)<.12]=[40,150,30]
        # Thin peripheral foliage masks an exact 50 cm soil interval in the
        # old whole-corridor presence profile. No plant body occupies it.
        rgb[:,np.abs(offsets-.27)<.035]=[40,150,30]
        return offsets,rgb

    def test_visible_50cm_gap_is_recovered_despite_peripheral_leaf(self):
        offsets,rgb=self.short_gap_scene();args=(*[rgb[:,:,i] for i in range(3)],np.ones(rgb.shape[:2],bool),offsets,1.5)
        conservative=gaps.classify_cross_sections(*args,refine_visible=False)
        refined,evidence=gaps.classify_cross_sections(*args,return_evidence=True)
        self.assertFalse(gaps.intervals_from_states(np.arange(71)*.05,conservative,.5)[0])
        found,_=gaps.intervals_from_states(np.arange(71)*.05,refined,.5)
        self.assertEqual(len(found),1)
        self.assertAlmostEqual(found[0][0],1.25);self.assertAlmostEqual(found[0][1],1.75)
        self.assertTrue(evidence['recovered'][25:35].all())

    def test_off_axis_stool_vetoes_visible_soil_recovery(self):
        offsets,rgb=self.short_gap_scene()
        rgb[28:32,np.abs(offsets-.27)<.07]=[110,101,73]
        states=gaps.classify_cross_sections(*[rgb[:,:,i] for i in range(3)],np.ones(rgb.shape[:2],bool),offsets,1.5)
        self.assertTrue((states[28:32]==1).all())
        self.assertFalse(gaps.intervals_from_states(np.arange(71)*.05,states,.5)[0])

    def test_central_short_plant_always_interrupts_visible_gap(self):
        offsets,rgb=self.short_gap_scene();rgb[30,np.abs(offsets)<.12]=[40,150,30]
        states=gaps.classify_cross_sections(*[rgb[:,:,i] for i in range(3)],np.ones(rgb.shape[:2],bool),offsets,1.5)
        self.assertEqual(states[30],1)
        self.assertFalse(gaps.intervals_from_states(np.arange(71)*.05,states,.5)[0])

    def test_unbounded_skinny_object_is_not_reclassified_as_total_gap(self):
        offsets=np.linspace(-.675,.675,45);rgb=np.tile(np.array([168.,152.,125.]),(80,45,1))
        rgb[:,np.abs(offsets-.27)<.035]=[40,150,30]
        states,evidence=gaps.classify_cross_sections(*[rgb[:,:,i] for i in range(3)],
            np.ones(rgb.shape[:2],bool),offsets,1.5,return_evidence=True)
        self.assertFalse(evidence['recovered'].any())
        self.assertTrue((states==1).all())

    def test_variable_width_objects_are_independent_of_block_read_direction(self):
        from osgeo import gdal,osr
        class Feedback:
            def isCanceled(self):return False
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'variable_width.tif')
            ds=gdal.GetDriverByName('GTiff').Create(path,800,100,3,gdal.GDT_Byte)
            ds.SetGeoTransform((600000,.05,0,8090000,0,-.05))
            srs=osr.SpatialReference();srs.ImportFromEPSG(31982);ds.SetProjection(srs.ExportToWkt())
            yy,xx=np.mgrid[:100,:800];u=(xx+.5)*.05
            width=np.where((u<7.)|(u>27.),.30,.10)
            crop=abs((yy+.5)*.05-2.5)<width/2
            for i,(soil,cane) in enumerate(zip([168,152,125],[40,150,30]),1):
                ds.GetRasterBand(i).WriteArray(np.where(crop,cane,soil).astype(np.uint8))
            ds=None
            sampler=gaps.GapRasterSampler(path,srs.ExportToWkt(),temp)
            try:
                edges,centres,normals=gaps.sample_polyline([[600000,8089997.5],[600040,8089997.5]],.05)
                forward=sampler.states(centres,normals,1.5,Feedback())
                reverse=sampler.states(centres[::-1],normals[::-1],1.5,Feedback())[::-1]
                np.testing.assert_array_equal(forward,reverse)
                # A narrow connected row is not bare merely because another
                # part of the same object is wider many metres away.
                self.assertTrue((forward[200:500]==1).all())
                self.assertFalse(gaps.intervals_from_states(edges,forward,.5)[0])
            finally:sampler.close()

    def _section(self,background,colour,width=.20,rows=20,dtype=float,centre=0.):
        offsets=np.linspace(-.675,.675,45)
        rgb=np.tile(np.array(background,dtype=dtype),(rows,45,1))
        rgb[:,np.abs(offsets-centre)<width/2]=colour
        return gaps.classify_cross_sections(*[rgb[:,:,i] for i in range(3)],
            np.ones((rows,45),bool),offsets,1.5)

    def test_bright_yellow_green_cane_does_not_require_darkness(self):
        # G<R and plant is as bright as surrounding straw: old darkness gates
        # rejected it. Its blue absorption and local contrast remain strong.
        for scale in (.4,1.,2.):
            states=self._section(np.array([168,152,125])*scale,
                                 np.array([190,175,70])*scale)
            np.testing.assert_array_equal(states,1)

    def test_strong_chlorosis_without_green_support_is_review_not_gap(self):
        states=self._section([168,152,125],[190,160,65])
        np.testing.assert_array_equal(states,-2)
        self.assertFalse(gaps.intervals_from_states(np.arange(21)*.05,states,.5)[0])

    def test_yellow_soil_and_uniform_straw_do_not_become_crop(self):
        for colour in ([190,175,70],[168,152,125],[185,115,75],[190,160,65]):
            np.testing.assert_array_equal(self._section(colour,colour),0)

    def test_uint8_and_float_inputs_produce_same_result(self):
        a=self._section([168,152,125],[190,175,70],dtype=np.uint8)
        b=self._section([168,152,125],[190,175,70])
        np.testing.assert_array_equal(a,b)

    def test_thin_leaf_cannot_hide_a_gap_but_off_axis_stool_can(self):
        # One 3 cm sample over a long bare corridor is insufficient support.
        thin=self._section([168,152,125],[60,200,45],width=.025,rows=60)
        np.testing.assert_array_equal(thin,0)
        found,_=gaps.intervals_from_states(np.arange(61)*.05,thin,.5)
        self.assertEqual(len(found),1)
        stool=self._section([168,152,125],[40,140,30],width=.14,centre=.27)
        np.testing.assert_array_equal(stool,1)

    def test_thin_dark_object_is_review_not_assumed_bare_ground(self):
        states=self._section([168,152,125],[40,140,30],width=.025,rows=60)
        np.testing.assert_array_equal(states,-2)

    def test_outer_canopy_cannot_confirm_weak_foliage_inside_empty_corridor(self):
        offsets=np.linspace(-.675,.675,45)
        rgb=np.tile(np.array([168.,152.,125.]),(40,45,1))
        rgb[:,(offsets<-.35)&(offsets>-.49)]=[50,150,35]
        # Weak, bright leaf tips near the outer edge, no row seed inside.
        rgb[:,(offsets>-.35)&(offsets<-.23)]=[160,159,125]
        states=gaps.classify_cross_sections(*[rgb[:,:,i] for i in range(3)],
            np.ones((40,45),bool),offsets,1.5)
        self.assertFalse((states==1).any())
        self.assertTrue((states==0).any())

    def test_invalid_rgb_cannot_confirm_vegetation(self):
        for colour in ([np.nan,150,20],[0,0,0],[100,np.inf,10],[-100,100,0]):
            # No valid image in the central corridor; not a bare observation.
            offsets=np.linspace(-.675,.675,45)
            rgb=np.tile(np.array(colour),(20,45,1))
            states=gaps.classify_cross_sections(*[rgb[:,:,i] for i in range(3)],
                np.ones((20,45),bool),offsets,1.5)
            np.testing.assert_array_equal(states,-1)

    def test_yellow_cane_gap_across_raster_processing_blocks(self):
        from osgeo import gdal,osr
        class Feedback:
            def isCanceled(self):return False
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'yellow_cane.tif')
            ds=gdal.GetDriverByName('GTiff').Create(path,800,100,3,gdal.GDT_Byte)
            ds.SetGeoTransform((600000,.05,0,8090000,0,-.05))
            srs=osr.SpatialReference();srs.ImportFromEPSG(31982);ds.SetProjection(srs.ExportToWkt())
            yy,xx=np.mgrid[:100,:800]
            # A 1.25 m gap crosses the 256-station (12.8 m) block boundary.
            crop=(abs((yy+.5)*.05-2.5)<.12)&~((xx>=245)&(xx<270))
            for i,(soil,cane) in enumerate(zip([168,152,125],[190,175,70]),1):
                ds.GetRasterBand(i).WriteArray(np.where(crop,cane,soil).astype(np.uint8))
            ds=None
            sampler=gaps.GapRasterSampler(path,srs.ExportToWkt(),temp)
            try:
                e,c,n=gaps.sample_polyline([[600000,8089997.5],[600040,8089997.5]],.05)
                states=sampler.states(c,n,1.5,Feedback())
                found,_=gaps.intervals_from_states(e,states,.5)
                self.assertEqual(len(found),1)
                self.assertAlmostEqual(found[0][0],12.25,delta=.051)
                self.assertAlmostEqual(found[0][1],13.5,delta=.051)
                self.assertTrue((states[20:220]==1).all())
                self.assertTrue((states[300:780]==1).all())
            finally:sampler.close()

    def test_raster_rgb_colour_metadata_overrides_physical_bgr_order(self):
        from osgeo import gdal,osr
        class Feedback:
            def isCanceled(self):return False
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'bgr.tif')
            ds=gdal.GetDriverByName('GTiff').Create(path,200,80,3,gdal.GDT_Byte)
            ds.SetGeoTransform((600000,.05,0,8090000,0,-.05))
            srs=osr.SpatialReference();srs.ImportFromEPSG(31982);ds.SetProjection(srs.ExportToWkt())
            yy,xx=np.mgrid[:80,:200];crop=abs((yy+.5)*.05-2)<.12
            for i,(soil,cane,interpretation) in enumerate([(125,70,gdal.GCI_BlueBand),
                    (152,175,gdal.GCI_GreenBand),(168,190,gdal.GCI_RedBand)],1):
                ds.GetRasterBand(i).WriteArray(np.where(crop,cane,soil).astype(np.uint8))
                ds.GetRasterBand(i).SetColorInterpretation(interpretation)
            ds=None
            sampler=gaps.GapRasterSampler(path,srs.ExportToWkt(),temp)
            try:
                e,c,n=gaps.sample_polyline([[600000.2,8089998],[600009.8,8089998]],.05)
                states=sampler.states(c,n,1.5,Feedback())
                self.assertTrue((states==1).all())
            finally:sampler.close()

    def test_nominal_50cm_not_lost_on_line_with_fractional_remainder(self):
        edges,_,_=gaps.sample_polyline([[0,0],[10.013,0]],.05)
        np.testing.assert_allclose(np.diff(edges)[:-1],.05)
        states=np.ones(len(edges)-1,dtype=int);states[20:30]=0
        found,_=gaps.intervals_from_states(edges,states,.5)
        self.assertEqual(len(found),1)
        self.assertAlmostEqual(found[0][1]-found[0][0],.5)

    def test_review_intervals_are_separate_from_gaps(self):
        edges=np.arange(7)*.25;states=[1,-2,-2,0,-1,1]
        review=gaps.review_intervals(edges,states)
        self.assertEqual([r[2] for r in review],['incerto','sem_dados'])
        self.assertAlmostEqual(sum(b-a for a,b,_ in review),.75)
        found,_=gaps.intervals_from_states(edges,states,.5)
        self.assertFalse(found)
    def test_threshold_is_inclusive_and_does_not_include_crop_neighbours(self):
        edges=np.arange(9)*.1
        found,unknown=gaps.intervals_from_states(edges,[1,1,0,0,0,0,0,1],.5)
        self.assertEqual(len(found),1)
        self.assertAlmostEqual(found[0][0],.2); self.assertAlmostEqual(found[0][1],.7)
        self.assertEqual(found[0][2],'interna')
        self.assertFalse(gaps.intervals_from_states(edges,[1,1,0,0,0,0,0,1],.51)[0])

    def test_nodata_is_not_absence_and_does_not_bridge_gaps(self):
        found,unknown=gaps.intervals_from_states(np.arange(7)*.25,[1,0,0,-1,0,1],.25)
        self.assertEqual(len(found),2); self.assertAlmostEqual(unknown,.25)
        self.assertTrue(all(v[2]=='limite_dados' for v in found))

    def test_total_initial_and_final_categories(self):
        self.assertEqual(gaps.intervals_from_states([0,1,2],[0,0],.5)[0][0][2],'total')
        found,_=gaps.intervals_from_states([0,1,2,3],[0,1,0],.5)
        self.assertEqual([v[2] for v in found],['inicial','final'])

    def test_isolated_green_speck_does_not_split_gap(self):
        found,_=gaps.intervals_from_states(np.arange(22)*.05,[0]*10+[1]+[0]*10,.5,min_crop_m=.10)
        self.assertEqual(len(found),1); self.assertAlmostEqual(found[0][1],1.05)

    def test_true_crop_stand_separates_gaps(self):
        found,_=gaps.intervals_from_states(np.arange(25)*.05,[0]*10+[1]*4+[0]*10,.5)
        self.assertEqual(len(found),2)

    def test_short_confirmed_plant_always_interrupts_a_150cm_gap(self):
        found,_=gaps.intervals_from_states(np.arange(42)*.05,[0]*20+[1]+[0]*20,1.5)
        self.assertFalse(found)

    def test_olive_cane_from_reported_image_is_not_bare_soil(self):
        offsets=np.linspace(-.675,.675,45)
        rgb=np.tile(np.array([168.,152.,125.]),(4,45,1))
        # Actual RGB colours from the reported image (G < R).
        for i,colour in enumerate(([110,101,73],[114,106,78],[140,133,104],[143,141,107])):
            rgb[i,np.abs(offsets)<.12]=colour
        states=gaps.classify_cross_sections(*[rgb[:,:,i] for i in range(3)],
            np.ones((4,45),bool),offsets,1.5)
        np.testing.assert_array_equal(states,1)

    def test_off_axis_cane_is_not_rejected_by_central_sample_requirement(self):
        offsets=np.linspace(-.675,.675,45)
        rgb=np.tile(np.array([168.,152.,125.]),(4,45,1))
        rgb[:,np.abs(offsets-.27)<.07]=[110,101,73]
        states=gaps.classify_cross_sections(*[rgb[:,:,i] for i in range(3)],
            np.ones((4,45),bool),offsets,1.5)
        np.testing.assert_array_equal(states,1)

    def test_straw_speckles_cannot_fragment_a_150cm_empty_row(self):
        offsets=np.linspace(-.675,.675,45)
        rgb=np.tile(np.array([168.,152.,125.]),(60,45,1))
        for i in range(2,60,6):
            rgb[i,20:22]=[155,149,115]  # Weak local colour, not a plant object.
        states=gaps.classify_cross_sections(*[rgb[:,:,i] for i in range(3)],
            np.ones((60,45),bool),offsets,1.5)
        found,_=gaps.intervals_from_states(np.arange(61)*.05,states,1.5)
        self.assertEqual(len(found),1)
        self.assertAlmostEqual(found[0][1]-found[0][0],3.)

    def test_one_plant_cannot_flood_a_connected_straw_carpet(self):
        offsets=np.linspace(-.675,.675,45)
        rgb=np.tile(np.array([185.,115.,75.]),(100,45,1))
        rgb[:,np.abs(offsets)<.3]=[165,150,120]  # Straw brighter than red soil.
        rgb[45:55,np.abs(offsets)<.15]=[45,125,30]
        states=gaps.classify_cross_sections(*[rgb[:,:,i] for i in range(3)],
            np.ones((100,45),bool),offsets,1.5)
        self.assertTrue((states[:30]==0).all())
        self.assertTrue((states[70:]==0).all())
        self.assertTrue((states[45:55]==1).all())
        found,_=gaps.intervals_from_states(np.arange(101)*.05,states,1.5)
        self.assertEqual(len(found),2)

    def test_dense_vegetation_filter_does_not_remove_image_coverage(self):
        import ast
        import scipy.ndimage as ndi
        tree=ast.parse((ROOT/'RestituirLinhasAlgorithm.py').read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef))
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_classify_rgb_grid')
        scope={'np':np,'ndi':ndi}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'<coverage>','exec'),scope)
        shape=(100,100);valid=np.ones(shape,bool);valid[:2]=False
        crop,contrast,coverage=scope[method.name](None,np.full(shape,40),np.full(shape,150),np.full(shape,30),valid,.15)
        self.assertFalse(crop.any())  # Dense-canopy exclusion remains separate.
        np.testing.assert_array_equal(coverage,valid)

    def test_planned_line_survives_dense_patch_excluded_from_crop_signal(self):
        import sys,types,importlib,uuid
        from qgis.core import (QgsVectorLayer,QgsFeature,QgsGeometry,QgsPointXY,
                              QgsRectangle,QgsProcessingFeedback)
        pkg=types.ModuleType('dense_patch_test_'+uuid.uuid4().hex);pkg.__path__=[str(ROOT)];sys.modules[pkg.__name__]=pkg
        module=importlib.import_module(pkg.__name__+'.RestituirLinhasAlgorithm')
        alg=module.RestituirLinhasAlgorithm()
        shape=(60,120);valid=np.ones(shape,bool)
        density,contrast,coverage=alg._classify_rgb_grid(np.full(shape,40),np.full(shape,150),np.full(shape,30),valid,.1)
        planned=QgsVectorLayer('LineString?crs=EPSG:31982','planned','memory')
        f=QgsFeature();f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(600000.5,8089998),QgsPointXY(600009.5,8089998)]))
        planned.dataProvider().addFeatures([f]);planned.updateExtents()
        lines,_=alg._reconstruct_from_planned_lines(planned,None,QgsRectangle(600000,8089994,600012,8090000),
            density,density,contrast,coverage,.1,1.5,600000,8090000,120,60,QgsProcessingFeedback())
        self.assertEqual(len(lines),1)
        self.assertAlmostEqual(lines[0][2],9.,places=5)

    def test_shadow_is_uncertain_and_does_not_join_two_absences(self):
        offsets=np.linspace(-.675,.675,45)
        rgb=np.tile(np.array([168.,152.,125.]),(1,45,1))
        rgb[0,np.abs(offsets)<.2]*=.4
        state=gaps.classify_cross_sections(*[rgb[:,:,i] for i in range(3)],
            np.ones((1,45),bool),offsets,1.5)[0]
        self.assertEqual(state,-2)
        found,unassessed=gaps.intervals_from_states(np.arange(42)*.05,[0]*20+[-2]+[0]*20,1.5)
        self.assertFalse(found)
        self.assertAlmostEqual(unassessed,.05)

    def test_uniform_bare_soil_still_produces_a_gap(self):
        offsets=np.linspace(-.675,.675,45)
        rgb=np.tile(np.array([168.,152.,125.]),(1,45,1))
        state=gaps.classify_cross_sections(*[rgb[:,:,i] for i in range(3)],
            np.ones((1,45),bool),offsets,1.5)[0]
        self.assertEqual(state,0)

    def test_curve_lengths_are_along_polyline_not_chord(self):
        xy=np.array([[0,0],[1,0],[1,1]],float)
        edges,centres,normals=gaps.sample_polyline(xy,.1)
        self.assertAlmostEqual(edges[-1],2)
        coords=gaps.segment_coordinates(xy,.5,1.5)
        self.assertAlmostEqual(np.linalg.norm(np.diff(coords,axis=0),axis=1).sum(),1)
        np.testing.assert_allclose(coords,[[.5,0],[1,0],[1,.5]])

    def test_entire_nodata_has_no_gaps(self):
        found,unknown=gaps.intervals_from_states([0,1,2],[-1,-1],.5)
        self.assertFalse(found); self.assertEqual(unknown,2)

    def test_real_raster_corridor_ignores_adjacent_row_and_keeps_nodata(self):
        from osgeo import gdal,osr
        class Feedback:
            def isCanceled(self): return False
        with tempfile.TemporaryDirectory() as temp:
            path=str(Path(temp)/'image.tif')
            ds=gdal.GetDriverByName('GTiff').Create(path,200,80,4,gdal.GDT_Byte)
            ds.SetGeoTransform((600000,.05,0,8090000,0,-.05))
            srs=osr.SpatialReference(); srs.ImportFromEPSG(31982); ds.SetProjection(srs.ExportToWkt())
            # Healthy row at y=-2 m, with exact 1 m gap at x=4..5 m.
            yy,xx=np.mgrid[:80,:200]; crop=(abs((yy+.5)*.05-2)<.15)&~((xx>=80)&(xx<100))
            # Vigorous neighbouring row at y=-0.5 m cannot fill this gap.
            crop |= abs((yy+.5)*.05-.5)<.2
            for i,(a,b) in enumerate([(40,140),(160,90),(30,70)],1):
                ds.GetRasterBand(i).WriteArray(np.where(crop,a,b).astype(np.uint8))
            alpha=np.full((80,200),255,dtype=np.uint8); alpha[:,140:160]=0
            ds.GetRasterBand(4).WriteArray(alpha); ds.GetRasterBand(4).SetColorInterpretation(gdal.GCI_AlphaBand)
            ds=None
            sampler=gaps.GapRasterSampler(path,srs.ExportToWkt(),temp)
            try:
                edges,centres,normals=gaps.sample_polyline([[600000,8089998],[600010,8089998]],.05)
                states=sampler.states(centres,normals,1.5,Feedback())
                found,unknown=gaps.intervals_from_states(edges,states,.5)
                self.assertEqual(len(found),1)
                self.assertAlmostEqual(found[0][0],4,delta=.051)
                self.assertAlmostEqual(found[0][1],5,delta=.051)
                self.assertAlmostEqual(unknown,1,delta=.051)
            finally: sampler.close()
            self._check_qgis_pipeline(path)

    def _check_qgis_pipeline(self,path):
        import sys,types,importlib
        from qgis.core import (QgsVectorLayer,QgsFeature,QgsGeometry,QgsPointXY,QgsProcessingContext,
                              QgsProcessingFeedback,QgsProcessingUtils,QgsProject)
        pkg=types.ModuleType('gap_test_package_'+str(id(self))); pkg.__path__=[str(ROOT)]; sys.modules[pkg.__name__]=pkg
        module=importlib.import_module(pkg.__name__+'.RestituirLinhasAlgorithm')
        ctx=QgsProcessingContext(); ctx.setProject(QgsProject.instance())
        points=QgsVectorLayer('Point?crs=EPSG:31982','points','memory')
        batch=[]
        for x in np.arange(.2,9.8,.2):
            if 4<x<5 or 7<x<8: continue
            f=QgsFeature(); f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(600000+x,8089998)))
            batch.append(f)
        points.dataProvider().addFeatures(batch); points.updateExtents()
        planned=QgsVectorLayer('LineString?crs=EPSG:31982','planned','memory')
        f=QgsFeature(); f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(600000,8089998),QgsPointXY(600010,8089998)]))
        planned.dataProvider().addFeatures([f]); planned.updateExtents()
        ctx.temporaryLayerStore().addMapLayer(points); ctx.temporaryLayerStore().addMapLayer(planned)
        outputs=[]
        class FixedRows(module.RestituirLinhasAlgorithm):
            def _reconstruct_from_planned_lines(self,*args,**kwargs):
                # The geometry is fixed deliberately: this regression verifies
                # that the NEW gap pass changes measurements, never the trace.
                pts=[QgsPointXY(600000,8089998),QgsPointXY(600010,8089998)]
                return [(pts,0.,10.,0.,0.,0,100.,0.)],[]
        for minimum in (50,150):
            alg=FixedRows(); alg.initAlgorithm()
            parameters={'INPUT_RASTER':path,'INPUT_POINTS':points.id(),
                'INPUT_PLANNED_LINES':planned.id(),'MIN_GAP_CM':minimum,
                'OUTPUT':'memory:','OUTPUT_GAPS':'memory:'}
            if minimum==50:parameters['OUTPUT_REVIEW']='memory:'
            result=alg.processAlgorithm(parameters,ctx,QgsProcessingFeedback())
            rows=QgsProcessingUtils.mapLayerFromString(result['OUTPUT'],ctx)
            segments=QgsProcessingUtils.mapLayerFromString(result['OUTPUT_GAPS'],ctx)
            self.assertEqual(rows.featureCount(),1)
            self.assertIn('sem_dados_m',rows.fields().names())
            self.assertIn('incerto_m',rows.fields().names())
            self.assertIn('categoria',segments.fields().names())
            if minimum==50:
                review=QgsProcessingUtils.mapLayerFromString(result['OUTPUT_REVIEW'],ctx)
                self.assertIsNotNone(review)
                self.assertTrue(any(f['motivo']=='sem_dados' for f in review.getFeatures()))
            else:self.assertFalse(result.get('OUTPUT_REVIEW'))
            self.assertTrue(all(f['compr_m']+1e-6>=minimum/100 for f in segments.getFeatures()))
            outputs.append((bytes(next(rows.getFeatures()).geometry().asWkb()),segments.featureCount()))
        ctx.temporaryLayerStore().removeAllMapLayers()
        self.assertEqual(outputs[0][0],outputs[1][0])
        self.assertGreater(outputs[0][1],outputs[1][1])


if __name__=='__main__': unittest.main()
