"""RGB vegetation classification and crop point-cloud generation algorithm for QGIS."""

import math
import os
import tempfile

import numpy as np
from osgeo import gdal
import scipy.ndimage as ndi
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterDestination,
    QgsProcessingParameterRasterLayer,
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
            defaultValue=5.0,
            minValue=0.5,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.POINT_SPACING_CM,
            'Espaçamento aproximado entre pontos da nuvem (cm)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=20.0,
            minValue=5.0,
            maxValue=200.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.GLI_THRESHOLD,
            'Ajuste fino de sensibilidade GLI (0 = automático adaptativo)',
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

        requested_pixel_cm = self.parameterAsDouble(
            parameters, self.PIXEL_SIZE_CM, context
        )
        point_spacing_cm = self.parameterAsDouble(
            parameters, self.POINT_SPACING_CM, context
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

        alpha_band = None
        for b_idx in range(1, band_count + 1):
            if b_idx in (red_band, green_band, blue_band):
                continue
            interp = src.GetRasterBand(b_idx).GetColorInterpretation()
            if interp == gdal.GCI_AlphaBand or b_idx == 4:
                alpha_band = b_idx
                break

        width, height = src.RasterXSize, src.RasterYSize
        transform = src.GetGeoTransform()
        source_crs = src.GetProjection()
        if not source_crs:
            src = None
            raise QgsProcessingException(
                'O raster não tem sistema de referência espacial definido.'
            )

        output_crs = crs
        reproject_to_utm = (
            crs.isGeographic() or crs.mapUnits() != QgsUnitTypes.DistanceMeters
        )
        if reproject_to_utm:
            output_crs = self._local_utm_crs(raster, crs, context)
            native_res_m = self._estimate_metric_pixel_size(
                raster, crs, output_crs, width, height, context
            )
            pixel_cm = max(requested_pixel_cm, native_res_m * 100.0 * 0.95)
            pixel_size_map_units = pixel_cm / 100.0
            feedback.pushInfo(
                f'Raster em unidades não métricas: reprojetando via VRT para '
                f'{output_crs.authid()} com pixel de {pixel_cm:g} cm.'
            )
        else:
            metres_per_map_unit = QgsUnitTypes.fromUnitToUnitFactor(
                crs.mapUnits(), QgsUnitTypes.DistanceMeters
            )
            if not metres_per_map_unit or not np.isfinite(metres_per_map_unit):
                src = None
                raise QgsProcessingException(
                    'Não foi possível converter as unidades do CRS para metros.'
                )
            native_px_w = math.hypot(transform[1], transform[4]) * metres_per_map_unit
            native_px_h = math.hypot(transform[2], transform[5]) * metres_per_map_unit
            native_res_m = min(native_px_w, native_px_h)
            native_cm = native_res_m * 100.0
            if requested_pixel_cm < native_cm * 0.95:
                pixel_cm = native_cm
                feedback.pushInfo(
                    f'Mantendo a resolução nativa do raster ({pixel_cm:.2f} cm) '
                    f'para evitar superamostragem artificial.'
                )
            else:
                pixel_cm = requested_pixel_cm
            pixel_size_map_units = pixel_cm / 100.0 / metres_per_map_unit

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

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='falha_plantio_rgb_') as temp_dir:
            band_list = [red_band, green_band, blue_band]
            if alpha_band is not None:
                band_list.append(alpha_band)

            vrt_path = os.path.join(temp_dir, 'rgb_input.vrt')
            vrt = gdal.BuildVRT(
                vrt_path,
                raster.source(),
                options=gdal.BuildVRTOptions(bandList=band_list),
            )
            if vrt is None:
                src = None
                raise QgsProcessingException('Não foi possível preparar as bandas RGB.')
            vrt = None

            need_warp = reproject_to_utm or (
                abs(pixel_size_map_units - abs(transform[1])) > abs(transform[1]) * 0.05
            ) or (transform[2] != 0.0 or transform[4] != 0.0)

            if need_warp:
                warped_vrt_path = os.path.join(temp_dir, 'rgb_warped.vrt')
                warp_options = {
                    'format': 'VRT',
                    'xRes': pixel_size_map_units,
                    'yRes': pixel_size_map_units,
                    'resampleAlg': 'bilinear',
                }
                if reproject_to_utm:
                    warp_options['dstSRS'] = output_crs.toWkt()
                else:
                    warp_options['outputBounds'] = bounds
                warped = gdal.Warp(
                    warped_vrt_path,
                    vrt_path,
                    options=gdal.WarpOptions(**warp_options),
                )
                if warped is None:
                    src = None
                    raise QgsProcessingException('Falha ao configurar grade de leitura RGB.')
                warped = None
                rgb = gdal.Open(warped_vrt_path, gdal.GA_ReadOnly)
            else:
                rgb = gdal.Open(vrt_path, gdal.GA_ReadOnly)

            src = None
            if rgb is None:
                raise QgsProcessingException('Falha ao abrir grade RGB para leitura.')

            out_width = rgb.RasterXSize
            out_height = rgb.RasterYSize
            has_alpha = rgb.RasterCount >= 4
            feedback.pushInfo(
                f'Grade de processamento: {out_width} × {out_height} pixels '
                f'({pixel_cm:.2f} cm/px) em {output_crs.authid()}.'
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
            result.SetMetadataItem('INDEX', 'Adaptive GLI + NGRDI')
            result.SetMetadataItem('GLI_THRESHOLD', str(threshold))
            result.SetMetadataItem('PIXEL_SIZE_CM', f'{pixel_cm:.2f}')

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
            pixel_size_m = min(pixel_width, pixel_height)
            if pixel_size_m <= 0:
                result = None
                rgb = None
                raise QgsProcessingException('O raster tem dimensão de pixel inválida.')

            # Keep point spacing accurate (never coarsen beyond 30 cm so row spacing ~1.5 m is well resolved)
            requested_spacing_m = point_spacing_cm / 100.0
            field_area_m2 = (out_width * pixel_width) * (out_height * pixel_height)
            if field_area_m2 > 500000.0 and requested_spacing_m < 0.20:
                effective_req_m = 0.20
            else:
                effective_req_m = requested_spacing_m
            point_stride = max(1, int(round(effective_req_m / pixel_size_m)))
            effective_spacing_cm = point_stride * pixel_size_m * 100.0
            feedback.pushInfo(
                f'Nuvem de pontos da cultura: espaçamento de {effective_spacing_cm:.1f} cm '
                f'(agregado por bloco com filtragem de palhada, sombra e mata).'
            )

            # Align tile size to a multiple of point_stride so every cell is self-contained inside a tile
            cells_per_tile = max(16, int(round(2048 / point_stride)))
            tile_step = cells_per_tile * point_stride
            halo_px = max(16, int(math.ceil(4.5 / pixel_size_m)))

            nodata_values = [rgb.GetRasterBand(i).GetNoDataValue() for i in (1, 2, 3)]
            # >= ~1/3 of the cell must be crop: with the completed vegetation mask this keeps every
            # cane cell while avoiding a halo of points outside the row centre
            min_pixels_per_cell = max(1, int(round((point_stride * point_stride) * 0.34)))

            tile_rows = int(math.ceil(out_height / tile_step))
            tile_cols = int(math.ceil(out_width / tile_step))
            total_tiles = max(1, tile_rows * tile_cols)
            tile_idx = 0
            point_count = 0
            point_batch = []

            for row0 in range(0, out_height, tile_step):
                if feedback.isCanceled():
                    result = None
                    rgb = None
                    return {}
                row1 = min(out_height, row0 + tile_step)
                r_pad0 = max(0, row0 - halo_px)
                r_pad1 = min(out_height, row1 + halo_px)
                win_h = r_pad1 - r_pad0
                inner_r0 = row0 - r_pad0
                inner_r1 = inner_r0 + (row1 - row0)

                for col0 in range(0, out_width, tile_step):
                    if feedback.isCanceled():
                        result = None
                        rgb = None
                        return {}
                    col1 = min(out_width, col0 + tile_step)
                    c_pad0 = max(0, col0 - halo_px)
                    c_pad1 = min(out_width, col1 + halo_px)
                    win_w = c_pad1 - c_pad0
                    inner_c0 = col0 - c_pad0
                    inner_c1 = inner_c0 + (col1 - col0)

                    red = rgb.GetRasterBand(1).ReadAsArray(c_pad0, r_pad0, win_w, win_h)
                    green = rgb.GetRasterBand(2).ReadAsArray(c_pad0, r_pad0, win_w, win_h)
                    blue = rgb.GetRasterBand(3).ReadAsArray(c_pad0, r_pad0, win_w, win_h)

                    valid = np.isfinite(red) & np.isfinite(green) & np.isfinite(blue)
                    for data, nodata in zip((red, green, blue), nodata_values):
                        if nodata is not None:
                            valid &= data != nodata
                    if has_alpha:
                        alpha = rgb.GetRasterBand(4).ReadAsArray(c_pad0, r_pad0, win_w, win_h)
                        valid &= alpha > 0
                    valid &= (red > 0) | (green > 0) | (blue > 0)

                    inner_valid = valid[inner_r0:inner_r1, inner_c0:inner_c1]
                    if not np.any(inner_valid):
                        empty_tile = np.full(
                            (row1 - row0, col1 - col0), 255, dtype=np.uint8
                        )
                        result_band.WriteArray(empty_tile, col0, row0)
                        tile_idx += 1
                        feedback.setProgress(95.0 * tile_idx / total_tiles)
                        continue

                    veg_mask, crop_mask, gli = self._classify_window(
                        red, green, blue, valid, pixel_size_m, threshold
                    )

                    inner_veg = veg_mask[inner_r0:inner_r1, inner_c0:inner_c1]
                    inner_crop = crop_mask[inner_r0:inner_r1, inner_c0:inner_c1]
                    inner_gli = gli[inner_r0:inner_r1, inner_c0:inner_c1]

                    out_tile = np.zeros((row1 - row0, col1 - col0), dtype=np.uint8)
                    out_tile[inner_veg] = 1
                    out_tile[~inner_valid] = 255
                    result_band.WriteArray(out_tile, col0, row0)

                    local_rows, local_cols = np.nonzero(inner_crop)
                    if local_rows.size:
                        n_cell_cols = int(math.ceil((col1 - col0) / point_stride))
                        cell_ids = (
                            (local_rows // point_stride) * n_cell_cols
                            + (local_cols // point_stride)
                        )
                        unique_ids, inverse = np.unique(cell_ids, return_inverse=True)
                        counts = np.bincount(inverse).astype(np.int32)
                        keep_cells = counts >= min_pixels_per_cell
                        if np.any(keep_cells):
                            global_rows = (row0 + local_rows).astype(np.float64)
                            global_cols = (col0 + local_cols).astype(np.float64)
                            row_sums = np.bincount(inverse, weights=global_rows)[keep_cells]
                            col_sums = np.bincount(inverse, weights=global_cols)[keep_cells]
                            gli_sums = np.bincount(
                                inverse, weights=inner_gli[local_rows, local_cols]
                            )[keep_cells]
                            kept_counts = counts[keep_cells]

                            mean_rows = row_sums / kept_counts
                            mean_cols = col_sums / kept_counts
                            mean_glis = gli_sums / kept_counts
                            xs = (
                                geotransform[0]
                                + (mean_cols + 0.5) * geotransform[1]
                                + (mean_rows + 0.5) * geotransform[2]
                            )
                            ys = (
                                geotransform[3]
                                + (mean_cols + 0.5) * geotransform[4]
                                + (mean_rows + 0.5) * geotransform[5]
                            )

                            for x_pt, y_pt, gli_pt, cnt_pt in zip(
                                    xs, ys, mean_glis, kept_counts):
                                feat = QgsFeature(point_fields)
                                feat.setGeometry(
                                    QgsGeometry.fromPointXY(
                                        QgsPointXY(float(x_pt), float(y_pt))
                                    )
                                )
                                feat.setAttributes([float(gli_pt), 1, int(cnt_pt)])
                                point_batch.append(feat)
                                point_count += 1
                                if len(point_batch) >= 10000:
                                    if not point_sink.addFeatures(
                                            point_batch, QgsFeatureSink.FastInsert):
                                        raise QgsProcessingException(
                                            'Erro ao gravar pontos da cultura no GeoPackage.'
                                        )
                                    point_batch = []

                    tile_idx += 1
                    feedback.setProgress(95.0 * tile_idx / total_tiles)

            if point_batch and not point_sink.addFeatures(
                    point_batch, QgsFeatureSink.FastInsert):
                raise QgsProcessingException(
                    'Erro ao gravar os últimos pontos da cultura no GeoPackage.'
                )
            point_sink = None
            result_band.FlushCache()
            result.FlushCache()
            result = None
            rgb = None
            feedback.setProgress(100.0)

        feedback.pushInfo(
            'Classificação concluída: 1 = vegetação verde; 0 = palhada/solo; '
            '255 = NoData.'
        )
        feedback.pushInfo(f'Pontos representativos da cultura gravados: {point_count}.')
        return {self.OUTPUT: output_path, self.OUTPUT_POINTS: point_destination}

    def _classify_window(self, red, green, blue, valid, pixel_size_m, gli_threshold):
        """
        Classify green vegetation and extract crop-row pixels while rejecting yellow straw
        (palhada), bare soil tracks (carreadores), cloud shadow shifts, and dense forest (mata).
        """
        r_f = red.astype(np.float32)
        g_f = green.astype(np.float32)
        b_f = blue.astype(np.float32)

        denom_gli = 2.0 * g_f + r_f + b_f + 1e-6
        gli = (2.0 * g_f - r_f - b_f) / denom_gli
        ngrdi = (g_f - r_f) / (g_f + r_f + 1e-6)

        is_pure_green = (
            valid
            & (gli > 0.08 + gli_threshold * 0.5)
            & (ngrdi > 0.01 + gli_threshold * 0.5)
            & (g_f > r_f)
            & (g_f > b_f)
        )
        # soft green: shaded / dense / low-contrast cane that still is clearly vegetation
        is_soft_green = (
            valid
            & (gli > 0.025 + gli_threshold * 0.5)
            & (ngrdi > -0.035 + gli_threshold * 0.5)
            & (g_f > b_f)
            & (g_f >= 0.97 * r_f)
        )

        h, w = gli.shape
        # Compute spatial background statistics on a ~15 cm sub-grid for high speed
        ds_factor = max(1, int(round(0.15 / max(0.01, pixel_size_m))))
        if ds_factor > 1 and h >= ds_factor * 8 and w >= ds_factor * 8:
            sh = h // ds_factor
            sw = w // ds_factor
            h_trim = sh * ds_factor
            w_trim = sw * ds_factor

            v_sub = valid[:h_trim, :w_trim].reshape(sh, ds_factor, sw, ds_factor).mean(axis=(1, 3)).astype(np.float32)
            g_masked = np.where(valid[:h_trim, :w_trim], gli[:h_trim, :w_trim], 0.0)
            n_masked = np.where(valid[:h_trim, :w_trim], ngrdi[:h_trim, :w_trim], 0.0)
            gli_sub = g_masked.reshape(sh, ds_factor, sw, ds_factor).mean(axis=(1, 3))
            ngrdi_sub = n_masked.reshape(sh, ds_factor, sw, ds_factor).mean(axis=(1, 3))
            sub_res = pixel_size_m * ds_factor
            pg_sub = is_pure_green[:h_trim, :w_trim].reshape(sh, ds_factor, sw, ds_factor).mean(axis=(1, 3)).astype(np.float32)
        else:
            ds_factor = 1
            v_sub = valid.astype(np.float32)
            gli_sub = np.where(valid, gli, 0.0)
            ngrdi_sub = np.where(valid, ngrdi, 0.0)
            sub_res = pixel_size_m
            pg_sub = is_pure_green.astype(np.float32)

        win_px = max(3, int(round(0.85 / max(0.01, sub_res))))
        if win_px % 2 == 0:
            win_px += 1
        inv_den = 1.0 / (ndi.uniform_filter(v_sub, size=win_px) + 1e-6)
        gli_bg_sub = ndi.uniform_filter(gli_sub, size=win_px) * inv_den
        ngrdi_bg_sub = ndi.uniform_filter(ngrdi_sub, size=win_px) * inv_den

        v_norm = np.maximum(v_sub, 1e-6)
        d_gli_sub = (gli_sub / v_norm) - gli_bg_sub
        d_ngrdi_sub = (ngrdi_sub / v_norm) - ngrdi_bg_sub
        lc_sub = 0.55 * d_gli_sub + 0.45 * d_ngrdi_sub

        broad_px = max(9, int(round(4.5 / max(0.01, sub_res))))
        broad_den = 1.0 / (ndi.uniform_filter(v_sub, size=broad_px) + 1e-6)
        mad_sub = ndi.uniform_filter(np.abs(lc_sub) * v_sub, size=broad_px) * broad_den
        broad_gli_sub = ndi.uniform_filter(gli_sub, size=broad_px) * broad_den
        broad_ngrdi_sub = ndi.uniform_filter(ngrdi_sub, size=broad_px) * broad_den

        # a forest/APP canopy is (almost) continuous green; cane rows always leave bare soil
        # between rows, so dense healthy cane must NOT be mistaken for forest
        pg_cover = ndi.uniform_filter(pg_sub * v_sub, size=broad_px) * broad_den
        forest_core_sub = (broad_gli_sub > 0.085) & (broad_ngrdi_sub > -0.005) & (pg_cover > 0.60)
        buf_px = max(5, int(round(7.0 / max(0.01, sub_res))))
        forest_buf_sub = ndi.uniform_filter(forest_core_sub.astype(np.float32), size=buf_px) > 0.10

        if ds_factor > 1:
            zoom_y = h / gli_bg_sub.shape[0]
            zoom_x = w / gli_bg_sub.shape[1]
            gli_bg = ndi.zoom(gli_bg_sub, (zoom_y, zoom_x), order=1)[:h, :w]
            ngrdi_bg = ndi.zoom(ngrdi_bg_sub, (zoom_y, zoom_x), order=1)[:h, :w]
            local_mad = ndi.zoom(mad_sub, (zoom_y, zoom_x), order=1)[:h, :w]
            forest_buffer = ndi.zoom(forest_buf_sub.astype(np.float32), (zoom_y, zoom_x), order=0)[:h, :w] > 0.5
        else:
            gli_bg = gli_bg_sub
            ngrdi_bg = ngrdi_bg_sub
            local_mad = mad_sub
            forest_buffer = forest_buf_sub

        d_gli = gli - gli_bg
        d_ngrdi = ngrdi - ngrdi_bg
        local_contrast = 0.55 * d_gli + 0.45 * d_ngrdi

        rel_thresh = np.maximum(0.0045, 0.55 * local_mad) + gli_threshold * 0.20

        is_row_veg = (
            valid
            & (local_contrast > rel_thresh)
            & (d_gli > 0.003)
            & (d_ngrdi > 0.002)
            & (gli > 0.005 + gli_threshold * 0.5)
            & (ngrdi > -0.085 + gli_threshold * 0.5)
            & (g_f > b_f)
        )


        veg_raster_mask = is_row_veg | is_pure_green
        if pixel_size_m < 0.06:
            veg_raster_mask = ndi.binary_opening(
                veg_raster_mask, structure=np.ones((2, 2), dtype=bool)
            )
            is_row_veg = is_row_veg & veg_raster_mask

        # points must cover ALL visible cane: contrast-detected rows, clearly green pixels and
        # soft (shaded / dense) green that is part of a green blob
        core_veg = is_row_veg | is_pure_green
        near_px = max(3, int(round(0.30 / max(0.01, pixel_size_m))))
        soft_ok = is_soft_green & (ndi.maximum_filter(core_veg, size=near_px | 1) > 0)
        point_veg = core_veg | soft_ok
        if pixel_size_m < 0.06:
            point_veg = ndi.binary_opening(point_veg, structure=np.ones((2, 2), dtype=bool))
        crop_point_mask = point_veg & (~forest_buffer)
        return veg_raster_mask, crop_point_mask, gli

    def _estimate_metric_pixel_size(self, raster, source_crs, utm_crs, width, height, context):
        try:
            tr = QgsCoordinateTransform(source_crs, utm_crs, context.transformContext())
            ext_m = tr.transformBoundingBox(raster.extent())
            return min(ext_m.width() / max(1, width), ext_m.height() / max(1, height))
        except Exception:
            return 0.05

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
            'Classifica a cobertura vegetal de cana-de-açúcar em imagens RGB '
            'combinando os índices GLI = (2G − R − B)/(2G + R + B) e '
            'NGRDI = (G − R)/(G + R) com filtragem espacial adaptativa local '
            '(resistente à palhada seca, solo exposto e sombras de nuvens).\n\n'
            'Gera:\n'
            '1. Um GeoTIFF classificado (1 = vegetação verde, 0 = palhada/solo, '
            '255 = NoData/borda transparente).\n'
            '2. Uma nuvem de pontos GeoPackage centrada nas touceiras/fileiras '
            'da cultura (filtrando automaticamente manchas densas de mata/APP e '
            'carreadores).\n\n'
            'O processamento usa leitura direta em blocos via VRT (sem duplicar '
            'dezenas de GB em arquivos temporários) e preserva a resolução '
            'espacial efetiva da imagem.'
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
