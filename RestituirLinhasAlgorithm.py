"""Reconstruct individual sugarcane row lines from classified crop points."""

import math
import random

import numpy as np
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsFeature,
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
    QgsFeatureRequest,
    QgsCoordinateTransform,
    QgsFeatureSink,
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
    SAMPLE_LIMIT = 50000
    POINT_BATCH = 50000

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
        feedback.pushInfo(
            'Selecionando somente os pontos dentro da imagem e amostrando a orientação...'
        )
        sample, bounds, point_count = self._sample_points(
            points, image_extent, feedback
        )
        if feedback.isCanceled():
            return {}
        if point_count < 10:
            raise QgsProcessingException(
                'Há menos de dez pontos da nuvem dentro da imagem selecionada.'
            )
        feedback.pushInfo(
            f'Pontos dentro da imagem: {point_count}; usados na amostra angular: '
            f'{len(sample)}.'
        )
        sample_array = np.asarray(sample, dtype=np.float64)
        if sample_array.shape[0] < 10 or not all(math.isfinite(v) for v in bounds):
            raise QgsProcessingException('Não há pontos válidos suficientes na nuvem.')

        bin_size = min(0.10, spacing / 12.0)
        angle = self._estimate_orientation(sample_array, spacing, bin_size)
        radians = math.radians(angle)
        along = np.array([math.cos(radians), math.sin(radians)])
        across = np.array([-math.sin(radians), math.cos(radians)])
        feedback.pushInfo(f'Orientação predominante estimada: {angle:.2f}°.')

        along_min, along_max = self._projected_bounds(bounds, along)
        cross_min, cross_max = self._projected_bounds(bounds, across)
        station_step = 0.50
        cross_bin_size = 0.05
        cross_bin_count = max(
            2, int(math.ceil((cross_max - cross_min) / cross_bin_size)) + 1
        )
        along_length = max(0.0, along_max - along_min)
        station_count = max(1, int(math.ceil(along_length / station_step)) + 1)
        if cross_bin_count > 2000000:
            raise QgsProcessingException(
                'A largura projetada da nuvem excede o limite de análise local. '
                'Confira o CRS e a extensão da imagem selecionada.'
            )
        while station_count > 200000:
            station_step *= 1.25
            station_count = max(1, int(math.ceil(along_length / station_step)) + 1)
        feedback.pushInfo(
            f'Acumulando pontos em células esparsas ({station_count} estações de '
            f'{station_step:.2f} m; passo transversal de {cross_bin_size:.2f} m)...'
        )
        density_indices, density_counts = self._accumulate_density(
            points, along, across, along_min, cross_min, station_step,
            cross_bin_size, cross_bin_count, image_extent, point_count, feedback,
        )
        if feedback.isCanceled():
            return {}

        feedback.pushInfo('Rastreando os centros das fileiras ao longo do campo...')
        candidates_by_station = []
        support_half_bins = max(1, int(round(0.75 / station_step)))
        for station_index in range(station_count):
            if station_index % 20 == 0:
                if feedback.isCanceled():
                    return {}
                feedback.setProgress(40 + 25 * station_index / station_count)
            lo = max(0, station_index - support_half_bins)
            hi = min(station_count, station_index + support_half_bins + 1)
            first = np.searchsorted(
                density_indices, lo * cross_bin_count, side='left'
            )
            last = np.searchsorted(
                density_indices, hi * cross_bin_count, side='left'
            )
            cross_bins = density_indices[first:last] % cross_bin_count
            profile = np.bincount(
                cross_bins,
                weights=density_counts[first:last],
                minlength=cross_bin_count,
            )
            centers = self._find_row_centers(
                profile, cross_min, cross_bin_size, spacing, min_points
            )
            candidates_by_station.append([
                self._weighted_center(
                    profile, center, cross_min, cross_bin_size,
                    min(0.30, spacing * 0.25),
                )
                for center in centers
            ])
        row_tracks = self._track_rows(
            candidates_by_station, station_step, spacing, max_deviation, max_gap,
            feedback,
        )
        if feedback.isCanceled():
            return {}
        stations_with_candidates = sum(
            bool(candidates) for candidates in candidates_by_station
        )
        max_candidates = max(
            (len(candidates) for candidates in candidates_by_station), default=0
        )
        feedback.pushInfo(
            f'Estações com fileiras candidatas: {stations_with_candidates}/{station_count}; '
            f'máximo de candidatos numa estação: {max_candidates}.'
        )
        viable_tracks = [track for track in row_tracks if len(track) >= 3]
        if len(viable_tracks) < 2:
            feedback.pushInfo(
                f'Diagnóstico: orientação global {angle:.2f}°, passo longitudinal '
                f'{station_step:.2f} m, trilhas temporais {len(row_tracks)}, '
                f'trilhas com pelo menos três estações {len(viable_tracks)}.'
            )
            raise QgsProcessingException(
                'Não foram identificadas pelo menos duas fileiras contínuas. Confira '
                'o espaçamento informado e a classificação da nuvem.'
            )
        feedback.pushInfo(f'Fileiras acompanhadas localmente: {len(viable_tracks)}.')

        fields = QgsFields()
        fields.append(QgsField('linha_id', QVariant.Int))
        fields.append(QgsField('angulo_graus', QVariant.Double, len=10, prec=3))
        fields.append(QgsField('compr_m', QVariant.Double, len=14, prec=2))
        sink, destination = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.LineString, crs,
        )
        if sink is None:
            raise QgsProcessingException('Não foi possível criar a camada de linhas.')

        output_id = 0
        for track in viable_tracks:
            if feedback.isCanceled():
                return {}
            observed = np.asarray([item[0] for item in track], dtype=np.int64)
            observed_offsets = np.asarray([item[1] for item in track], dtype=np.float64)
            breaks = np.flatnonzero(np.diff(observed) * station_step > max_gap)
            groups = np.split(np.arange(len(observed)), breaks + 1)
            for group in groups:
                if group.size < 3:
                    continue
                group_indices = observed[group]
                start, end = int(group_indices[0]), int(group_indices[-1])
                bins = np.arange(start, end + 1)
                fitted = np.interp(
                    bins, group_indices, observed_offsets[group]
                )
                fitted = self._smooth(fitted, window=3)
                line_points = []
                for index, offset in zip(bins, fitted):
                    t = along_min + index * station_step
                    s = float(offset)
                    x = along[0] * t + across[0] * s
                    y = along[1] * t + across[1] * s
                    line_points.append(QgsPointXY(x, y))
                if len(line_points) < 2:
                    continue
                geometry = QgsGeometry.fromPolylineXY(line_points)
                length = geometry.length()
                if length < 2.0:
                    continue
                feature = QgsFeature(fields)
                feature.setGeometry(geometry)
                feature.setAttributes([output_id + 1, angle % 180.0, length])
                if not sink.addFeature(feature, QgsFeatureSink.FastInsert):
                    raise QgsProcessingException('Falha ao gravar uma linha restituída.')
                output_id += 1

        feedback.pushInfo(
            f'Restituição concluída: {output_id} segmento(s) de linha criado(s). '
            'Cada traçado acompanha o centro local da fileira ao longo do campo.'
        )
        return {self.OUTPUT: destination}

    def _sample_points(self, layer, extent, feedback):
        rng = random.Random(207)
        sample = []
        total = 0
        xmin = ymin = float('inf')
        xmax = ymax = float('-inf')
        request = QgsFeatureRequest()
        request.setNoAttributes()
        request.setFilterRect(extent)
        for feature in layer.getFeatures(request):
            if total % 50000 == 0 and feedback.isCanceled():
                return sample, (xmin, ymin, xmax, ymax), total
            geometry = feature.geometry()
            if geometry is None or geometry.isNull() or geometry.isEmpty():
                continue
            point = geometry.asPoint()
            x, y = point.x(), point.y()
            if not math.isfinite(x) or not math.isfinite(y):
                continue
            total += 1
            xmin, ymin = min(xmin, x), min(ymin, y)
            xmax, ymax = max(xmax, x), max(ymax, y)
            coordinate = (x, y)
            if len(sample) < self.SAMPLE_LIMIT:
                sample.append(coordinate)
            else:
                index = rng.randrange(total)
                if index < self.SAMPLE_LIMIT:
                    sample[index] = coordinate
        return sample, (xmin, ymin, xmax, ymax), total

    def _estimate_orientation(self, sample, spacing, bin_size):
        best_angle = 0.0
        best_score = float('-inf')
        lag_min = max(1, int(round((spacing - 0.25) / bin_size)))
        lag_max = max(lag_min, int(round((spacing + 0.25) / bin_size)))
        short_lag_min = max(1, int(round(0.20 / bin_size)))
        short_lag_max = max(
            short_lag_min,
            min(
                lag_min - 1,
                int(round(min(spacing * 0.60, spacing - 0.10) / bin_size)),
            ),
        )
        for angle in np.arange(0.0, 180.0, 1.0):
            radians = math.radians(angle)
            normal = np.array([-math.sin(radians), math.cos(radians)])
            projection = sample @ normal
            start = float(projection.min())
            size = max(2, int(math.ceil((projection.max() - start) / bin_size)) + 1)
            profile = np.histogram(
                projection, bins=size, range=(start, start + size * bin_size)
            )[0].astype(np.float64)
            smooth_width = max(1, int(round(0.30 / bin_size)))
            smooth_kernel = np.ones(smooth_width, dtype=np.float64) / smooth_width
            centered = np.convolve(profile, smooth_kernel, mode='same')
            mean = float(centered.mean())
            peakiness = float(centered.std() / (mean + 1e-9))
            centered -= mean
            energy = float(np.dot(centered, centered))
            if energy <= 0:
                continue
            periodicity = 0.0
            for lag in range(lag_min, min(lag_max, len(centered) - 1) + 1):
                score = float(np.dot(centered[:-lag], centered[lag:]) / energy)
                periodicity = max(periodicity, score)
            shorter_periodicity = 0.0
            for lag in range(
                    short_lag_min, min(short_lag_max, len(centered) - 1) + 1):
                score = float(np.dot(centered[:-lag], centered[lag:]) / energy)
                shorter_periodicity = max(shorter_periodicity, score)
            # Cane rows repeat at the inter-row spacing. Penalizing strong
            # shorter repeats helps distinguish that spacing from repeated
            # plants along a row (a common source of 90-degree errors).
            fundamental = periodicity - 0.90 * max(0.0, shorter_periodicity)
            score = peakiness * max(0.0, fundamental)
            if score > best_score:
                best_score, best_angle = score, float(angle)
        return best_angle

    def _projected_bounds(self, bounds, vector):
        xmin, ymin, xmax, ymax = bounds
        corners = np.array([
            [xmin, ymin], [xmin, ymax], [xmax, ymin], [xmax, ymax]
        ], dtype=np.float64)
        projected = corners @ vector
        return float(projected.min()), float(projected.max())

    def _find_row_centers(self, profile, start, bin_size, spacing, min_points):
        if len(profile) < 3:
            return []
        width = min(len(profile), max(1, int(round(0.35 / bin_size))))
        kernel = np.ones(width, dtype=np.float64) / width
        smoothed = np.convolve(profile, kernel, mode='same')
        local_support = np.convolve(
            profile, np.ones(width, dtype=np.float64), mode='same'
        )
        minimum_distance = max(1, int(round(spacing * 0.68 / bin_size)))
        local_maxima = (
            np.flatnonzero(
                (smoothed[1:-1] >= smoothed[:-2])
                & (smoothed[1:-1] > smoothed[2:])
                & (smoothed[1:-1] > 0)
            ) + 1
        ).tolist()
        if smoothed[0] > smoothed[1] and smoothed[0] > 0:
            local_maxima.append(0)
        if smoothed[-1] > smoothed[-2] and smoothed[-1] > 0:
            local_maxima.append(len(smoothed) - 1)
        if not local_maxima:
            return []
        peak_floor = max(
            0.25,
            float(smoothed.max()) * 0.05,
            float(np.median(smoothed)) * 1.15,
        )
        candidates = [
            i for i in local_maxima
            if smoothed[i] >= peak_floor and local_support[i] >= min_points
        ]
        if not candidates:
            return []

        # Keep local supported ridges, then suppress nearby alternatives inside
        # the same crop row. The row tracker links these peaks across stations;
        # choosing one global lattice independently at every station can shift
        # the row phase and fragment otherwise continuous field rows.
        ranked = sorted(candidates, key=lambda index: smoothed[index], reverse=True)
        suppressed = np.zeros(len(smoothed), dtype=bool)
        selected = []
        for peak in ranked:
            if suppressed[peak]:
                continue
            selected.append(peak)
            lo = max(0, peak - minimum_distance)
            hi = min(len(suppressed), peak + minimum_distance + 1)
            suppressed[lo:hi] = True
        selected.sort()
        return [start + index * bin_size for index in selected]

    def _coordinate_batches(self, layer, extent):
        batch = []
        request = QgsFeatureRequest()
        request.setNoAttributes()
        request.setFilterRect(extent)
        for feature in layer.getFeatures(request):
            geometry = feature.geometry()
            if geometry is None or geometry.isNull() or geometry.isEmpty():
                continue
            point = geometry.asPoint()
            batch.append((point.x(), point.y()))
            if len(batch) >= self.POINT_BATCH:
                yield np.asarray(batch, dtype=np.float64)
                batch = []
        if batch:
            yield np.asarray(batch, dtype=np.float64)

    def _accumulate_density(
            self, layer, along, across, along_min, cross_min, station_step,
            cross_bin_size, cross_bin_count, extent, total_points, feedback):
        processed_points = 0
        index_batches = []
        count_batches = []
        for coordinates in self._coordinate_batches(layer, extent):
            if feedback.isCanceled():
                return None, None
            processed_points += len(coordinates)
            t = coordinates @ along
            s = coordinates @ across
            station_index = np.floor((t - along_min) / station_step).astype(np.int64)
            cross_index = np.floor((s - cross_min) / cross_bin_size).astype(np.int64)
            valid = (
                (station_index >= 0)
                & (cross_index >= 0) & (cross_index < cross_bin_count)
            )
            if np.any(valid):
                flat_indices = (
                    station_index[valid] * cross_bin_count + cross_index[valid]
                )
                unique_indices, counts = np.unique(
                    flat_indices, return_counts=True
                )
                index_batches.append(unique_indices)
                count_batches.append(counts.astype(np.uint32))
            feedback.setProgress(
                15 + 25 * min(processed_points, total_points) / max(1, total_points)
            )
        if not index_batches:
            return np.asarray([], dtype=np.int64), np.asarray([], dtype=np.uint32)
        indices = np.concatenate(index_batches)
        counts = np.concatenate(count_batches)
        unique_indices, inverse = np.unique(indices, return_inverse=True)
        merged_counts = np.bincount(inverse, weights=counts).astype(np.uint32)
        return unique_indices, merged_counts

    def _weighted_center(self, profile, center, start, bin_size, radius):
        center_index = int(round((center - start) / bin_size))
        half_bins = max(1, int(round(radius / bin_size)))
        lo = max(0, center_index - half_bins)
        hi = min(len(profile), center_index + half_bins + 1)
        weights = profile[lo:hi]
        total = float(weights.sum())
        if total <= 0:
            return center
        median_index = int(np.searchsorted(np.cumsum(weights), total * 0.5))
        return start + (lo + median_index + 0.5) * bin_size

    def _track_rows(
            self, candidates_by_station, station_step, spacing,
            max_deviation, max_gap, feedback):
        tracks = []
        active_track_indices = []
        gap_limit = max(1, int(math.ceil(max_gap / station_step)))
        for station_index, candidates in enumerate(candidates_by_station):
            if station_index % 20 == 0:
                if feedback.isCanceled():
                    return tracks
                feedback.setProgress(
                    65 + 15 * station_index / max(1, len(candidates_by_station))
                )
            active_track_indices = [
                index for index in active_track_indices
                if station_index - tracks[index][-1][0] <= gap_limit
            ]
            active = []
            for track_index in active_track_indices:
                track = tracks[track_index]
                last_station, last_center = track[-1]
                active.append((track_index, last_station, last_center, track))
            active.sort(key=lambda item: item[2])
            active_centers = np.asarray(
                [item[2] for item in active], dtype=np.float64
            )
            pairs = []
            for candidate_index, center in enumerate(candidates):
                search_radius = spacing * 0.45 * 1.5
                lo = np.searchsorted(active_centers, center - search_radius, side='left')
                hi = np.searchsorted(active_centers, center + search_radius, side='right')
                for track_index, last_station, last_center, track in active[lo:hi]:
                    elapsed = station_index - last_station
                    max_shift = min(
                        max_deviation * elapsed * station_step, spacing * 0.45
                    )
                    predicted = last_center
                    if len(track) >= 2:
                        prior_station, prior_center = track[-2]
                        steps = last_station - prior_station
                        if steps > 0:
                            velocity = (last_center - prior_center) / steps
                            extrapolation = velocity * elapsed
                            extrapolation = min(
                                max(extrapolation, -max_shift * 0.5), max_shift * 0.5
                            )
                            predicted += extrapolation
                    distance = abs(center - predicted)
                    if distance <= max_shift:
                        pairs.append((distance, track_index, candidate_index))
            pairs.sort()
            used_tracks = set()
            used_candidates = set()
            for _distance, track_index, candidate_index in pairs:
                if track_index in used_tracks or candidate_index in used_candidates:
                    continue
                tracks[track_index].append(
                    (station_index, float(candidates[candidate_index]))
                )
                used_tracks.add(track_index)
                used_candidates.add(candidate_index)
            active_track_indices = [
                track_index for track_index, _last, _center, _track in active
            ]
            for candidate_index, center in enumerate(candidates):
                if candidate_index not in used_candidates:
                    tracks.append([(station_index, float(center))])
                    active_track_indices.append(len(tracks) - 1)
        return tracks

    def _smooth(self, values, window):
        if len(values) < window:
            return values
        pad_left = window // 2
        pad_right = window - 1 - pad_left
        padded = np.pad(values, (pad_left, pad_right), mode='edge')
        return np.convolve(padded, np.ones(window) / window, mode='valid')

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
            'Usa a imagem como referência espacial e a nuvem de pontos da cultura '
            'para estimar a orientação e o espaçamento das linhas e desenhar cada '
            'linha ajustada localmente aos pontos. A densidade é examinada em '
            'estações sucessivas e os centros são rastreados ao longo do campo, '
            'permitindo acompanhar curvas de nível sem forçar linhas retas e '
            'paralelas. '
            'A saída é uma camada vetorial de linhas no CRS métrico da nuvem.\n\n'
            'Ajuste o espaçamento esperado conforme o plantio. A posição de cada '
            'trecho usa o centro ponderado da distribuição local para reduzir o '
            'deslocamento causado por pontos fora da fileira, e a densidade mínima descarta trechos sustentados '
            'por poucos pontos. Os pontos precisam estar em CRS métrico; a imagem '
            'pode estar em outro CRS e é usada para conferir a área analisada.'
        )
