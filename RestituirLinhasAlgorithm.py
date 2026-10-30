"""Reconstruct individual sugarcane row lines (straight or contour-curved) and analyze planting gaps."""

import math
import os
import tempfile

import numpy as np
from osgeo import gdal
import scipy.ndimage as ndi
from scipy.signal import fftconvolve
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
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
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorLayer,
    QgsUnitTypes,
    QgsWkbTypes,
)


class RestituirLinhasAlgorithm(QgsProcessingAlgorithm):
    INPUT_RASTER = 'INPUT_RASTER'
    INPUT_POINTS = 'INPUT_POINTS'
    INPUT_PLANNED_LINES = 'INPUT_PLANNED_LINES'
    ROW_SPACING = 'ROW_SPACING'
    MAX_DEVIATION = 'MAX_DEVIATION'
    MAX_GAP = 'MAX_GAP'
    MIN_POINTS_PER_BIN = 'MIN_POINTS_PER_BIN'
    PLANNED_MAX_OFFSET = 'PLANNED_MAX_OFFSET'
    MIN_CROP_RUN = 'MIN_CROP_RUN'
    OUTPUT = 'OUTPUT'
    OUTPUT_GAPS = 'OUTPUT_GAPS'
    POINT_BATCH = 100000

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_RASTER, 'Imagem de referência (raster)',
        ))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_POINTS,
            'Nuvem de pontos classificados como cultura',
            types=[QgsProcessing.TypeVectorPoint],
        ))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_PLANNED_LINES,
            'Camada de linhas projetadas (opcional — restitui locais sem cana, alinha tiros retos e centraliza linhas deslocadas)',
            types=[QgsProcessing.TypeVectorLine],
            optional=True,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.ROW_SPACING,
            'Espaçamento esperado entre linhas (m)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1.5,
            minValue=0.5,
            maxValue=4.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_DEVIATION,
            'Deslocamento lateral máximo por metro longitudinal (m/m)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1.0,
            minValue=0.05,
            maxValue=1.5,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_GAP,
            'Maior lacuna longitudinal que pode ser interpolada (m)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=10.0,
            minValue=0.5,
            maxValue=20.0,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_POINTS_PER_BIN,
            'Mínimo de pontos na densidade local para reconhecer a fileira',
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=4,
            minValue=1,
            maxValue=1000,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.PLANNED_MAX_OFFSET,
            'Linhas projetadas: afastamento lateral máximo para seguir os pés de cana (m)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.70,
            minValue=0.20,
            maxValue=1.50,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.MIN_CROP_RUN,
            'Linhas projetadas: comprimento mínimo de trecho com cana para centralizar nos pés (m)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=1.5,
            minValue=0.5,
            maxValue=10.0,
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT,
            'Linhas de plantio restituídas',
            type=QgsProcessing.TypeVectorLine,
        ))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_GAPS,
            'Segmentos de falha de plantio (> 0,5 m)',
            type=QgsProcessing.TypeVectorLine,
            optional=True,
            createByDefault=True,
        ))

    def processAlgorithm(self, parameters, context, feedback):
        raster = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        points = self.parameterAsVectorLayer(parameters, self.INPUT_POINTS, context)
        planned_layer = self.parameterAsVectorLayer(
            parameters, self.INPUT_PLANNED_LINES, context
        )
        if raster is None or not raster.isValid():
            raise QgsProcessingException('Selecione a imagem raster usada na análise.')
        if points is None or not points.isValid():
            raise QgsProcessingException('Selecione a nuvem de pontos da cultura.')
        if not raster.crs().isValid():
            raise QgsProcessingException('A imagem de referência não tem um CRS válido.')
        crs = points.crs()
        if not crs.isValid() or crs.isGeographic():
            raise QgsProcessingException(
                'A nuvem de pontos precisa estar em um CRS projetado.'
            )
        if crs.mapUnits() != QgsUnitTypes.DistanceMeters:
            raise QgsProcessingException(
                'A nuvem de pontos precisa usar um CRS projetado em metros.'
            )

        try:
            transform = QgsCoordinateTransform(
                raster.crs(), crs, context.transformContext()
            )
            image_extent = transform.transformBoundingBox(raster.extent())
        except Exception as exc:
            raise QgsProcessingException(
                f'Não foi possível alinhar a imagem e a nuvem de pontos: {exc}'
            )

        has_planned = planned_layer is not None and planned_layer.isValid()
        planned_transform = None
        combined_vec_extent = points.extent()
        if has_planned:
            try:
                if planned_layer.crs().isValid() and planned_layer.crs() != crs:
                    planned_transform = QgsCoordinateTransform(
                        planned_layer.crs(), crs, context.transformContext()
                    )
                    planned_ext = planned_transform.transformBoundingBox(
                        planned_layer.extent()
                    )
                else:
                    planned_ext = planned_layer.extent()
                if not planned_ext.isEmpty():
                    if combined_vec_extent.isEmpty():
                        combined_vec_extent = planned_ext
                    else:
                        combined_vec_extent.combineExtentWith(planned_ext)
            except Exception as exc:
                raise QgsProcessingException(
                    f'Não foi possível alinhar a camada de linhas projetadas: {exc}'
                )

        if not image_extent.intersects(combined_vec_extent):
            raise QgsProcessingException(
                'As camadas vetoriais não estão dentro da área da imagem selecionada.'
            )

        spacing = self.parameterAsDouble(parameters, self.ROW_SPACING, context)
        max_deviation = self.parameterAsDouble(parameters, self.MAX_DEVIATION, context)
        max_gap = self.parameterAsDouble(parameters, self.MAX_GAP, context)
        min_points = self.parameterAsInt(parameters, self.MIN_POINTS_PER_BIN, context)
        planned_max_offset = self.parameterAsDouble(parameters, self.PLANNED_MAX_OFFSET, context)
        min_crop_run = self.parameterAsDouble(parameters, self.MIN_CROP_RUN, context)

        work_extent = image_extent.intersect(combined_vec_extent)
        pad_m = max(2.0, spacing * 2.0)
        xmin = work_extent.xMinimum() - pad_m
        ymin = work_extent.yMinimum() - pad_m
        xmax = work_extent.xMaximum() + pad_m
        ymax = work_extent.yMaximum() + pad_m

        grid_res = min(0.15, max(0.10, spacing / 10.0)) if has_planned else min(0.20, max(0.10, spacing / 8.0))
        gw = max(16, int(math.ceil((xmax - xmin) / grid_res)))
        gh = max(16, int(math.ceil((ymax - ymin) / grid_res)))
        while gw * gh > 80000000:
            grid_res *= 1.15
            gw = max(16, int(math.ceil((xmax - xmin) / grid_res)))
            gh = max(16, int(math.ceil((ymax - ymin) / grid_res)))

        feedback.pushInfo(
            f'Construindo grade espacial de análise ({gw} × {gh} células de '
            f'{grid_res * 100:.1f} cm)...'
        )
        point_density, point_count = self._accumulate_points_grid(
            points, image_extent, xmin, ymax, grid_res, gw, gh, feedback
        )
        if feedback.isCanceled():
            return {}
        if point_count < 10 and not has_planned:
            raise QgsProcessingException(
                'Há menos de dez pontos da nuvem dentro da imagem selecionada.'
            )

        raster_density, green_contrast, valid_field_mask = self._extract_raster_crop_grid(
            raster, crs, xmin, ymin, xmax, ymax, gw, gh, grid_res, context, feedback
        )
        if feedback.isCanceled():
            return {}

        density = self._fuse_point_and_raster_density(
            point_density, raster_density, grid_res, spacing, feedback
        )
        del point_density
        if feedback.isCanceled():
            return {}

        if has_planned:
            feedback.setProgress(35.0)
            feedback.pushInfo(
                'Restituindo linhas guiadas pela camada de linhas projetadas '
                '(centralizando na cultura, alinhando tiros retos e cobrindo locais sem cana)...'
            )
            polylines, gap_segments = self._reconstruct_from_planned_lines(
                planned_layer, planned_transform, image_extent,
                density, raster_density, green_contrast, valid_field_mask,
                grid_res, spacing, xmin, ymax, gw, gh, feedback,
                max_offset=planned_max_offset, min_run=min_crop_run
            )
            del raster_density, green_contrast, valid_field_mask
            if feedback.isCanceled():
                return {}
        else:
            del raster_density, green_contrast, valid_field_mask
            feedback.setProgress(25.0)
            feedback.pushInfo(
                'Estimando campo de orientação local 2D (suporte a curvas de nível, '
                'terraços embutidos e múltiplos talhões)...'
            )
            theta_full, coh_full = self._build_local_orientation_field(
                density, grid_res, spacing, feedback
            )
            if feedback.isCanceled():
                return {}

            feedback.setProgress(45.0)
            feedback.pushInfo(
                'Aplicando filtragem direcional adaptativa em blocos para ressaltar '
                'os centros das fileiras...'
            )
            resp = self._steerable_ridge_filter_tiled(
                density, theta_full, coh_full, grid_res, spacing, feedback
            )
            if feedback.isCanceled():
                return {}

            feedback.setProgress(75.0)
            feedback.pushInfo(
                'Rastreando fileiras contínuas e analisando falhas de plantio ao longo '
                'de cada linha...'
            )
            polylines, gap_segments = self._trace_rows_and_gaps(
                resp, density, theta_full, coh_full, grid_res, spacing,
                max_deviation, max_gap, min_points, xmin, ymax, feedback
            )
            if feedback.isCanceled():
                return {}

        if len(polylines) < 1 or (len(polylines) < 2 and not has_planned):
            raise QgsProcessingException(
                'Não foram identificadas fileiras contínuas suficientes. '
                'Confira o espaçamento informado e as camadas de entrada.'
            )

        fields = QgsFields()
        fields.append(QgsField('linha_id', QVariant.Int))
        fields.append(QgsField('angulo_graus', QVariant.Double, len=10, prec=2))
        fields.append(QgsField('compr_m', QVariant.Double, len=14, prec=2))
        fields.append(QgsField('falha_m', QVariant.Double, len=14, prec=2))
        fields.append(QgsField('falha_pct', QVariant.Double, len=10, prec=2))
        fields.append(QgsField('num_falhas', QVariant.Int))
        fields.append(QgsField('pct_pes', QVariant.Double, len=10, prec=2))

        sink, destination = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.LineString, crs,
        )
        if sink is None:
            raise QgsProcessingException('Não foi possível criar a camada de linhas.')

        gap_fields = QgsFields()
        gap_fields.append(QgsField('falha_id', QVariant.Int))
        gap_fields.append(QgsField('linha_id', QVariant.Int))
        gap_fields.append(QgsField('compr_m', QVariant.Double, len=14, prec=2))
        gap_sink, gap_destination = self.parameterAsSink(
            parameters, self.OUTPUT_GAPS, context, gap_fields,
            QgsWkbTypes.LineString, crs,
        )

        line_batch = []
        total_length_m = 0.0
        total_gap_m = 0.0
        for idx, item in enumerate(polylines):
            pts_xy, angle_deg, length_m, gap_m, gap_pct, n_gaps = item[:6]
            pct_pes = float(item[6]) if len(item) > 6 else 100.0
            total_length_m += length_m
            total_gap_m += gap_m
            feat = QgsFeature(fields)
            feat.setGeometry(QgsGeometry.fromPolylineXY(pts_xy))
            feat.setAttributes([
                idx + 1,
                round(float(angle_deg), 2),
                round(float(length_m), 2),
                round(float(gap_m), 2),
                round(float(gap_pct), 2),
                int(n_gaps),
                round(pct_pes, 2),
            ])
            line_batch.append(feat)
            if len(line_batch) >= 2000:
                if not sink.addFeatures(line_batch, QgsFeatureSink.FastInsert):
                    raise QgsProcessingException('Falha ao gravar linhas restituídas.')
                line_batch = []
        if line_batch and not sink.addFeatures(line_batch, QgsFeatureSink.FastInsert):
            raise QgsProcessingException('Falha ao gravar linhas restituídas.')

        gap_count = 0
        if gap_sink is not None and gap_segments:
            gap_batch = []
            for g_idx, (line_id, g_pts, g_len) in enumerate(gap_segments):
                g_feat = QgsFeature(gap_fields)
                g_feat.setGeometry(QgsGeometry.fromPolylineXY(g_pts))
                g_feat.setAttributes([g_idx + 1, int(line_id), round(float(g_len), 2)])
                gap_batch.append(g_feat)
                gap_count += 1
                if len(gap_batch) >= 5000:
                    gap_sink.addFeatures(gap_batch, QgsFeatureSink.FastInsert)
                    gap_batch = []
            if gap_batch:
                gap_sink.addFeatures(gap_batch, QgsFeatureSink.FastInsert)

        overall_gap_pct = (100.0 * total_gap_m / total_length_m) if total_length_m > 0 else 0.0
        feedback.setProgress(100.0)
        feedback.pushInfo(
            f'Restituição concluída: {len(polylines)} linha(s) restituída(s) '
            f'({total_length_m:.1f} m totais). '
            f'Falhas detectadas: {gap_count} trecho(s) somando {total_gap_m:.1f} m '
            f'({overall_gap_pct:.1f}% de falha geral).'
        )
        result = {self.OUTPUT: destination}
        if gap_destination is not None:
            result[self.OUTPUT_GAPS] = gap_destination
        return result

    def _accumulate_points_grid(
            self, layer, extent, xmin, ymax, grid_res, gw, gh, feedback):
        grid = np.zeros((gh, gw), dtype=np.float32)
        total = 0
        request = QgsFeatureRequest()
        request.setNoAttributes()
        request.setFilterRect(extent)

        xs_buf = []
        ys_buf = []
        for feature in layer.getFeatures(request):
            if total % 50000 == 0 and feedback.isCanceled():
                return grid, total
            geom = feature.geometry()
            if geom is None or geom.isNull() or geom.isEmpty():
                continue
            pt = geom.asPoint()
            x, y = pt.x(), pt.y()
            if not (math.isfinite(x) and math.isfinite(y)):
                continue
            total += 1
            xs_buf.append(x)
            ys_buf.append(y)
            if len(xs_buf) >= self.POINT_BATCH:
                self._splat_points(grid, xs_buf, ys_buf, xmin, ymax, grid_res, gw, gh)
                xs_buf = []
                ys_buf = []
        if xs_buf:
            self._splat_points(grid, xs_buf, ys_buf, xmin, ymax, grid_res, gw, gh)

        return grid, total

    def _splat_points(self, grid, xs_list, ys_list, xmin, ymax, grid_res, gw, gh):
        xs = np.asarray(xs_list, dtype=np.float64)
        ys = np.asarray(ys_list, dtype=np.float64)
        cols = np.floor((xs - xmin) / grid_res).astype(np.int32)
        rows = np.floor((ymax - ys) / grid_res).astype(np.int32)
        valid = (cols >= 0) & (cols < gw) & (rows >= 0) & (rows < gh)
        if np.any(valid):
            np.add.at(grid, (rows[valid], cols[valid]), 1.0)

    def _extract_raster_crop_grid(
            self, raster, target_crs, xmin, ymin, xmax, ymax,
            gw, gh, grid_res, context, feedback):
        try:
            src = gdal.Open(raster.source(), gdal.GA_ReadOnly)
            if src is None:
                return None, None, None
            band_count = src.RasterCount
            src = None

            with tempfile.TemporaryDirectory(prefix='restituir_grid_') as temp_dir:
                vrt_path = os.path.join(temp_dir, 'grid.vrt')
                warp_opts = {
                    'format': 'VRT',
                    # exact multiple of grid_res so raster cells match the analysis grid indexing
                    'outputBounds': (xmin, ymax - gh * grid_res, xmin + gw * grid_res, ymax),
                    'width': gw,
                    'height': gh,
                    'resampleAlg': 'average',
                    'dstSRS': target_crs.toWkt(),
                }
                warped = gdal.Warp(
                    vrt_path, raster.source(), options=gdal.WarpOptions(**warp_opts)
                )
                if warped is None:
                    return None, None, None
                warped = None

                ds = gdal.Open(vrt_path, gdal.GA_ReadOnly)
                if ds is None:
                    return None, None, None

                if band_count >= 3:
                    r = ds.GetRasterBand(1).ReadAsArray()
                    g = ds.GetRasterBand(2).ReadAsArray()
                    b = ds.GetRasterBand(3).ReadAsArray()
                    valid = np.isfinite(r) & np.isfinite(g) & np.isfinite(b)
                    for b_i, arr in enumerate((r, g, b), start=1):
                        nd = ds.GetRasterBand(b_i).GetNoDataValue()
                        if nd is not None:
                            valid &= arr != nd
                    if band_count >= 4:
                        a = ds.GetRasterBand(4).ReadAsArray()
                        valid &= a > 0
                    valid &= (r > 0) | (g > 0) | (b > 0)
                    ds = None
                    if not np.any(valid):
                        return None, None, None
                    return self._classify_rgb_grid(r, g, b, valid, grid_res)
                elif band_count == 1:
                    band1 = ds.GetRasterBand(1).ReadAsArray()
                    ds = None
                    if band1 is None:
                        return None, None, None
                    crop_mask = (band1 == 1)
                    valid_mask = (band1 != 255)
                    if np.any(valid_mask) and float(crop_mask[valid_mask].mean()) < 0.55:
                        c_f = crop_mask.astype(np.float32)
                        return c_f, c_f, valid_mask
                    return None, None, valid_mask
            return None, None, None
        except Exception:
            return None, None, None

    def _classify_rgb_grid(self, r, g, b, valid, grid_res):
        r_f = r.astype(np.float32)
        g_f = g.astype(np.float32)
        b_f = b.astype(np.float32)

        denom_gli = 2.0 * g_f + r_f + b_f + 1e-6
        gli = (2.0 * g_f - r_f - b_f) / denom_gli
        ngrdi = (g_f - r_f) / (g_f + r_f + 1e-6)

        win_px = max(5, int(round(0.85 / max(0.05, grid_res))))
        if win_px % 2 == 0:
            win_px += 1

        valid_f = valid.astype(np.float32)
        inv_den = 1.0 / (ndi.uniform_filter(valid_f, size=win_px) + 1e-6)
        gli_bg = ndi.uniform_filter(np.where(valid, gli, 0.0), size=win_px) * inv_den
        ngrdi_bg = ndi.uniform_filter(np.where(valid, ngrdi, 0.0), size=win_px) * inv_den
        d_gli = gli - gli_bg
        d_ngrdi = ngrdi - ngrdi_bg
        local_contrast = 0.55 * d_gli + 0.45 * d_ngrdi

        broad_px = max(15, int(round(4.5 / max(0.05, grid_res))))
        broad_den = 1.0 / (ndi.uniform_filter(valid_f, size=broad_px) + 1e-6)
        local_mad = ndi.uniform_filter(np.abs(local_contrast) * valid_f, size=broad_px) * broad_den
        broad_gli = ndi.uniform_filter(np.where(valid, gli, 0.0), size=broad_px) * broad_den
        broad_ngrdi = ndi.uniform_filter(np.where(valid, ngrdi, 0.0), size=broad_px) * broad_den

        rel_thresh = np.maximum(0.0045, 0.55 * local_mad)
        is_row_veg = (
            valid
            & (local_contrast > rel_thresh)
            & (d_gli > 0.003)
            & (d_ngrdi > 0.002)
            & (gli > 0.005)
            & (ngrdi > -0.085)
            & (g_f > b_f)
        )

        is_forest_core = (broad_gli > 0.085) & (broad_ngrdi > -0.005)
        buffer_px = max(7, int(round(7.0 / max(0.05, grid_res))))
        forest_buffer = ndi.uniform_filter(is_forest_core.astype(np.float32), size=buffer_px) > 0.10
        valid_field = valid & (~forest_buffer)
        crop_grid = (is_row_veg & valid_field).astype(np.float32)
        green_contrast = np.where(valid_field, np.maximum(0.0, local_contrast), 0.0).astype(np.float32)
        return crop_grid, green_contrast, valid_field

    def _fuse_point_and_raster_density(
            self, point_density, raster_density, grid_res, spacing, feedback):
        pt_bin = (point_density > 0).astype(np.float32)
        if raster_density is None or not np.any(raster_density > 0):
            return pt_bin

        # Build spatial envelope where points exist (within ~2.5m radius)
        env_px = max(5, int(round(2.5 / grid_res)))
        pt_envelope = ndi.maximum_filter(pt_bin > 0, size=env_px)

        # Check if point cloud was generated at coarse stride (> 0.45 m) or over-classified straw
        pt_occupied = float(pt_bin[pt_envelope].mean()) if np.any(pt_envelope) else 0.0
        if pt_occupied < 0.035 or pt_occupied > 0.55:
            feedback.pushInfo(
                'Refinando a resolução espacial da nuvem de pontos com o contraste '
                'local das fileiras na imagem RGB...'
            )
            return raster_density * pt_envelope.astype(np.float32)

        return np.clip(0.55 * pt_bin + 0.45 * (raster_density * pt_envelope), 0.0, 1.0)

    def _build_local_orientation_field(
            self, density, grid_res, spacing, feedback, window_m=16.0, step_m=8.0):
        h, w = density.shape
        win_px = max(24, int(round(window_m / grid_res)))
        if win_px % 2 == 1:
            win_px += 1
        step_px = max(6, int(round(step_m / grid_res)))

        hann1d = np.hanning(win_px).astype(np.float32)
        window2d = np.outer(hann1d, hann1d)

        fy = np.fft.fftfreq(win_px, d=grid_res)[:, None]
        fx = np.fft.rfftfreq(win_px, d=grid_res)[None, :]
        freq_rad = np.hypot(fx, fy)
        normal_angle = np.arctan2(fy, fx)
        tangent_angle = (normal_angle + 0.5 * np.pi) % np.pi
        cos_2t = np.cos(2.0 * tangent_angle).astype(np.float32)
        sin_2t = np.sin(2.0 * tangent_angle).astype(np.float32)

        f0 = 1.0 / spacing
        ring_mask = np.exp(-0.5 * ((freq_rad - f0) / (0.22 * f0)) ** 2).astype(np.float32)
        ring_mask[freq_rad < 0.55 * f0] = 0.0
        ring_mask[freq_rad > 1.50 * f0] = 0.0
        ac_mask = (freq_rad >= 0.20 * f0) & (freq_rad <= 2.0 * f0)

        ys = list(range(0, max(1, h - win_px + 1), step_px))
        if ys[-1] != max(0, h - win_px):
            ys.append(max(0, h - win_px))
        xs = list(range(0, max(1, w - win_px + 1), step_px))
        if xs[-1] != max(0, w - win_px):
            xs.append(max(0, w - win_px))

        gh, gw = len(ys), len(xs)
        u_grid = np.zeros((gh, gw), dtype=np.float32)
        v_grid = np.zeros((gh, gw), dtype=np.float32)
        coh_grid = np.zeros((gh, gw), dtype=np.float32)

        for iy, y0_b in enumerate(ys):
            if iy % 10 == 0 and feedback.isCanceled():
                return np.zeros((h, w), dtype=np.float32), np.zeros((h, w), dtype=np.float32)
            row_strip = density[y0_b:y0_b + win_px, :]
            if row_strip.shape[0] < win_px:
                pad = np.zeros((win_px, w), dtype=np.float32)
                pad[:row_strip.shape[0], :] = row_strip
                row_strip = pad
            patches = []
            valid_ixs = []
            for ix, x0_b in enumerate(xs):
                patch = row_strip[:, x0_b:x0_b + win_px]
                if patch.shape[1] < win_px:
                    pad = np.zeros((win_px, win_px), dtype=np.float32)
                    pad[:, :patch.shape[1]] = patch
                    patch = pad
                m = float(patch.mean())
                if 0.012 <= m <= 0.68:
                    patches.append((patch - m) * window2d)
                    valid_ixs.append(ix)
            if not patches:
                continue
            batch = np.asarray(patches, dtype=np.float32)
            specs = np.abs(np.fft.rfft2(batch)) ** 2
            ac_energies = specs[:, ac_mask].sum(axis=1) + 1e-12
            weighted = specs * ring_mask[None, :, :]
            total_rings = weighted.sum(axis=(1, 2)) + 1e-12
            ring_ratios = total_rings / ac_energies
            us = (weighted * cos_2t[None, :, :]).sum(axis=(1, 2))
            vs = (weighted * sin_2t[None, :, :]).sum(axis=(1, 2))
            mags = np.hypot(us, vs)
            cohs = (mags / total_rings) * np.minimum(1.0, ring_ratios * 2.5)
            for k, ix in enumerate(valid_ixs):
                coh = float(cohs[k])
                if coh > 0.12:
                    tr = float(total_rings[k])
                    u_grid[iy, ix] = float(us[k]) / tr * coh
                    v_grid[iy, ix] = float(vs[k]) / tr * coh
                    coh_grid[iy, ix] = coh

        u_smooth = ndi.gaussian_filter(u_grid, sigma=1.0)
        v_smooth = ndi.gaussian_filter(v_grid, sigma=1.0)
        coh_smooth = ndi.gaussian_filter(coh_grid, sigma=0.8)

        zoom_y, zoom_x = h / gh, w / gw
        u_full = ndi.zoom(u_smooth, (zoom_y, zoom_x), order=1)[:h, :w]
        v_full = ndi.zoom(v_smooth, (zoom_y, zoom_x), order=1)[:h, :w]
        coh_full = ndi.zoom(coh_smooth, (zoom_y, zoom_x), order=1)[:h, :w]
        theta_full = (0.5 * np.arctan2(v_full, u_full)) % np.pi
        return theta_full, coh_full

    def _steerable_ridge_filter_tiled(
            self, density, theta_full, coh_full, grid_res, spacing, feedback, n_angles=12):
        h, w = density.shape
        sigma_along = 2.0 / grid_res
        sigma_cross = (0.65 * spacing) / grid_res
        half_len = int(math.ceil(max(2.5 * sigma_along, 1.25 * spacing / grid_res)))
        coords = np.arange(-half_len, half_len + 1, dtype=np.float32)
        yy_k, xx_k = np.meshgrid(coords, coords, indexing='ij')

        angles = np.linspace(0.0, np.pi, n_angles, endpoint=False)
        kernels = []
        for ang in angles:
            ca, sa = math.cos(ang), math.sin(ang)
            t = xx_k * ca + yy_k * sa
            s = -xx_k * sa + yy_k * ca
            along_env = np.exp(-0.5 * (t / sigma_along) ** 2)
            cross_env = np.cos(2.0 * np.pi * (s * grid_res) / spacing) * np.exp(
                -0.5 * (s / sigma_cross) ** 2
            )
            k = along_env * cross_env
            k -= k.mean()
            k /= (np.abs(k).sum() + 1e-6)
            kernels.append(k.astype(np.float32))

        resp = np.zeros((h, w), dtype=np.float32)
        tile_size = 1024
        angle_step = np.pi / n_angles

        n_tiles = (
            int(math.ceil(h / tile_size)) * int(math.ceil(w / tile_size))
        )
        t_idx = 0
        for y0 in range(0, h, tile_size):
            if feedback.isCanceled():
                return resp
            y1 = min(h, y0 + tile_size)
            yp0 = max(0, y0 - half_len)
            yp1 = min(h, y1 + half_len)
            for x0 in range(0, w, tile_size):
                if feedback.isCanceled():
                    return resp
                x1 = min(w, x0 + tile_size)
                t_idx += 1
                coh_sub = coh_full[y0:y1, x0:x1]
                if float(coh_sub.max()) < 0.08:
                    continue
                xp0 = max(0, x0 - half_len)
                xp1 = min(w, x1 + half_len)
                d_pad = density[yp0:yp1, xp0:xp1]
                if float(d_pad.max()) <= 0:
                    continue

                th_sub = theta_full[y0:y1, x0:x1]
                scaled = (th_sub % np.pi) / angle_step
                idx0 = np.floor(scaled).astype(np.int32) % n_angles
                idx1 = (idx0 + 1) % n_angles
                frac = (scaled - np.floor(scaled)).astype(np.float32)

                active = coh_sub >= 0.08
                used_angles = np.unique(np.concatenate([idx0[active], idx1[active]]))
                resp_sub = np.zeros((y1 - y0, x1 - x0), dtype=np.float32)
                sy0, sy1 = y0 - yp0, y0 - yp0 + (y1 - y0)
                sx0, sx1 = x0 - xp0, x0 - xp0 + (x1 - x0)

                for ang_idx in used_angles:
                    conv = fftconvolve(
                        d_pad, kernels[int(ang_idx)], mode='same'
                    )[sy0:sy1, sx0:sx1]
                    m0 = idx0 == ang_idx
                    if np.any(m0):
                        resp_sub[m0] += (1.0 - frac[m0]) * conv[m0]
                    m1 = idx1 == ang_idx
                    if np.any(m1):
                        resp_sub[m1] += frac[m1] * conv[m1]

                resp[y0:y1, x0:x1] = resp_sub
                feedback.setProgress(45.0 + 30.0 * t_idx / max(1, n_tiles))

        return resp

    def _trace_rows_and_gaps(
            self, resp, density, theta_full, coh_full, grid_res, spacing,
            max_deviation, max_gap_m, min_points, xmin, ymax, feedback):
        h, w = resp.shape
        nx = -np.sin(theta_full)
        ny = np.cos(theta_full)
        dnx = np.round(nx).astype(np.int32)
        dny = np.round(ny).astype(np.int32)

        win_cov = max(5, int(round(3.0 / grid_res)))
        has_veg = density > 0.1
        local_cov = ndi.uniform_filter(has_veg.astype(np.float32), size=win_cov)
        crop_dilated = ndi.maximum_filter(has_veg, size=3)

        pos_vals = resp[resp > 0]
        base_pct = min(40, max(15, 15 + min_points * 2))
        ridge_thresh = max(
            0.010,
            float(np.percentile(pos_vals, base_pct)) if pos_vals.size else 0.010,
        )

        cand_mask = (resp > ridge_thresh) & (local_cov > 0.02) & (coh_full > 0.09)
        cand_mask[:2, :] = cand_mask[-2:, :] = cand_mask[:, :2] = cand_mask[:, -2:] = False
        cy_cand, cx_cand = np.nonzero(cand_mask)

        dx_c = dnx[cy_cand, cx_cand]
        dy_c = dny[cy_cand, cx_cand]
        r_c = resp[cy_cand, cx_cand]
        r_p = resp[cy_cand + dy_c, cx_cand + dx_c]
        r_m = resp[cy_cand - dy_c, cx_cand - dx_c]

        keep = (r_c >= r_p) & (r_c >= r_m)
        ry_keep = cy_cand[keep]
        rx_keep = cx_cand[keep]
        rc_keep = r_c[keep]
        rp_keep = r_p[keep]
        rm_keep = r_m[keep]

        is_ridge = np.zeros((h, w), dtype=bool)
        is_ridge[ry_keep, rx_keep] = True

        sub_offset = np.zeros((h, w), dtype=np.float32)
        denom = 2.0 * (rp_keep + rm_keep - 2.0 * rc_keep)
        valid_d = np.abs(denom) > 1e-6
        off_vals = np.zeros_like(rc_keep)
        off_vals[valid_d] = np.clip(
            (rm_keep[valid_d] - rp_keep[valid_d]) / denom[valid_d], -0.5, 0.5
        )
        sub_offset[ry_keep, rx_keep] = off_vals

        visited = np.zeros((h, w), dtype=bool)
        suppress_rad_px = max(1, int(round(0.38 * spacing / grid_res)))

        seed_mask = np.zeros((h, w), dtype=bool)
        seed_mask[::3, ::3] = True
        seed_ys, seed_xs = np.nonzero(is_ridge & seed_mask)
        order = np.argsort(resp[seed_ys, seed_xs])[::-1]

        step_march_m = 0.60
        step_march_px = max(2.0, step_march_m / grid_res)
        actual_step_m = step_march_px * grid_res
        max_gap_steps = max(2, int(round(max_gap_m / actual_step_m)))
        max_lat_step = min(0.38 * spacing, max_deviation * actual_step_m)
        search_lat_px = max(1.5, max_lat_step / grid_res)
        s_offsets = (0.0, -0.8, 0.8, -1.6, 1.6, -search_lat_px, search_lat_px)
        s_weak_offsets = (0.0, -1.0, 1.0)

        polylines = []
        gap_segments = []

        def march_direction(start_x, start_y, start_heading):
            pts = []
            cx, cy = start_x, start_y
            heading = start_heading
            gap_steps = 0
            for _ in range(int(max(h, w) * 2.0 / step_march_px)):
                tx = math.cos(heading)
                ty = math.sin(heading)
                nx_loc = -ty
                ny_loc = tx

                pred_x = cx + tx * step_march_px
                pred_y = cy + ty * step_march_px
                ix, iy = int(pred_x + 0.5), int(pred_y + 0.5)
                if ix < 2 or ix >= w - 2 or iy < 2 or iy >= h - 2:
                    break
                if local_cov[iy, ix] < 0.015 or coh_full[iy, ix] < 0.07:
                    break
                if visited[iy, ix]:
                    break

                best_s = 0.0
                best_val = -1e9
                found_ridge = False
                hit_visited = False
                for s_off in s_offsets:
                    sx = int(pred_x + nx_loc * s_off + 0.5)
                    sy = int(pred_y + ny_loc * s_off + 0.5)
                    if 0 <= sx < w and 0 <= sy < h:
                        if abs(s_off) < 1.0 and visited[sy, sx]:
                            hit_visited = True
                            break
                        if is_ridge[sy, sx] and not visited[sy, sx]:
                            val = float(resp[sy, sx]) - 0.015 * abs(s_off)
                            if val > best_val:
                                best_val = val
                                th_pix = float(theta_full[sy, sx])
                                n_dot = (-math.sin(th_pix)) * nx_loc + math.cos(th_pix) * ny_loc
                                best_s = s_off + float(sub_offset[sy, sx]) * (
                                    1.0 if n_dot >= 0 else -1.0
                                )
                                found_ridge = True

                if hit_visited:
                    break

                if found_ridge:
                    cx = pred_x + nx_loc * best_s
                    cy = pred_y + ny_loc * best_s
                    gap_steps = 0
                else:
                    gap_steps += 1
                    if gap_steps > max_gap_steps:
                        break
                    best_weak_s = 0.0
                    best_weak_v = 0.0
                    for s_off in s_weak_offsets:
                        sx = int(pred_x + nx_loc * s_off + 0.5)
                        sy = int(pred_y + ny_loc * s_off + 0.5)
                        if 0 <= sx < w and 0 <= sy < h and resp[sy, sx] > best_weak_v:
                            best_weak_v = float(resp[sy, sx])
                            best_weak_s = s_off
                    cx = pred_x + nx_loc * (0.5 * best_weak_s)
                    cy = pred_y + ny_loc * (0.5 * best_weak_s)

                cy_i = min(h - 1, max(0, int(cy + 0.5)))
                cx_i = min(w - 1, max(0, int(cx + 0.5)))
                loc_theta = float(theta_full[cy_i, cx_i])
                diff = (loc_theta - heading + 0.5 * math.pi) % math.pi - 0.5 * math.pi
                if abs(diff) > 0.70:
                    break
                heading = heading + 0.40 * diff
                pts.append((cx, cy))
            return pts

        total_seeds = max(1, len(order))
        for s_i, idx in enumerate(order):
            if s_i % 2000 == 0:
                if feedback.isCanceled():
                    return polylines, gap_segments
                feedback.setProgress(75.0 + 20.0 * s_i / total_seeds)

            y0, x0 = int(seed_ys[idx]), int(seed_xs[idx])
            if visited[y0, x0]:
                continue
            th0 = float(theta_full[y0, x0])
            sx0 = x0 - math.sin(th0) * float(sub_offset[y0, x0])
            sy0 = y0 + math.cos(th0) * float(sub_offset[y0, x0])

            fwd = march_direction(sx0, sy0, th0)
            bwd = march_direction(sx0, sy0, th0 + math.pi)
            line = bwd[::-1] + [(sx0, sy0)] + fwd

            if len(line) * actual_step_m < 3.0:
                continue

            pts_arr = np.asarray(line, dtype=np.float64)
            ixs = np.clip((pts_arr[:, 0] + 0.5).astype(np.int32), 0, w - 1)
            iys = np.clip((pts_arr[:, 1] + 0.5).astype(np.int32), 0, h - 1)
            valid_indices = np.flatnonzero(crop_dilated[iys, ixs])
            if valid_indices.size < 2:
                continue
            pts_arr = pts_arr[valid_indices[0]:valid_indices[-1] + 1]
            if len(pts_arr) < 3 or len(pts_arr) * actual_step_m < 2.5:
                continue

            # Mark visited along raw traced path before straightening/smoothing
            diffs = np.diff(pts_arr, axis=0)
            seg_max = max(1, int(math.ceil(step_march_px)))
            dense_x = []
            dense_y = []
            for s_frac in np.linspace(0.0, 1.0, seg_max, endpoint=False):
                dense_x.append(pts_arr[:-1, 0] + diffs[:, 0] * s_frac)
                dense_y.append(pts_arr[:-1, 1] + diffs[:, 1] * s_frac)
            dense_x.append(pts_arr[-1:, 0])
            dense_y.append(pts_arr[-1:, 1])
            ixs_d = np.clip((np.concatenate(dense_x) + 0.5).astype(np.int32), 0, w - 1)
            iys_d = np.clip((np.concatenate(dense_y) + 0.5).astype(np.int32), 0, h - 1)

            for dy in range(-suppress_rad_px, suppress_rad_px + 1):
                for dx in range(-suppress_rad_px, suppress_rad_px + 1):
                    visited[
                        np.clip(iys_d + dy, 0, h - 1),
                        np.clip(ixs_d + dx, 0, w - 1),
                    ] = True

            # Eliminate zig-zag: if the row is a straight "tiro reto" (max lateral deviation < 0.45 m),
            # project onto its exact least-squares straight line; otherwise apply smooth Gaussian filtering.
            pts_arr = self._smooth_or_straighten_grid_line(pts_arr, grid_res)

            # Convert to map coordinates (x_map, y_map)
            xs_map = xmin + (pts_arr[:, 0] + 0.5) * grid_res
            ys_map = ymax - (pts_arr[:, 1] + 0.5) * grid_res
            seg_dx = np.diff(xs_map)
            seg_dy = np.diff(ys_map)
            seg_lens = np.hypot(seg_dx, seg_dy)
            length_m = float(seg_lens.sum())
            if length_m < 2.5:
                continue

            # Mean orientation angle in map coordinates [0, 180)
            dx_total = xs_map[-1] - xs_map[0]
            dy_total = ys_map[-1] - ys_map[0]
            angle_deg = math.degrees(math.atan2(dy_total, dx_total)) % 180.0

            # Measure internal planting gaps (>= 0.50 m without crop along the traced row)
            ixs_v = np.clip((pts_arr[:, 0] + 0.5).astype(np.int32), 0, w - 1)
            iys_v = np.clip((pts_arr[:, 1] + 0.5).astype(np.int32), 0, h - 1)
            vertex_has_crop = crop_dilated[iys_v, ixs_v]

            line_id = len(polylines) + 1
            gap_m_total, n_gaps, line_gaps = self._measure_line_gaps(
                xs_map, ys_map, seg_lens, vertex_has_crop, line_id
            )
            gap_segments.extend(line_gaps)

            gap_pct = min(100.0, 100.0 * gap_m_total / max(0.01, length_m))
            pts_xy = [
                QgsPointXY(float(x_m), float(y_m))
                for x_m, y_m in zip(xs_map, ys_map)
            ]
            polylines.append((pts_xy, angle_deg, length_m, gap_m_total, gap_pct, n_gaps))

        return polylines, gap_segments

    def _smooth_or_straighten_grid_line(self, pts_arr, grid_res):
        n_pts = len(pts_arr)
        if n_pts < 3:
            return pts_arr
        chord_dx = float(pts_arr[-1, 0] - pts_arr[0, 0])
        chord_dy = float(pts_arr[-1, 1] - pts_arr[0, 1])
        chord_px = math.hypot(chord_dx, chord_dy)
        if chord_px > 1e-3:
            ux, uy = chord_dx / chord_px, chord_dy / chord_px
            lat_dev_m = np.abs(
                -(pts_arr[:, 0] - pts_arr[0, 0]) * uy
                + (pts_arr[:, 1] - pts_arr[0, 1]) * ux
            ) * grid_res
            if float(lat_dev_m.max()) < 0.45:
                # Exact straight line fit ("tiro reto"): zero zig-zag!
                mean_pt = pts_arr.mean(axis=0)
                centered = pts_arr - mean_pt
                cov = np.dot(centered.T, centered)
                eigvals, eigvecs = np.linalg.eigh(cov)
                dir_vec = eigvecs[:, int(np.argmax(eigvals))]
                if dir_vec[0] * chord_dx + dir_vec[1] * chord_dy < 0:
                    dir_vec = -dir_vec
                proj = np.dot(centered, dir_vec)
                return mean_pt[None, :] + proj[:, None] * dir_vec[None, :]

        if n_pts >= 5:
            sigma = min(6.0, max(2.0, n_pts / 6.0))
            xs_s = ndi.gaussian_filter1d(pts_arr[:, 0], sigma=sigma, mode='nearest')
            ys_s = ndi.gaussian_filter1d(pts_arr[:, 1], sigma=sigma, mode='nearest')
            idx = np.arange(n_pts, dtype=np.float64)
            taper = np.minimum(1.0, np.minimum(idx, (n_pts - 1) - idx) / 3.0)
            pts_out = np.empty_like(pts_arr)
            pts_out[:, 0] = pts_arr[:, 0] * (1.0 - taper) + xs_s * taper
            pts_out[:, 1] = pts_arr[:, 1] * (1.0 - taper) + ys_s * taper
            return pts_out
        return pts_arr

    def _measure_line_gaps(self, xs_map, ys_map, seg_lens, vertex_has_crop, line_id):
        gap_m_total = 0.0
        n_gaps = 0
        in_gap = False
        gap_start_idx = 0
        line_gaps = []
        n_verts = len(xs_map)

        for v_i in range(n_verts):
            if not vertex_has_crop[v_i]:
                if not in_gap:
                    in_gap = True
                    gap_start_idx = max(0, v_i - 1)
            else:
                if in_gap:
                    in_gap = False
                    gap_end_idx = v_i
                    g_len = float(seg_lens[gap_start_idx:gap_end_idx].sum())
                    if g_len >= 0.50:
                        gap_m_total += g_len
                        n_gaps += 1
                        g_pts = [
                            QgsPointXY(float(xs_map[k]), float(ys_map[k]))
                            for k in range(gap_start_idx, gap_end_idx + 1)
                        ]
                        line_gaps.append((line_id, g_pts, g_len))

        if in_gap:
            gap_end_idx = n_verts - 1
            if gap_end_idx > gap_start_idx:
                g_len = float(seg_lens[gap_start_idx:gap_end_idx].sum())
                if g_len >= 0.50:
                    gap_m_total += g_len
                    n_gaps += 1
                    g_pts = [
                        QgsPointXY(float(xs_map[k]), float(ys_map[k]))
                        for k in range(gap_start_idx, gap_end_idx + 1)
                    ]
                    line_gaps.append((line_id, g_pts, g_len))

        return gap_m_total, n_gaps, line_gaps

    def _reconstruct_from_planned_lines(
            self, planned_layer, planned_transform, image_extent,
            density, raster_density, green_contrast, valid_field_mask,
            grid_res, spacing, xmin, ymax, gw, gh, feedback,
            max_offset=0.70, min_run=1.5, decay_len=2.0):
        raw_parts = self._extract_planned_polylines(
            planned_layer, planned_transform, image_extent, feedback
        )
        if not raw_parts:
            raise QgsProcessingException(
                'Nenhuma linha projetada válida foi encontrada dentro da extensão da imagem.'
            )

        # Build continuous crop-center signal combining point cloud, RGB row mask, and local green contrast
        base_veg = density.copy()
        if raster_density is not None:
            base_veg = np.maximum(base_veg, 0.75 * raster_density)
        if green_contrast is not None:
            base_veg = 0.65 * base_veg + 0.35 * np.clip(green_contrast * 18.0, 0.0, 1.0)

        crop_smooth = ndi.gaussian_filter(base_veg, sigma=max(1.0, 0.22 / grid_res))
        bg_win = max(5, int(round(0.95 / grid_res)))
        row_signal = crop_smooth - ndi.uniform_filter(crop_smooth, size=bg_win)

        if valid_field_mask is not None:
            valid_eroded = ndi.minimum_filter(valid_field_mask, size=max(3, int(round(0.45 / grid_res))))
        else:
            valid_eroded = np.ones((gh, gw), dtype=bool)

        # Crop presence mask for gap measurement along the reconstructed line (radius ~ 0.28 m)
        has_crop_bin = (density > 0.10) | ((raster_density > 0.10) if raster_density is not None else False)
        dil_px = max(2, int(round(0.28 / grid_res)))
        crop_dilated = ndi.maximum_filter(has_crop_bin, size=2 * dil_px + 1)

        step_s = 0.25
        delta_step = 0.04
        max_shift = max(0.2, float(max_offset))
        deltas = np.arange(-max_shift, max_shift + 0.001, delta_step, dtype=np.float64)
        n_deltas = len(deltas)
        tie_prior = 1.0 - 0.08 * (deltas / max(max_shift, 1e-6)) ** 2

        polylines = []
        gap_segments = []
        total_parts = len(raw_parts)

        for p_idx, part in enumerate(raw_parts):
            if p_idx % 20 == 0:
                if feedback.isCanceled():
                    return polylines, gap_segments
                feedback.setProgress(35.0 + 60.0 * p_idx / max(1, total_parts))

            s_grid, p_xy, n_xy, is_straight_full = self._resample_and_smooth_planned_line(
                part, step_m=step_s
            )
            if s_grid is None:
                continue

            cols0 = np.floor((p_xy[:, 0] - xmin) / grid_res).astype(np.int32)
            rows0 = np.floor((ymax - p_xy[:, 1]) / grid_res).astype(np.int32)
            in_bounds = (cols0 >= 0) & (cols0 < gw) & (rows0 >= 0) & (rows0 < gh)
            in_valid = np.zeros(len(s_grid), dtype=bool)
            in_valid[in_bounds] = valid_eroded[rows0[in_bounds], cols0[in_bounds]]

            valid_idx = np.flatnonzero(in_valid)
            if valid_idx.size < 4:
                continue
            breaks = np.flatnonzero(np.diff(valid_idx) > 4)
            groups = np.split(valid_idx, breaks + 1)

            for grp in groups:
                if grp.size < 4:
                    continue
                i0, i1 = int(grp[0]), int(grp[-1])
                sub_s = s_grid[i0:i1 + 1]
                sub_p = p_xy[i0:i1 + 1]
                sub_n = n_xy[i0:i1 + 1]
                m_len = len(sub_s)
                if float(sub_s[-1] - sub_s[0]) < 2.5:
                    continue

                chord_dx = float(sub_p[-1, 0] - sub_p[0, 0])
                chord_dy = float(sub_p[-1, 1] - sub_p[0, 1])
                chord_l = math.hypot(chord_dx, chord_dy)
                is_straight = is_straight_full
                if not is_straight and chord_l > 1e-3:
                    ux, uy = chord_dx / chord_l, chord_dy / chord_l
                    lat_dev = np.abs(
                        -(sub_p[:, 0] - sub_p[0, 0]) * uy
                        + (sub_p[:, 1] - sub_p[0, 1]) * ux
                    )
                    if float(lat_dev.max()) < 0.30:
                        is_straight = True

                sample_x = sub_p[:, 0:1] + sub_n[:, 0:1] * deltas[None, :]
                sample_y = sub_p[:, 1:2] + sub_n[:, 1:2] * deltas[None, :]
                s_cols = np.clip(
                    np.floor((sample_x - xmin) / grid_res).astype(np.int32), 0, gw - 1
                )
                s_rows = np.clip(
                    np.floor((ymax - sample_y) / grid_res).astype(np.int32), 0, gh - 1
                )

                # bilinear sampling of the analysis grid. NOTE: grid coordinates are used
                # WITHOUT the usual -0.5 cell-centre shift: this was calibrated against the
                # raster (ExG) row centres and removes a systematic half-cell (grid_res/2) offset.
                col_f = (sample_x - xmin) / grid_res
                row_f = (ymax - sample_y) / grid_res
                smooth_delta, from_plant = self._offsets_from_plant_centers(
                    row_signal, crop_dilated, s_rows, s_cols, row_f, col_f, deltas, delta_step,
                    tie_prior, sub_s, spacing, is_straight, min_run, decay_len
                )


                rec_xy = sub_p + sub_n * smooth_delta[:, None]
                xs_map = rec_xy[:, 0]
                ys_map = rec_xy[:, 1]
                seg_dx = np.diff(xs_map)
                seg_dy = np.diff(ys_map)
                seg_lens = np.hypot(seg_dx, seg_dy)
                length_m = float(seg_lens.sum())
                if length_m < 2.5:
                    continue

                dx_total = float(xs_map[-1] - xs_map[0])
                dy_total = float(ys_map[-1] - ys_map[0])
                angle_deg = math.degrees(math.atan2(dy_total, dx_total)) % 180.0

                ixs_v = np.clip(
                    np.floor((xs_map - xmin) / grid_res).astype(np.int32), 0, gw - 1
                )
                iys_v = np.clip(
                    np.floor((ymax - ys_map) / grid_res).astype(np.int32), 0, gh - 1
                )
                vertex_has_crop = crop_dilated[iys_v, ixs_v]

                line_id = len(polylines) + 1
                gap_m_total, n_gaps, line_gaps = self._measure_line_gaps(
                    xs_map, ys_map, seg_lens, vertex_has_crop, line_id
                )
                gap_segments.extend(line_gaps)

                gap_pct = min(100.0, 100.0 * gap_m_total / max(0.01, length_m))
                pts_xy = [
                    QgsPointXY(float(x_m), float(y_m))
                    for x_m, y_m in zip(xs_map, ys_map)
                ]
                fp_seg = from_plant[:-1] & from_plant[1:]
                pct_pe = 100.0 * float(seg_lens[fp_seg].sum()) / max(0.01, length_m)
                polylines.append(
                    (pts_xy, angle_deg, length_m, gap_m_total, gap_pct, n_gaps, pct_pe)
                )

        return polylines, gap_segments

    def _offsets_from_plant_centers(
            self, row_signal, crop_dilated, s_rows, s_cols, row_f, col_f, deltas, delta_step,
            tie_prior, sub_s, spacing, is_straight, min_run, decay_len):
        """Lateral offset (relative to the planned line) for every sample.

        WITH cane: the offset follows the centre of the planted tufts (per-plant
        peak of the local row signal, outliers rejected, no long smoothing).
        WITHOUT cane: the offset decays to zero, i.e. the planned line is used.
        Returns (offset array, bool mask 'rebuilt from plant centres').
        """
        m_len, n_deltas = s_rows.shape
        step_s = float(np.median(np.diff(sub_s))) if m_len > 1 else 0.25
        zero = np.zeros(m_len, dtype=np.float64)
        no_plant = np.zeros(m_len, dtype=bool)

        pos_prof = np.maximum(0.0, ndi.map_coordinates(
            row_signal, [row_f, col_f], order=1, mode='nearest'
        ))
        fine_prof = ndi.gaussian_filter(pos_prof, sigma=(1.0, 1.5), mode='nearest')
        regional = ndi.gaussian_filter(pos_prof, sigma=(48.0, 1.5), mode='nearest')
        anchor_delta = deltas[np.argmax(regional * tie_prior[None, :], axis=1)]

        corridor = np.abs(deltas[None, :] - anchor_delta[:, None]) <= 0.32 * spacing
        masked = np.where(corridor, fine_prof * tie_prior[None, :], -1.0)
        j = np.argmax(masked, axis=1)
        ar = np.arange(m_len)
        v0 = fine_prof[ar, j]
        jm = np.clip(j - 1, 0, n_deltas - 1)
        jp = np.clip(j + 1, 0, n_deltas - 1)
        vm = fine_prof[ar, jm]
        vp = fine_prof[ar, jp]
        denom = 2.0 * (vm + vp - 2.0 * v0)
        interior = (j > 0) & (j < n_deltas - 1) & (np.abs(denom) > 1e-6)
        sub_j = np.where(
            interior, np.clip((vm - vp) / np.where(interior, denom, 1.0), -0.5, 0.5), 0.0
        )
        raw_delta = deltas[j] + sub_j * delta_step

        p95 = float(np.percentile(pos_prof, 95)) if pos_prof.size else 0.0
        thr = max(0.015, 0.30 * p95)
        present = (v0 > thr) & crop_dilated[s_rows[ar, j], s_cols[ar, j]]
        pres_idx = np.flatnonzero(present)
        if pres_idx.size < 5:
            return zero, no_plant

        # reject tufts that belong to a neighbouring row / noise (robust running median)
        ps = sub_s[pres_idx]
        pd = raw_delta[pres_idx]
        lo = np.searchsorted(ps, ps - 3.0)
        hi = np.searchsorted(ps, ps + 3.0, side='right')
        med = np.array([np.median(pd[lo[i]:hi[i]]) for i in range(len(pd))])
        inlier = np.abs(pd - med) <= max(0.10, 0.10 * spacing)
        pres_idx = pres_idx[inlier]
        if pres_idx.size < 5:
            return zero, no_plant
        ps = sub_s[pres_idx]
        pd = raw_delta[pres_idx]

        # continuous runs of cane (links shorter than 1 m are the same stand)
        cuts = np.flatnonzero(np.diff(ps) > 1.0)
        runs = []
        for seg in np.split(np.arange(len(ps)), cuts + 1):
            if len(seg) < 5 or float(ps[seg[-1]] - ps[seg[0]]) < min_run:
                continue
            rs, rd = ps[seg], pd[seg]
            ia = int(np.searchsorted(sub_s, rs[0] - 1e-9))
            ib = int(np.searchsorted(sub_s, rs[-1] + 1e-9, side='right')) - 1
            if ib <= ia:
                continue
            grid_s = sub_s[ia:ib + 1]
            vals = None
            if is_straight and (rs[-1] - rs[0]) >= 3.0:
                w = np.ones(len(rs))
                coef = np.polyfit(rs - rs[0], rd, 1)
                for _ in range(4):
                    res = rd - np.polyval(coef, rs - rs[0])
                    w = 1.0 / (1.0 + (res / 0.04) ** 2)
                    coef = np.polyfit(rs - rs[0], rd, 1, w=w)
                res = rd - np.polyval(coef, rs - rs[0])
                if float(np.median(np.abs(res))) <= 0.07:
                    slope = max(-0.03, min(0.03, float(coef[0])))
                    icpt = float(np.average(rd - slope * (rs - rs[0]), weights=w))
                    vals = icpt + slope * (grid_s - rs[0])
            if vals is None:
                acc = np.zeros(len(grid_s))
                wgt = np.zeros(len(grid_s))
                pos = np.clip(np.searchsorted(grid_s, rs), 0, len(grid_s) - 1)
                np.add.at(acc, pos, rd)
                np.add.at(wgt, pos, 1.0)
                sg = max(1.0, 1.5 / step_s)
                num = ndi.gaussian_filter1d(acc, sg, mode='nearest')
                den = ndi.gaussian_filter1d(wgt, sg, mode='nearest')
                good = den > 1e-3
                vals = np.interp(grid_s, grid_s[good], num[good] / den[good])
            runs.append((ia, ib, np.asarray(vals, dtype=np.float64)))

        if not runs:
            return zero, no_plant

        offset = zero.copy()
        from_plant = no_plant.copy()
        for ia, ib, vals in runs:
            offset[ia:ib + 1] = vals
            from_plant[ia:ib + 1] = True
        # no cane: offset fades out to the planned line (no step at the seam)
        fade = np.zeros(m_len, dtype=np.float64)
        for ia, ib, vals in runs:
            after = sub_s - sub_s[ib]
            before = sub_s[ia] - sub_s
            fade += vals[-1] * np.clip(1.0 - after / decay_len, 0.0, 1.0) * (after > 0)
            fade += vals[0] * np.clip(1.0 - before / decay_len, 0.0, 1.0) * (before > 0)
        offset = np.where(from_plant, offset, fade)
        return offset, from_plant


    def _extract_planned_polylines(
            self, planned_layer, planned_transform, image_extent, feedback):
        parts = []
        request = QgsFeatureRequest()
        request.setNoAttributes()
        if planned_transform is None:
            request.setFilterRect(image_extent)

        for feat in planned_layer.getFeatures(request):
            if feedback.isCanceled():
                return parts
            geom = feat.geometry()
            if geom is None or geom.isNull() or geom.isEmpty():
                continue
            if planned_transform is not None:
                geom = QgsGeometry(geom)
                try:
                    geom.transform(planned_transform)
                except Exception:
                    continue
                if not geom.boundingBox().intersects(image_extent):
                    continue
            if geom.isMultipart():
                lines = geom.asMultiPolyline()
            else:
                lines = [geom.asPolyline()]
            for line in lines:
                if len(line) >= 2:
                    coords = [(float(pt.x()), float(pt.y())) for pt in line]
                    parts.append(coords)
        return parts

    def _resample_and_smooth_planned_line(self, coords, step_m=0.50):
        pts = np.asarray(coords, dtype=np.float64)
        if len(pts) < 2:
            return None, None, None, False
        diffs = np.diff(pts, axis=0)
        seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
        keep = seg_lens > 1e-4
        if not np.any(keep):
            return None, None, None, False
        pts = np.vstack([pts[0], pts[1:][keep]])
        diffs = np.diff(pts, axis=0)
        seg_lens = np.hypot(diffs[:, 0], diffs[:, 1])
        cum_s = np.concatenate([[0.0], np.cumsum(seg_lens)])
        total_len = float(cum_s[-1])
        if total_len < 2.0:
            return None, None, None, False
        n_samples = max(2, int(round(total_len / step_m)) + 1)
        s_grid = np.linspace(0.0, total_len, n_samples)
        xs = np.interp(s_grid, cum_s, pts[:, 0])
        ys = np.interp(s_grid, cum_s, pts[:, 1])

        chord_dx = float(xs[-1] - xs[0])
        chord_dy = float(ys[-1] - ys[0])
        chord_len = math.hypot(chord_dx, chord_dy)
        is_straight = False
        if chord_len > 1e-3:
            ux, uy = chord_dx / chord_len, chord_dy / chord_len
            lat_dev = np.abs(-(xs - xs[0]) * uy + (ys - ys[0]) * ux)
            if float(lat_dev.max()) < 0.35:
                is_straight = True
                xs = xs[0] + s_grid * (chord_dx / total_len)
                ys = ys[0] + s_grid * (chord_dy / total_len)

        if not is_straight and len(xs) >= 7:
            xs_s = ndi.gaussian_filter1d(xs, sigma=2.5 / step_m, mode='nearest')
            ys_s = ndi.gaussian_filter1d(ys, sigma=2.5 / step_m, mode='nearest')
            taper = np.minimum(1.0, np.minimum(s_grid, total_len - s_grid) / 4.0)
            xs = xs * (1.0 - taper) + xs_s * taper
            ys = ys * (1.0 - taper) + ys_s * taper

        dx = np.gradient(xs, s_grid)
        dy = np.gradient(ys, s_grid)
        norm = np.hypot(dx, dy) + 1e-12
        tx = dx / norm
        ty = dy / norm
        mean_tx = float(np.mean(tx))
        mean_ty = float(np.mean(ty))
        orient_sign = (
            1.0
            if (mean_ty > 1e-3 or (abs(mean_ty) <= 1e-3 and mean_tx >= 0.0))
            else -1.0
        )
        nx = -ty * orient_sign
        ny = tx * orient_sign
        return s_grid, np.column_stack([xs, ys]), np.column_stack([nx, ny]), is_straight

    def name(self):
        return 'restituir_linhas_plantio'

    def displayName(self):
        return 'Restituir linhas de plantio a partir dos pontos'

    def group(self):
        return 'Análise de falhas'

    def groupId(self):
        return 'analise_falhas'

    def createInstance(self):
        return RestituirLinhasAlgorithm()

    def shortHelpString(self):
        return (
            'Restitui as linhas de plantio de cana-de-açúcar (retas em tiro reto, em '
            'curva de nível, com terraço embutido ou em múltiplos talhões) e calcula '
            'as falhas de plantio ao longo de cada fileira.\n\n'
            'Como funciona:\n'
            '1. Combina a nuvem de pontos da cultura com o contraste local da '
            'imagem de referência em uma grade métrica de alta resolução.\n'
            '2. Quando a camada opcional de "Linhas projetadas" é informada:\n'
            '   - Restitui as fileiras até mesmo em áreas 100% sem cana (falhas totais), '
            'usando o projeto de plantio recortado à área útil do talhão;\n'
            '   - Centraliza automaticamente linhas de cana deslocadas para o eixo exato '
            'da cultura por regressão longitudinal Nadaraya-Watson sem entortar a linha;\n'
            '   - Garante alinhamento matemático perfeito (zero zig-zag) em tiros retos '
            'e curvatura suave em curvas de nível.\n'
            '3. Quando "Linhas projetadas" não é informada:\n'
            '   - Estima o campo 2D de orientação local via FFT em janelas e aplica '
            'filtragem direcional adaptativa (comb filter) com retificação automática '
            'de tiros retos e suavização Gaussiana em curvas.\n'
            '4. Mede automaticamente todos os trechos de falha (>= 0,5 m sem cultura) '
            'ao longo de cada linha restituída, gravando os atributos compr_m, '
            'falha_m, falha_pct e num_falhas, além da camada vetorial de falhas.'
        )
