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
        found,_=gaps.intervals_from_states(np.arange(22)*.05,[0]*10+[1]+[0]*10,.5)
        self.assertEqual(len(found),1); self.assertAlmostEqual(found[0][1],1.05)

    def test_true_crop_stand_separates_gaps(self):
        found,_=gaps.intervals_from_states(np.arange(25)*.05,[0]*10+[1]*4+[0]*10,.5)
        self.assertEqual(len(found),2)

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
            result=alg.processAlgorithm({'INPUT_RASTER':path,'INPUT_POINTS':points.id(),
                'INPUT_PLANNED_LINES':planned.id(),'MIN_GAP_CM':minimum,
                'OUTPUT':'memory:','OUTPUT_GAPS':'memory:'},ctx,QgsProcessingFeedback())
            rows=QgsProcessingUtils.mapLayerFromString(result['OUTPUT'],ctx)
            segments=QgsProcessingUtils.mapLayerFromString(result['OUTPUT_GAPS'],ctx)
            self.assertEqual(rows.featureCount(),1)
            self.assertIn('sem_dados_m',rows.fields().names())
            self.assertIn('categoria',segments.fields().names())
            self.assertTrue(all(f['compr_m']+1e-6>=minimum/100 for f in segments.getFeatures()))
            outputs.append((bytes(next(rows.getFeatures()).geometry().asWkb()),segments.featureCount()))
        ctx.temporaryLayerStore().removeAllMapLayers()
        self.assertEqual(outputs[0][0],outputs[1][0])
        self.assertGreater(outputs[0][1],outputs[1][1])


if __name__=='__main__': unittest.main()
