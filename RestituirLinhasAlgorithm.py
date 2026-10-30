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
    ROW_SPACING = 'ROW_SPACING'
    MAX_DEVIATION = 'MAX_DEVIATION'
    MAX_GAP = 'MAX_GAP'
    MIN_POINTS_PER_BIN = 'MIN_POINTS_PER_BIN'
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
        if not image_extent.intersects(points.extent()):
            raise QgsProcessingException(
                'A nuvem de pontos não está dentro da área da imagem selecionada.'
            )

        spacing = self.parameterAsDouble(parameters, self.ROW_SPACING, context)
        max_deviation = self.parameterAsDouble(parameters, self.MAX_DEVIATION, context)
        max_gap = self.parameterAsDouble(parameters, self.MAX_GAP, context)
        min_points = self.parameterAsInt(parameters, self.MIN_POINTS_PER_BIN, context)

        work_extent = image_extent.intersect(points.extent())
        pad_m = max(2.0, spacing * 2.0)
        xmin = work_extent.xMinimum() - pad_m
        ymin = work_extent.yMinimum() - pad_m
        xmax = work_extent.xMaximum() + pad_m
        ymax = work_extent.yMaximum() + pad_m

        grid_res = min(0.20, max(0.10, spacing / 8.0))
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
        if point_count < 10:
            raise QgsProcessingException(
                'Há menos de dez pontos da nuvem dentro da imagem selecionada.'
            )

        raster_density = self._extract_raster_crop_grid(
            raster, crs, xmin, ymin, xmax, ymax, gw, gh, grid_res, context, feedback
        )
        if feedback.isCanceled():
            return {}

        density = self._fuse_point_and_raster_density(
            point_density, raster_density, grid_res, spacing, feedback
        )
        del point_density, raster_density
        if feedback.isCanceled():
            return {}

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

        if len(polylines) < 2:
            raise QgsProcessingException(
                'Não foram identificadas pelo menos duas fileiras contínuas. '
                'Confira o espaçamento informado e a classificação da nuvem.'
            )

        fields = QgsFields()
        fields.append(QgsField('linha_id', QVariant.Int))
        fields.append(QgsField('angulo_graus', QVariant.Double, len=10, prec=2))
        fields.append(QgsField('compr_m', QVariant.Double, len=14, prec=2))
        fields.append(QgsField('falha_m', QVariant.Double, len=14, prec=2))
        fields.append(QgsField('falha_pct', QVariant.Double, len=10, prec=2))
        fields.append(QgsField('num_falhas', QVariant.Int))

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
            pts_xy, angle_deg, length_m, gap_m, gap_pct, n_gaps = item
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
                return None
            band_count = src.RasterCount
            src = None

            with tempfile.TemporaryDirectory(prefix='restituir_grid_') as temp_dir:
                vrt_path = os.path.join(temp_dir, 'grid.vrt')
                warp_opts = {
                    'format': 'VRT',
                    'outputBounds': (xmin, ymin, xmax, ymax),
                    'width': gw,
                    'height': gh,
                    'resampleAlg': 'average',
                    'dstSRS': target_crs.toWkt(),
                }
                warped = gdal.Warp(
                    vrt_path, raster.source(), options=gdal.WarpOptions(**warp_opts)
                )
                if warped is None:
                    return None
                warped = None

                ds = gdal.Open(vrt_path, gdal.GA_ReadOnly)
                if ds is None:
                    return None

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
                        return None
                    return self._classify_rgb_grid(r, g, b, valid, grid_res)
                elif band_count == 1:
                    band1 = ds.GetRasterBand(1).ReadAsArray()
                    ds = None
                    if band1 is None:
                        return None
                    crop_mask = (band1 == 1)
                    valid_mask = (band1 != 255)
                    if np.any(valid_mask) and float(crop_mask[valid_mask].mean()) < 0.55:
                        return crop_mask.astype(np.float32)
            return None
        except Exception:
            return None

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
        return (is_row_veg & (~forest_buffer)).astype(np.float32)

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

            # Smooth grid coordinates gently (3-point moving average) to remove discretization jitter
            if len(pts_arr) >= 5:
                pts_arr[1:-1, 0] = (
                    0.25 * pts_arr[:-2, 0] + 0.50 * pts_arr[1:-1, 0] + 0.25 * pts_arr[2:, 0]
                )
                pts_arr[1:-1, 1] = (
                    0.25 * pts_arr[:-2, 1] + 0.50 * pts_arr[1:-1, 1] + 0.25 * pts_arr[2:, 1]
                )

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
            gap_m_total = 0.0
            n_gaps = 0
            in_gap = False
            gap_start_idx = 0

            for v_i in range(len(pts_arr)):
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
                            gap_segments.append((line_id, g_pts, g_len))

            gap_pct = min(100.0, 100.0 * gap_m_total / max(0.01, length_m))
            pts_xy = [
                QgsPointXY(float(x_m), float(y_m))
                for x_m, y_m in zip(xs_map, ys_map)
            ]
            polylines.append((pts_xy, angle_deg, length_m, gap_m_total, gap_pct, n_gaps))

        return polylines, gap_segments

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
            'Restitui as linhas de plantio de cana-de-açúcar (retas, em curva de '
            'nível, com terraço embutido ou em múltiplos talhões) e calcula as '
            'falhas de plantio ao longo de cada fileira.\n\n'
            'Como funciona:\n'
            '1. Combina a nuvem de pontos da cultura com o contraste local da '
            'imagem de referência em uma grade métrica de alta resolução.\n'
            '2. Estima um campo 2D de orientação local via Transformada de Fourier '
            'em janelas na frequência fundamental do espaçamento entre linhas, '
            'acompanhando automaticamente curvas de nível e mudanças de direção '
            'entre talhões e ignorando carreadores e áreas de mata.\n'
            '3. Aplica um banco de filtros direcionais (comb filter) guiado pelo '
            'campo de orientação local para interpolar lacunas e extrair o eixo '
            'central sub-pixel de cada fileira.\n'
            '4. Mede automaticamente os trechos de falha (>= 0,5 m sem cultura) '
            'dentro de cada linha restituída, gravando os atributos compr_m, '
            'falha_m, falha_pct e num_falhas, além de uma camada vetorial '
            'opcional contendo os segmentos exatos onde ocorreram as falhas.'
        )
