"""Initial RGB vegetation classification algorithm for the QGIS plugin."""

import math
import os
import tempfile

import numpy as np
from osgeo import gdal
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsUnitTypes,
    QgsWkbTypes,
)


class FalhaDePlantioAlgorithm(QgsProcessingAlgorithm):
    INPUT_RASTER = 'INPUT_RASTER'
    RED_BAND = 'RED_BAND'
    GREEN_BAND = 'GREEN_BAND'
    BLUE_BAND = 'BLUE_BAND'
    PIXEL_SIZE_CM = 'PIXEL_SIZE_CM'
    POINT_SPACING_CM = 'POINT_SPACING_CM'
    GLI_THRESHOLD = 'GLI_THRESHOLD'
    OUTPUT = 'OUTPUT'
    OUTPUT_POINTS = 'OUTPUT_POINTS'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_RASTER,
            'Raster de entrada (imagem RGB)',
        ))
        for key, label, default in (
                (self.RED_BAND, 'Banda vermelha (R)', 1),
                (self.GREEN_BAND, 'Banda verde (G)', 2),
                (self.BLUE_BAND, 'Banda azul (B)', 3)):
            self.addParameter(QgsProcessingParameterNumber(
                key, label, type=QgsProcessingParameterNumber.Integer,
                defaultValue=default, minValue=1,
            ))
        self.addParameter(QgsProcessingParameterNumber(
            self.PIXEL_SIZE_CM,
            'Tamanho do pixel de saída (cm)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=3.0,
            minValue=0.01,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.POINT_SPACING_CM,
            'Espaçamento aproximado entre pontos da nuvem (cm)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=10.0,
            minValue=1.0,
            maxValue=1000.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.GLI_THRESHOLD,
            'Limiar GLI para classificar como vegetação',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.0,
            minValue=-1.0,
            maxValue=1.0,
        ))
        self.addParameter(QgsProcessingParameterRasterDestination(
            self.OUTPUT,
            'Classificação de vegetação (GeoTIFF)',
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_POINTS,
            'Nuvem de pontos da cultura (GeoPackage)',
            type=QgsProcessing.TypeVectorPoint,
        ))

    def processAlgorithm(self, parameters, context, feedback):
        raster = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        if raster is None or not raster.isValid():
            raise QgsProcessingException('Selecione um raster de entrada válido.')

        crs = raster.crs()
        if not crs.isValid():
            raise QgsProcessingException('O raster não tem um CRS válido definido.')
        pixel_cm = self.parameterAsDouble(parameters, self.PIXEL_SIZE_CM, context)
        point_spacing_cm = self.parameterAsDouble(
            parameters, self.POINT_SPACING_CM, context
        )

        output_crs = crs
        reproject_to_utm = (
            crs.isGeographic() or crs.mapUnits() != QgsUnitTypes.DistanceMeters
        )
        if reproject_to_utm:
            output_crs = self._local_utm_crs(raster, crs, context)
            pixel_size_map_units = pixel_cm / 100.0
            feedback.pushInfo(
                f'Raster em unidades não métricas: reprojetando automaticamente para '
                f'{output_crs.authid()} com pixel de {pixel_cm:g} cm.'
            )
        else:
            metres_per_map_unit = QgsUnitTypes.fromUnitToUnitFactor(
                crs.mapUnits(), QgsUnitTypes.DistanceMeters)
            if not metres_per_map_unit or not np.isfinite(metres_per_map_unit):
                raise QgsProcessingException(
                    'Não foi possível converter as unidades do CRS para metros.'
                )
            pixel_size_map_units = (
                pixel_cm / 100.0 / metres_per_map_unit
            )

        threshold = self.parameterAsDouble(parameters, self.GLI_THRESHOLD, context)
        red_band = self.parameterAsInt(parameters, self.RED_BAND, context)
        green_band = self.parameterAsInt(parameters, self.GREEN_BAND, context)
        blue_band = self.parameterAsInt(parameters, self.BLUE_BAND, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        src = gdal.Open(raster.source(), gdal.GA_ReadOnly)
        if src is None:
            raise QgsProcessingException('O GDAL não conseguiu abrir o raster selecionado.')
        band_count = src.RasterCount
        if any(band < 1 or band > band_count
               for band in (red_band, green_band, blue_band)):
            src = None
            raise QgsProcessingException(
                f'O raster possui {band_count} banda(s). Ajuste os números das bandas RGB.'
            )
        if len(set((red_band, green_band, blue_band))) != 3:
            src = None
            raise QgsProcessingException('As bandas R, G e B devem ser diferentes.')

        width, height = src.RasterXSize, src.RasterYSize
        transform = src.GetGeoTransform()
        source_crs = src.GetProjection()
        if not source_crs:
            src = None
            raise QgsProcessingException(
                'O raster não tem sistema de referência espacial definido.'
            )

        corners = [
            (transform[0] + col * transform[1] + row * transform[2],
             transform[3] + col * transform[4] + row * transform[5])
            for col, row in ((0, 0), (width, 0), (0, height), (width, height))
        ]
        bounds = (
            min(point[0] for point in corners),
            min(point[1] for point in corners),
            max(point[0] for point in corners),
            max(point[1] for point in corners),
        )
        src = None

        feedback.pushInfo(f'Resolução solicitada: {pixel_cm:g} cm.')
        feedback.pushInfo(
            'O tamanho configurado define o espaçamento dos pixels no GeoTIFF; '
            'não cria detalhe além da resolução espacial original da imagem.'
        )

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='falha_plantio_rgb_') as temp_dir:
            vrt_path = os.path.join(temp_dir, 'rgb.vrt')
            rgb_path = os.path.join(temp_dir, 'rgb_resampled.tif')
            vrt = gdal.BuildVRT(
                vrt_path,
                raster.source(),
                options=gdal.BuildVRTOptions(
                    bandList=[red_band, green_band, blue_band]
                ),
            )
            if vrt is None:
                raise QgsProcessingException('Não foi possível preparar as bandas RGB.')
            vrt = None

            def warp_progress(_complete, _message, _data):
                return 0 if feedback.isCanceled() else 1

            warp_options = {
                'format': 'GTiff',
                'xRes': pixel_size_map_units,
                'yRes': pixel_size_map_units,
                'resampleAlg': 'bilinear',
                'outputType': gdal.GDT_Float32,
                'creationOptions': ['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=IF_SAFER'],
                'callback': warp_progress,
            }
            if reproject_to_utm:
                warp_options['dstSRS'] = output_crs.toWkt()
            else:
                warp_options['outputBounds'] = bounds
            warped = gdal.Warp(
                rgb_path,
                vrt_path,
                options=gdal.WarpOptions(**warp_options),
            )
            if warped is None:
                if feedback.isCanceled():
                    return {}
                raise QgsProcessingException('Falha ao reamostrar as bandas RGB.')
            warped = None
            if feedback.isCanceled():
                return {}

            rgb = gdal.Open(rgb_path, gdal.GA_ReadOnly)
            out_width = rgb.RasterXSize
            out_height = rgb.RasterYSize
            feedback.pushInfo(
                f'Grade de saída: {out_width} × {out_height} pixels em '
                f'{output_crs.authid()}.'
            )
            driver = gdal.GetDriverByName('GTiff')
            result = driver.Create(
                output_path, out_width, out_height, 1, gdal.GDT_Byte,
                options=['TILED=YES', 'COMPRESS=DEFLATE', 'BIGTIFF=IF_SAFER'],
            )
            if result is None:
                rgb = None
                raise QgsProcessingException(f'Não foi possível criar: {output_path}')
            result.SetGeoTransform(rgb.GetGeoTransform())
            result.SetProjection(rgb.GetProjection())
            result.SetMetadataItem('CLASS_0', 'Sem vegetação verde detectada')
            result.SetMetadataItem('CLASS_1', 'Vegetação verde detectada')
            result.SetMetadataItem('INDEX', 'GLI=(2*G-R-B)/(2*G+R+B)')
            result.SetMetadataItem('GLI_THRESHOLD', str(threshold))
            result.SetMetadataItem('PIXEL_SIZE_CM', str(pixel_cm))

            result_band = result.GetRasterBand(1)
            result_band.SetNoDataValue(255)
            color_table = gdal.ColorTable()
            color_table.SetColorEntry(0, (220, 50, 50, 255))
            color_table.SetColorEntry(1, (20, 180, 40, 255))
            color_table.SetColorEntry(255, (0, 0, 0, 0))
            result_band.SetRasterColorTable(color_table)
            result_band.SetRasterColorInterpretation(gdal.GCI_PaletteIndex)

            point_fields = QgsFields()
            point_fields.append(QgsField('gli', QVariant.Double, len=12, prec=7))
            point_fields.append(QgsField('classe', QVariant.Int))
            point_fields.append(QgsField('pixel_count', QVariant.Int))
            point_sink, point_destination = self.parameterAsSink(
                parameters,
                self.OUTPUT_POINTS,
                context,
                point_fields,
                QgsWkbTypes.Point,
                output_crs,
            )
            if point_sink is None:
                result = None
                rgb = None
                raise QgsProcessingException('Não foi possível criar a nuvem de pontos.')

            geotransform = rgb.GetGeoTransform()
            pixel_width = math.hypot(geotransform[1], geotransform[4])
            pixel_height = math.hypot(geotransform[2], geotransform[5])
            if pixel_width <= 0 or pixel_height <= 0:
                result = None
                rgb = None
                raise QgsProcessingException('O raster reamostrado tem pixels inválidos.')
            requested_spacing_m = point_spacing_cm / 100.0
            pixel_size_m = min(pixel_width, pixel_height)
            point_stride = max(1, int(math.ceil(requested_spacing_m / pixel_size_m)))
            grid_rows = int(math.ceil(out_height / point_stride))
            grid_columns = int(math.ceil(out_width / point_stride))
            max_grid_cells = 2000000
            while grid_rows * grid_columns > max_grid_cells:
                scale_up = math.sqrt(grid_rows * grid_columns / max_grid_cells)
                point_stride = max(
                    point_stride + 1,
                    int(math.ceil(point_stride * scale_up)),
                )
                grid_rows = int(math.ceil(out_height / point_stride))
                grid_columns = int(math.ceil(out_width / point_stride))
            effective_spacing_cm = point_stride * pixel_size_m * 100.0
            feedback.pushInfo(
                f'Nuvem representativa: espaçamento aproximado '
                f'{effective_spacing_cm:.1f} cm; classificação mantém resolução '
                f'{pixel_cm:g} cm.'
            )

            # Keep one compact accumulator per output point cell. The dense
            # pixel classification stays full resolution; only the auxiliary
            # vector point cloud is spatially sampled for processing speed.
            cell_total = grid_rows * grid_columns
            point_counts = np.zeros(cell_total, dtype=np.uint32)
            point_row_sums = np.zeros(cell_total, dtype=np.float64)
            point_column_sums = np.zeros(cell_total, dtype=np.float64)
            point_gli_sums = np.zeros(cell_total, dtype=np.float64)

            block_rows = 256
            block_columns = 1024
            nodata_values = [rgb.GetRasterBand(i).GetNoDataValue() for i in (1, 2, 3)]
            tile_count = (
                int(math.ceil(out_height / block_rows))
                * int(math.ceil(out_width / block_columns))
            )
            tile_index = 0
            for row in range(0, out_height, block_rows):
                if feedback.isCanceled():
                    result = None
                    rgb = None
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass
                    return {}
                rows = min(block_rows, out_height - row)
                for column in range(0, out_width, block_columns):
                    if feedback.isCanceled():
                        result = None
                        rgb = None
                        try:
                            os.remove(output_path)
                        except OSError:
                            pass
                        return {}
                    columns = min(block_columns, out_width - column)
                    red = rgb.GetRasterBand(1).ReadAsArray(column, row, columns, rows)
                    green = rgb.GetRasterBand(2).ReadAsArray(column, row, columns, rows)
                    blue = rgb.GetRasterBand(3).ReadAsArray(column, row, columns, rows)
                    denominator = 2.0 * green + red + blue
                    gli = np.zeros(denominator.shape, dtype=np.float32)
                    np.divide(2.0 * green - red - blue, denominator,
                              out=gli, where=denominator != 0)
                    vegetation = np.zeros(denominator.shape, dtype=np.uint8)
                    vegetation[gli > threshold] = 1
                    valid = np.isfinite(red) & np.isfinite(green) & np.isfinite(blue)
                    for data, nodata in zip((red, green, blue), nodata_values):
                        if nodata is not None:
                            valid &= data != nodata
                    vegetation[~valid] = 255
                    result_band.WriteArray(vegetation, column, row)

                    local_rows, local_columns = np.nonzero(vegetation == 1)
                    if local_rows.size:
                        global_rows = row + local_rows
                        global_columns = column + local_columns
                        cell_ids = (
                            (global_rows // point_stride) * grid_columns
                            + global_columns // point_stride
                        )
                        unique_ids, inverse = np.unique(cell_ids, return_inverse=True)
                        counts = np.bincount(inverse).astype(np.uint32)
                        point_counts[unique_ids] += counts
                        point_row_sums[unique_ids] += np.bincount(
                            inverse, weights=global_rows
                        )
                        point_column_sums[unique_ids] += np.bincount(
                            inverse, weights=global_columns
                        )
                        point_gli_sums[unique_ids] += np.bincount(
                            inverse, weights=gli[local_rows, local_columns]
                        )
                    tile_index += 1
                    feedback.setProgress(80.0 * tile_index / max(1, tile_count))

            occupied_cells = np.flatnonzero(point_counts)
            point_batch = []
            point_count = 0
            for cell_id in occupied_cells:
                if point_count % 5000 == 0 and feedback.isCanceled():
                    result = None
                    rgb = None
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass
                    return {}
                count = int(point_counts[cell_id])
                pixel_row = point_row_sums[cell_id] / count
                pixel_column = point_column_sums[cell_id] / count
                x = (geotransform[0] + (pixel_column + 0.5) * geotransform[1]
                     + (pixel_row + 0.5) * geotransform[2])
                y = (geotransform[3] + (pixel_column + 0.5) * geotransform[4]
                     + (pixel_row + 0.5) * geotransform[5])
                feature = QgsFeature(point_fields)
                feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
                feature.setAttributes([
                    float(point_gli_sums[cell_id] / count), 1, count
                ])
                point_batch.append(feature)
                point_count += 1
                if len(point_batch) >= 5000:
                    if not point_sink.addFeatures(
                            point_batch, QgsFeatureSink.FastInsert):
                        raise QgsProcessingException(
                            'Erro ao gravar pontos da cultura no GeoPackage.'
                        )
                    point_batch = []
                if point_count % 5000 == 0:
                    feedback.setProgress(
                        80.0 + 20.0 * point_count / max(1, len(occupied_cells))
                    )
            if point_batch and not point_sink.addFeatures(
                    point_batch, QgsFeatureSink.FastInsert):
                raise QgsProcessingException(
                    'Erro ao gravar os últimos pontos da cultura no GeoPackage.'
                )
            feedback.setProgress(100.0)
            point_sink = None

            result_band.FlushCache()
            result.FlushCache()
            result = None
            rgb = None

        feedback.pushInfo(
            'Classificação concluída: 1 = vegetação verde; 0 = sem vegetação verde; '
            '255 = NoData.'
        )
        feedback.pushInfo(f'Pontos de vegetação gravados: {point_count}.')
        return {self.OUTPUT: output_path, self.OUTPUT_POINTS: point_destination}

    def name(self):
        return 'classificar_vegetacao_rgb'

    def displayName(self):
        return 'Classificar vegetação verde (RGB)'

    def group(self):
        return 'Análise de falhas'

    def groupId(self):
        return 'analise_falhas'

    def createInstance(self):
        return FalhaDePlantioAlgorithm()

    def shortHelpString(self):
        return (
            'Classifica cada pixel de uma imagem RGB como vegetação verde (1) ou '
            'sem vegetação verde (0), usando o índice GLI: '
            '(2G − R − B) / (2G + R + B). Pixels NoData recebem o valor 255.\n\n'
            'Escolha as bandas R, G e B conforme a ordem do seu raster, informe o '
            'limiar GLI e o tamanho de pixel de saída em centímetros. O algoritmo '
            'grava a classificação em GeoTIFF e cria uma camada de pontos GeoPackage '
            'com pontos representativos agregados em células espaciais. O raster mantém '
            'todos os pixels classificados; ajuste o espaçamento dos pontos para equilibrar '
            'detalhe e velocidade. O raster precisa '
            'usar um CRS definido. Se estiver em graus ou unidades não métricas, '
            'a saída será reprojetada automaticamente para a zona UTM local.\n\n'
            'A resolução de saída define o espaçamento dos pixels e não aumenta o '
            'detalhe real da imagem. Esta etapa detecta cobertura verde em RGB; '
            'ela não distingue cana de plantas daninhas sem linhas de plantio, '
            'bandas adicionais ou treinamento/classificação específica. A saída de '
            'pontos é 2D porque uma imagem RGB não contém elevação.'
        )

    def helpUrl(self):
        return 'https://github.com/CainC0de/Analise-de-falha-QGIS'

    def _local_utm_crs(self, raster, source_crs, context):
        """Choose the UTM zone at the raster center and return its CRS."""
        wgs84 = QgsCoordinateReferenceSystem('EPSG:4326')
        transform = QgsCoordinateTransform(
            source_crs, wgs84, context.transformContext()
        )
        try:
            center = transform.transform(raster.extent().center())
        except Exception as exc:
            raise QgsProcessingException(
                f'Não foi possível localizar a zona UTM da imagem: {exc}'
            )
        longitude, latitude = center.x(), center.y()
        if not (-180 <= longitude <= 180 and -80 <= latitude <= 84):
            raise QgsProcessingException(
                'A imagem está fora da área de cobertura UTM automática '
                '(latitude entre 80°S e 84°N).'
            )
        zone = min(60, max(1, int((longitude + 180) // 6) + 1))
        epsg = (32700 if latitude < 0 else 32600) + zone
        target = QgsCoordinateReferenceSystem(f'EPSG:{epsg}')
        if not target.isValid():
            raise QgsProcessingException(
                f'Não foi possível criar o CRS UTM EPSG:{epsg}.'
            )
        return target
