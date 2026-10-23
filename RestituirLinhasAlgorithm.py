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
            'Largura máxima para associar pontos à linha (m)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.45,
            minValue=0.05,
            maxValue=1.5,
        ))
        self.addParameter(QgsProcessingParameterNumber(
            self.MAX_GAP,
            'Maior intervalo entre pontos para manter a linha contínua (m)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=3.0,
            minValue=0.5,
            maxValue=20.0,
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
        crs = raster.crs()
        if not crs.isValid() or crs.isGeographic():
            raise QgsProcessingException(
                'A imagem deve usar um CRS projetado com unidades métricas.'
            )
        if crs.mapUnits() != QgsUnitTypes.DistanceMeters:
            raise QgsProcessingException(
                'A imagem deve usar um CRS projetado em metros para aplicar o '
                'espaçamento e as tolerâncias da restituição.'
            )
        if points.crs() != crs:
            raise QgsProcessingException(
                'A nuvem de pontos e a imagem precisam estar no mesmo CRS.'
            )

        spacing = self.parameterAsDouble(parameters, self.ROW_SPACING, context)
        max_deviation = self.parameterAsDouble(parameters, self.MAX_DEVIATION, context)
        max_gap = self.parameterAsDouble(parameters, self.MAX_GAP, context)
        point_count = points.featureCount()
        if point_count < 10:
            raise QgsProcessingException(
                'A nuvem tem poucos pontos para identificar a orientação das linhas.'
            )

        feedback.pushInfo('Amostrando os pontos para estimar a orientação predominante...')
        sample, bounds = self._sample_points(points, feedback)
        if feedback.isCanceled():
            return {}
        sample_array = np.asarray(sample, dtype=np.float64)
        if sample_array.shape[0] < 10 or not all(math.isfinite(v) for v in bounds):
            raise QgsProcessingException('Não há pontos válidos suficientes na nuvem.')

        bin_size = min(0.10, spacing / 12.0)
        angle = self._estimate_orientation(sample_array, spacing, bin_size)
        radians = math.radians(angle)
        along = np.array([math.cos(radians), math.sin(radians)])
        across = np.array([-math.sin(radians), math.cos(radians)])
        feedback.pushInfo(f'Orientação predominante estimada: {angle:.2f}°.')

        feedback.pushInfo('Localizando os centros das linhas de plantio...')
        normal_min, normal_max = self._projected_bounds(bounds, across)
        profile_size = max(2, int(math.ceil((normal_max - normal_min) / bin_size)) + 1)
        profile = np.zeros(profile_size, dtype=np.float64)
        self._fill_profile(points, across, normal_min, bin_size, profile, feedback)
        if feedback.isCanceled():
            return {}
        centers = self._find_row_centers(profile, normal_min, bin_size, spacing)
        if len(centers) < 2:
            raise QgsProcessingException(
                'Não foram identificadas pelo menos duas linhas. Confira o '
                'espaçamento informado e a classificação da nuvem.'
            )
        feedback.pushInfo(f'Linhas candidatas identificadas: {len(centers)}.')

        along_min, along_max = self._projected_bounds(bounds, along)
        along_bin = 0.50
        along_count = max(1, int(math.ceil((along_max - along_min) / along_bin)) + 1)
        if len(centers) * along_count > 100000000:
            raise QgsProcessingException(
                'A grade de restituição ficou grande demais. Use uma área menor ou '
                'aumente o tamanho do pixel na etapa de classificação.'
            )
        offsets_sum = np.zeros((len(centers), along_count), dtype=np.float64)
        counts = np.zeros((len(centers), along_count), dtype=np.uint32)
        feedback.pushInfo('Ajustando cada linha aos pontos da cultura...')
        self._accumulate_rows(
            points, centers, along, across, along_min, along_bin,
            max_deviation, offsets_sum, counts, feedback,
        )
        if feedback.isCanceled():
            return {}

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
        for row_id, _center in enumerate(centers, start=1):
            if feedback.isCanceled():
                return {}
            observed = np.flatnonzero(counts[row_id - 1] > 0)
            if observed.size < 2:
                continue
            breaks = np.flatnonzero(np.diff(observed) * along_bin > max_gap)
            groups = np.split(observed, breaks + 1)
            for group in groups:
                if group.size < 2:
                    continue
                start, end = int(group[0]), int(group[-1])
                bins = np.arange(start, end + 1)
                observed_offsets = offsets_sum[row_id - 1, group] / counts[row_id - 1, group]
                fitted = np.interp(bins, group, observed_offsets)
                fitted = self._smooth(fitted, window=5)
                line_points = []
                for index, offset in zip(bins, fitted):
                    t = along_min + index * along_bin
                    s = float(offset)
                    x = along[0] * t + across[0] * s
                    y = along[1] * t + across[1] * s
                    line_points.append(QgsPointXY(x, y))
                if len(line_points) < 2:
                    continue
                geometry = QgsGeometry.fromPolylineXY(line_points)
                length = geometry.length()
                if length <= 0:
                    continue
                feature = QgsFeature(fields)
                feature.setGeometry(geometry)
                feature.setAttributes([row_id, angle % 180.0, length])
                if not sink.addFeature(feature, QgsFeatureSink.FastInsert):
                    raise QgsProcessingException('Falha ao gravar uma linha restituída.')
                output_id += 1

        feedback.pushInfo(
            f'Restituição concluída: {output_id} segmento(s) de linha criado(s). '
            'Cada linha foi ajustada individualmente à distribuição local dos pontos.'
        )
        return {self.OUTPUT: destination}

    def _sample_points(self, layer, feedback):
        rng = random.Random(207)
        sample = []
        total = 0
        xmin = ymin = float('inf')
        xmax = ymax = float('-inf')
        for feature in layer.getFeatures():
            if total % 50000 == 0 and feedback.isCanceled():
                return sample, (xmin, ymin, xmax, ymax)
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
        return sample, (xmin, ymin, xmax, ymax)

    def _estimate_orientation(self, sample, spacing, bin_size):
        best_angle = 0.0
        best_score = float('-inf')
        lag_min = max(1, int(round((spacing - 0.25) / bin_size)))
        lag_max = max(lag_min, int(round((spacing + 0.25) / bin_size)))
        for angle in np.arange(0.0, 180.0, 1.0):
            radians = math.radians(angle)
            normal = np.array([-math.sin(radians), math.cos(radians)])
            projection = sample @ normal
            start = float(projection.min())
            size = max(2, int(math.ceil((projection.max() - start) / bin_size)) + 1)
            profile = np.histogram(
                projection, bins=size, range=(start, start + size * bin_size)
            )[0].astype(np.float64)
            centered = profile - profile.mean()
            energy = float(np.dot(centered, centered))
            if energy <= 0:
                continue
            for lag in range(lag_min, min(lag_max, len(centered) - 1) + 1):
                score = float(np.dot(centered[:-lag], centered[lag:]) / energy)
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

    def _fill_profile(self, layer, vector, start, bin_size, profile, feedback):
        for coordinates in self._coordinate_batches(layer):
            if feedback.isCanceled():
                return
            values = coordinates @ vector
            indices = np.floor((values - start) / bin_size).astype(np.int64)
            indices = np.clip(indices, 0, len(profile) - 1)
            profile += np.bincount(indices, minlength=len(profile))

    def _find_row_centers(self, profile, start, bin_size, spacing):
        if len(profile) < 3:
            return []
        width = min(len(profile), max(1, int(round(0.35 / bin_size))))
        kernel = np.ones(width, dtype=np.float64) / width
        smoothed = np.convolve(profile, kernel, mode='same')
        minimum_distance = max(1, int(round(spacing * 0.68 / bin_size)))
        local_maxima = [
            index for index in range(1, len(smoothed) - 1)
            if smoothed[index] >= smoothed[index - 1]
            and smoothed[index] > smoothed[index + 1]
            and smoothed[index] > 0
        ]
        if not local_maxima:
            return []
        peak_floor = max(float(smoothed.max()) * 0.08, float(np.median(smoothed)) * 1.15)
        ordered = sorted(
            (i for i in local_maxima if smoothed[i] >= peak_floor),
            key=lambda i: smoothed[i], reverse=True,
        )
        selected = []
        for index in ordered:
            if all(abs(index - other) >= minimum_distance for other in selected):
                selected.append(index)
        return sorted(start + index * bin_size for index in selected)

    def _coordinate_batches(self, layer):
        batch = []
        for feature in layer.getFeatures():
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

    def _accumulate_rows(
            self, layer, centers, along, across, along_min, along_bin,
            max_deviation, offsets_sum, counts, feedback):
        centers_array = np.asarray(centers)
        for coordinates in self._coordinate_batches(layer):
            if feedback.isCanceled():
                return
            t = coordinates @ along
            s = coordinates @ across
            right = np.searchsorted(centers_array, s, side='left')
            left = np.clip(right - 1, 0, len(centers_array) - 1)
            right_clipped = np.clip(right, 0, len(centers_array) - 1)
            use_right = np.abs(s - centers_array[right_clipped]) < np.abs(s - centers_array[left])
            row = np.where(use_right, right_clipped, left)
            offset = np.abs(s - centers_array[row])
            valid = offset <= max_deviation
            along_index = np.floor((t - along_min) / along_bin).astype(np.int64)
            valid &= (along_index >= 0) & (along_index < counts.shape[1])
            if not np.any(valid):
                continue
            np.add.at(offsets_sum, (row[valid], along_index[valid]), s[valid])
            np.add.at(counts, (row[valid], along_index[valid]), 1)

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
            'linha ajustada localmente aos pontos. As linhas podem ter pequenas '
            'curvas independentes; o algoritmo não força todas a serem paralelas. '
            'A saída é uma camada vetorial de linhas no CRS da imagem.\n\n'
            'Ajuste o espaçamento esperado conforme o plantio. Os pontos precisam '
            'estar no mesmo CRS projetado da imagem.'
        )
