"""End-to-end RGB preparation tests; run in an initialized QGIS Python session."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
from osgeo import gdal, osr
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFeature, QgsGeometry, QgsPointXY, QgsProcessingContext, QgsProcessingException,
    QgsProcessingFeedback, QgsProcessingUtils, QgsProject, QgsVectorLayer)
from qgis.core import QgsProcessingOutputLayerDefinition

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rgb_preparation_algorithm', ROOT / 'Falhadeplantio_algorithm.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Algorithm = module.FalhaDePlantioAlgorithm


class RasterPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='qgis_rgb_test_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.tif'
        self.crs = QgsCoordinateReferenceSystem('EPSG:31982')
        srs = osr.SpatialReference(); srs.ImportFromEPSG(31982)
        ds = gdal.GetDriverByName('GTiff').Create(str(self.source), 300, 300, 3, gdal.GDT_Byte)
        ds.SetGeoTransform((600000, .1, 0, 8090000, 0, -.1)); ds.SetProjection(srs.ExportToWkt())
        _, cols = np.indices((300, 300))
        crop = (cols % 15) < 5
        for i, (on, off, interp) in enumerate(((40, 130, gdal.GCI_RedBand),
                (150, 90, gdal.GCI_GreenBand), (30, 60, gdal.GCI_BlueBand)), 1):
            ds.GetRasterBand(i).WriteArray(np.where(crop, on, off).astype(np.uint8))
            ds.GetRasterBand(i).SetColorInterpretation(interp)
        ds = None
        self.geometry = QgsGeometry.fromWkt(
            'Polygon ((600002 8089998,600027 8089998,600021 8089973,600002 8089981,600002 8089998),'
            '(600010 8089991,600015 8089991,600015 8089986,600010 8089986,600010 8089991))')

    def mask(self, geometry=None, crs=None):
        crs = crs or self.crs
        geometry = geometry or self.geometry
        layer = QgsVectorLayer('MultiPolygon' if geometry.isMultipart() else 'Polygon', 'field', 'memory'); layer.setCrs(crs)
        f = QgsFeature(); f.setGeometry(geometry)
        self.assertTrue(layer.dataProvider().addFeatures([f])[0]); layer.updateExtents()
        return layer

    def run_case(self, mode=0, mask=None, target=None, keep_rgb=True, load=False):
        alg = Algorithm(); alg.initAlgorithm()
        ctx = QgsProcessingContext(); ctx.setProject(QgsProject.instance())
        params = {'INPUT_RASTER':str(self.source), 'PREPARATION_MODE':mode,
            'RED_BAND':1,'GREEN_BAND':2,'BLUE_BAND':3, 'PIXEL_SIZE_CM':10,
            'POINT_SPACING_CM':20, 'GLI_THRESHOLD':0,
            'OUTPUT':str(self.root/'classified.tif'), 'OUTPUT_POINTS':'memory:'}
        if mask is not None:
            ctx.temporaryLayerStore().addMapLayer(mask)
            params['MASK_LAYER'] = mask.id()
        if target is not None: params['TARGET_CRS'] = target
        if mode is None: params.pop('PREPARATION_MODE')
        if keep_rgb: params['OUTPUT_CLIPPED'] = str(self.root/'clipped.tif')
        if load:
            params['OUTPUT'] = QgsProcessingOutputLayerDefinition(params['OUTPUT'], QgsProject.instance())
        result = alg.processAlgorithm(params, ctx, QgsProcessingFeedback())
        points = QgsProcessingUtils.mapLayerFromString(result['OUTPUT_POINTS'], ctx)
        self.assertIsNotNone(points); self.assertGreater(points.featureCount(), 0)
        return result, ctx, points

    def test_direct_mode_preserves_old_outputs_without_mask(self):
        original = self.source.read_bytes()
        result, ctx, points = self.run_case(mode=None, keep_rgb=False)
        self.assertEqual(set(result), {'OUTPUT','OUTPUT_POINTS'})
        ds = gdal.Open(result['OUTPUT'])
        self.assertEqual((ds.RasterXSize, ds.RasterYSize), (300,300))
        ds = None
        self.assertEqual(points.crs(), self.crs)
        self.assertEqual(original, self.source.read_bytes())

    def test_clip_reproject_and_classify_in_one_run_preserving_holes(self):
        target = QgsCoordinateReferenceSystem('EPSG:32722')
        mask = self.mask()
        result, ctx, points = self.run_case(1, mask, target.authid())
        expected = QgsGeometry(self.geometry)
        expected.transform(QgsCoordinateTransform(self.crs, target, ctx.transformContext()))
        self.assertEqual(points.crs(), target)
        self.assertTrue(all(expected.intersects(f.geometry()) for f in points.getFeatures()))
        rgb = gdal.Open(result['OUTPUT_CLIPPED']); classification = gdal.Open(result['OUTPUT'])
        self.assertEqual(rgb.RasterCount, 4)
        self.assertEqual(rgb.GetGeoTransform(), classification.GetGeoTransform())
        self.assertEqual(rgb.GetProjection(), classification.GetProjection())
        alpha = rgb.GetRasterBand(4).ReadAsArray()
        values = classification.ReadAsArray()
        self.assertTrue((alpha == 0).any()); self.assertTrue((alpha > 0).any())
        self.assertTrue(np.all(values[alpha == 0] == 255))
        hole = expected.asPolygon()[1]
        centre = QgsGeometry.fromPolygonXY([hole]).centroid().asPoint()
        inv = gdal.InvGeoTransform(rgb.GetGeoTransform())
        x,y = gdal.ApplyGeoTransform(inv, centre.x(), centre.y())
        self.assertEqual(alpha[int(y),int(x)], 0)
        rgb = classification = None

    def test_geographic_mask_and_automatic_rgb_destination(self):
        geographic = QgsCoordinateReferenceSystem('EPSG:4326')
        geometry = QgsGeometry(self.geometry)
        geometry.transform(QgsCoordinateTransform(self.crs, geographic, QgsProject.instance()))
        result, ctx, points = self.run_case(1, self.mask(geometry, geographic), keep_rgb=False)
        self.assertTrue(Path(result['OUTPUT_CLIPPED']).is_file())
        self.assertEqual(points.crs(), self.crs)

    def test_reject_missing_mask(self):
        with self.assertRaisesRegex(QgsProcessingException, 'polígono do talhão'):
            self.run_case(1)

    def test_auto_rgb_is_queued_for_loading_in_gui(self):
        result, ctx, points = self.run_case(1, self.mask(), keep_rgb=False, load=True)
        self.assertTrue(ctx.willLoadLayerOnCompletion(result['OUTPUT_CLIPPED']))

    def test_empty_optional_crs_widget_uses_source_metric_crs(self):
        result, ctx, points = self.run_case(1,self.mask(),QgsCoordinateReferenceSystem())
        self.assertEqual(points.crs(),self.crs)

    def test_geographic_raster_chooses_metric_utm_automatically(self):
        geographic = self.root/'geographic.tif'
        ds = gdal.Warp(str(geographic), str(self.source), dstSRS='EPSG:4326', format='GTiff')
        ds = None
        self.source = geographic
        result, ctx, points = self.run_case(1, self.mask())
        self.assertEqual(points.crs().authid(), 'EPSG:32722')

    def test_multipart_mask_keeps_all_parts(self):
        second = QgsGeometry.fromWkt('Polygon ((600024 8089971,600029 8089971,600029 8089975,600024 8089975,600024 8089971))')
        geometry = QgsGeometry.unaryUnion([self.geometry,second])
        result, ctx, points = self.run_case(1, self.mask(geometry))
        self.assertTrue(all(geometry.intersects(f.geometry()) for f in points.getFeatures()))
        self.assertTrue(any(second.intersects(f.geometry()) for f in points.getFeatures()))

    def test_existing_alpha_is_respected(self):
        rgba = self.root/'rgba.tif'
        ds = gdal.Warp(str(rgba),str(self.source),dstAlpha=True,format='GTiff')
        alpha = ds.GetRasterBand(4).ReadAsArray()
        alpha[50:75,50:75] = 0
        ds.GetRasterBand(4).WriteArray(alpha)
        ds = None
        self.source = rgba
        result, ctx, points = self.run_case(1,self.mask())
        rgb = gdal.Open(result['OUTPUT_CLIPPED'])
        inv = gdal.InvGeoTransform(rgb.GetGeoTransform())
        x,y = gdal.ApplyGeoTransform(inv,600006,8089994)
        self.assertEqual(rgb.GetRasterBand(4).ReadAsArray()[int(y),int(x)],0)
        rgb = None

    def test_reject_geographic_output_for_centimetre_pixels(self):
        with self.assertRaisesRegex(QgsProcessingException, 'projetado em metros'):
            self.run_case(1, self.mask(), 'EPSG:4326')

    def test_reject_mask_outside_image(self):
        geometry = QgsGeometry(self.geometry); geometry.translate(1000,1000)
        with self.assertRaisesRegex(QgsProcessingException, 'não intersecta'):
            self.run_case(1, self.mask(geometry))

    def test_reject_empty_mask(self):
        layer = QgsVectorLayer('Polygon?crs=EPSG:31982','empty','memory')
        with self.assertRaisesRegex(QgsProcessingException, 'não contém polígonos'):
            self.run_case(1, layer)

    def test_do_not_overwrite_source_with_rgb_output(self):
        alg=Algorithm(); alg.initAlgorithm(); ctx=QgsProcessingContext()
        mask=self.mask(); ctx.temporaryLayerStore().addMapLayer(mask)
        with self.assertRaisesRegex(QgsProcessingException, 'arquivos diferentes'):
            alg.processAlgorithm({'INPUT_RASTER':str(self.source), 'PREPARATION_MODE':1,
                'MASK_LAYER':mask.id(), 'OUTPUT':str(self.root/'classified.tif'),
                'OUTPUT_POINTS':'memory:', 'OUTPUT_CLIPPED':str(self.source)},ctx,QgsProcessingFeedback())


if __name__ == '__main__':
    unittest.main()
