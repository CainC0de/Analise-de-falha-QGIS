
__author__ = 'CainC0de'
__date__ = '2022-09-25'
__copyright__ = '(C) 2026 CainC0de'

import logging
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingMultiStepFeedback,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputString,
    QgsProject,
)
import processing
from qgis.PyQt.QtGui import QIcon

logger = logging.getLogger('FalhaDePlantio')


class FalhaDePlantioAlgorithm(QgsProcessingAlgorithm):

    INPUT_RASTER = 'gligreenleafindex'
    INPUT_LINES = 'linhaplantio'
    INPUT_POLYGON = 'quadra'
    OUTPUT_FAILURES = 'FalhaDePlantio'
    PARAM_INDEX = 'indice_vegetacao'
    PARAM_THRESHOLD = 'threshold_gli'
    PARAM_BUFFER = 'buffer_contorno'
    PARAM_MIN_LENGTH = 'comp_minimo'
    PARAM_NIR_BAND = 'banda_nir'
    PARAM_SIEVE_SIZE = 'tamanho_sieve'
    PARAM_ANALYSIS_RES = 'resolucao_analise'
    PARAM_SIMPLIFY_TOL = 'simplificar_tolerancia'
    OUTPUT_STATS = 'Estatisticas'

    INDEX_CHOICES = ['GLI (RGB)', 'NDVI (NIR + Vermelho)']
    TOTAL_STEPS = 16

    def initAlgorithm(self, config=None):

        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_RASTER,
            'Raster (Drone/Imagem)',
            defaultValue=None,
        ))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_LINES,
            'Linhas de Plantio',
            types=[QgsProcessing.TypeVectorLine],
            defaultValue=None,
        ))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_POLYGON,
            'Contorno do Talhão',
            types=[QgsProcessing.TypeVectorPolygon],
            defaultValue=None,
        ))

        self.addParameter(QgsProcessingParameterEnum(
            self.PARAM_INDEX,
            'Índice de Vegetação',
            options=self.INDEX_CHOICES,
            defaultValue=0,
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.PARAM_THRESHOLD,
            'Limiar de Vegetação (threshold do índice)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.0,
            minValue=-1.0,
            maxValue=1.0,
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.PARAM_BUFFER,
            'Buffer do Contorno (unidades do CRS)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.1,
            minValue=0.0,
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.PARAM_MIN_LENGTH,
            'Comprimento Mínimo de Falha (metros)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.5,
            minValue=0.0,
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.PARAM_NIR_BAND,
            'Banda NIR (somente se usar NDVI)',
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=4,
            minValue=1,
            optional=True,
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.PARAM_SIEVE_SIZE,
            'Sieve — Mín. pixels por grupo (anti-ruído raster)',
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=50,
            minValue=0,
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.PARAM_ANALYSIS_RES,
            'Resolução de Análise (metros, 0=original)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.20,
            minValue=0.0,
        ))

        self.addParameter(QgsProcessingParameterNumber(
            self.PARAM_SIMPLIFY_TOL,
            'Tolerância de Simplificação (unidades do CRS)',
            type=QgsProcessingParameterNumber.Double,
            defaultValue=0.1,
            minValue=0.0,
        ))

        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT_FAILURES,
            'Resultado das Falhas (Linhas)',
            type=QgsProcessing.TypeVectorAnyGeometry,
            createByDefault=True,
            supportsAppend=True,
            defaultValue=None,
        ))

        self.addOutput(QgsProcessingOutputString(
            self.OUTPUT_STATS,
            'Estatísticas das Falhas',
        ))

    def processAlgorithm(self, parameters, context, model_feedback):

        feedback = QgsProcessingMultiStepFeedback(self.TOTAL_STEPS, model_feedback)
        results = {}
        outputs = {}
        step = 0

        indice = self.parameterAsEnum(parameters, self.PARAM_INDEX, context)
        threshold = self.parameterAsDouble(parameters, self.PARAM_THRESHOLD, context)
        buffer_dist = self.parameterAsDouble(parameters, self.PARAM_BUFFER, context)
        comp_minimo = self.parameterAsDouble(parameters, self.PARAM_MIN_LENGTH, context)
        banda_nir = self.parameterAsInt(parameters, self.PARAM_NIR_BAND, context)
        sieve_size = self.parameterAsInt(parameters, self.PARAM_SIEVE_SIZE, context)
        resolucao = self.parameterAsDouble(parameters, self.PARAM_ANALYSIS_RES, context)
        simplify_tol = self.parameterAsDouble(parameters, self.PARAM_SIMPLIFY_TOL, context)

        context.setTransformContext(QgsProject.instance().transformContext())
        project_crs = QgsProject.instance().crs().authid()

        logger.info(
            'Análise de falha: índice=%s, threshold=%.3f, sieve=%d, '
            'resolução=%.3f, simplificação=%.3f',
            self.INDEX_CHOICES[indice], threshold, sieve_size,
            resolucao, simplify_tol)

        step += 1
        feedback.pushInfo(f'Passo {step}/{self.TOTAL_STEPS}: Criando buffer no contorno...')
        try:
            alg_params = {
                'DISSOLVE': False,
                'DISTANCE': buffer_dist,
                'END_CAP_STYLE': 0,
                'INPUT': parameters[self.INPUT_POLYGON],
                'JOIN_STYLE': 0,
                'MITER_LIMIT': 2,
                'SEGMENTS': 5,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
            outputs['BufferContorno'] = processing.run(
                'native:buffer', alg_params,
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            feedback.reportError(f'Erro no buffer do contorno: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(f'Passo {step}/{self.TOTAL_STEPS}: Recortando raster pelo contorno...')
        try:
            alg_params = {
                'ALPHA_BAND': False,
                'CROP_TO_CUTLINE': True,
                'DATA_TYPE': 0,
                'INPUT': parameters[self.INPUT_RASTER],
                'MASK': outputs['BufferContorno']['OUTPUT'],
                'NODATA': 0,
                'SOURCE_CRS': project_crs,
                'TARGET_CRS': project_crs,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
            outputs['RasterRecortado'] = processing.run(
                'gdal:cliprasterbymasklayer', alg_params,
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            feedback.reportError(f'Erro ao recortar raster: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        if indice == 0:
            feedback.pushInfo(f'Passo {step}/{self.TOTAL_STEPS}: Calculando índice GLI (RGB)...')
            formula = '(2.0*A - B - C) / (2.0*A + B + C + 0.0001)'
            alg_params = {
                'INPUT_A': outputs['RasterRecortado']['OUTPUT'], 'BAND_A': 2,
                'INPUT_B': outputs['RasterRecortado']['OUTPUT'], 'BAND_B': 1,
                'INPUT_C': outputs['RasterRecortado']['OUTPUT'], 'BAND_C': 3,
                'FORMULA': formula,
                'RTYPE': 5,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
        else:
            feedback.pushInfo(
                f'Passo {step}/{self.TOTAL_STEPS}: Calculando NDVI (NIR={banda_nir})...')
            formula = '(A - B) / (A + B + 0.0001)'
            alg_params = {
                'INPUT_A': outputs['RasterRecortado']['OUTPUT'], 'BAND_A': banda_nir,
                'INPUT_B': outputs['RasterRecortado']['OUTPUT'], 'BAND_B': 1,
                'FORMULA': formula,
                'RTYPE': 5,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
        try:
            outputs['CalculoIndice'] = processing.run(
                'gdal:rastercalculator', alg_params,
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            feedback.reportError(f'Erro no índice de vegetação: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(
            f'Passo {step}/{self.TOTAL_STEPS}: Máscara binária '
            f'(threshold={threshold}, tipo=Byte)...')
        try:
            alg_params = {
                'INPUT_A': outputs['CalculoIndice']['OUTPUT'], 'BAND_A': 1,
                'FORMULA': f'(A > {threshold}) * 1',
                'RTYPE': 1,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
            outputs['MascaraBinaria'] = processing.run(
                'gdal:rastercalculator', alg_params,
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            feedback.reportError(f'Erro na máscara de vegetação: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        if sieve_size > 0:
            feedback.pushInfo(
                f'Passo {step}/{self.TOTAL_STEPS}: Sieve filter '
                f'(removendo grupos < {sieve_size} pixels)...')
            try:
                alg_params = {
                    'INPUT': outputs['MascaraBinaria']['OUTPUT'],
                    'THRESHOLD': sieve_size,
                    'EIGHT_CONNECTEDNESS': False,
                    'NO_MASK': False,
                    'MASK_LAYER': None,
                    'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
                }
                outputs['SieveFiltrado'] = processing.run(
                    'gdal:sieve', alg_params,
                    context=context, feedback=feedback, is_child_algorithm=True)
            except Exception as e:
                feedback.reportError(f'Erro no sieve filter: {e}', fatalError=True)
                return {}
        else:
            feedback.pushInfo(
                f'Passo {step}/{self.TOTAL_STEPS}: Sieve filter desabilitado (tamanho=0).')
            outputs['SieveFiltrado'] = {'OUTPUT': outputs['MascaraBinaria']['OUTPUT']}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        if resolucao > 0:
            feedback.pushInfo(
                f'Passo {step}/{self.TOTAL_STEPS}: Reamostrando para '
                f'{resolucao}m de resolução...')
            try:
                alg_params = {
                    'INPUT': outputs['SieveFiltrado']['OUTPUT'],
                    'SOURCE_CRS': project_crs,
                    'TARGET_CRS': project_crs,
                    'RESAMPLING': 0,
                    'TARGET_RESOLUTION': resolucao,
                    'NODATA': 0,
                    'DATA_TYPE': 1,
                    'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
                }
                outputs['Reamostrado'] = processing.run(
                    'gdal:warpreproject', alg_params,
                    context=context, feedback=feedback, is_child_algorithm=True)
            except Exception as e:
                feedback.reportError(f'Erro na reamostragem: {e}', fatalError=True)
                return {}
        else:
            feedback.pushInfo(
                f'Passo {step}/{self.TOTAL_STEPS}: Reamostragem desabilitada (resolução=0).')
            outputs['Reamostrado'] = {'OUTPUT': outputs['SieveFiltrado']['OUTPUT']}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(
            f'Passo {step}/{self.TOTAL_STEPS}: Convertendo raster em polígonos...')
        try:
            alg_params = {
                'INPUT': outputs['Reamostrado']['OUTPUT'],
                'BAND': 1,
                'FIELD': 'DN',
                'EIGHT_CONNECTEDNESS': False,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
            outputs['Vetorizar'] = processing.run(
                'gdal:polygonize', alg_params,
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            feedback.reportError(f'Erro na poligonização: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(
            f'Passo {step}/{self.TOTAL_STEPS}: Extraindo polígonos de vegetação (DN=1)...')
        try:
            alg_params = {
                'FIELD': 'DN',
                'INPUT': outputs['Vetorizar']['OUTPUT'],
                'OPERATOR': 0,
                'VALUE': '1',
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
            outputs['ExtrairPlanta'] = processing.run(
                'native:extractbyattribute', alg_params,
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            feedback.reportError(f'Erro ao extrair vegetação: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(
            f'Passo {step}/{self.TOTAL_STEPS}: Dissolvendo polígonos adjacentes...')
        try:
            alg_params = {
                'INPUT': outputs['ExtrairPlanta']['OUTPUT'],
                'FIELD': [],
                'SEPARATE_DISJOINT': False,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
            outputs['VegetacaoFundida'] = processing.run(
                'native:dissolve', alg_params,
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            feedback.reportError(f'Erro ao dissolver polígonos: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        if simplify_tol > 0:
            feedback.pushInfo(
                f'Passo {step}/{self.TOTAL_STEPS}: Simplificando geometrias '
                f'(tolerância={simplify_tol})...')
            try:
                alg_params = {
                    'INPUT': outputs['VegetacaoFundida']['OUTPUT'],
                    'METHOD': 0,
                    'TOLERANCE': simplify_tol,
                    'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
                }
                outputs['VegetacaoSimplificada'] = processing.run(
                    'native:simplifygeometries', alg_params,
                    context=context, feedback=feedback, is_child_algorithm=True)
            except Exception as e:
                feedback.reportError(f'Erro ao simplificar: {e}', fatalError=True)
                return {}
        else:
            feedback.pushInfo(
                f'Passo {step}/{self.TOTAL_STEPS}: Simplificação desabilitada (tolerância=0).')
            outputs['VegetacaoSimplificada'] = {
                'OUTPUT': outputs['VegetacaoFundida']['OUTPUT']}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(
            f'Passo {step}/{self.TOTAL_STEPS}: Recortando linhas de plantio...')
        try:
            alg_params = {
                'INPUT': parameters[self.INPUT_LINES],
                'MASK': outputs['BufferContorno']['OUTPUT'],
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
            outputs['LinhasNoTalhao'] = processing.run(
                'gdal:clipvectorbypolygon', alg_params,
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            feedback.reportError(f'Erro ao recortar linhas: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(
            f'Passo {step}/{self.TOTAL_STEPS}: Calculando diferença '
            f'(linhas − vegetação = falhas)...')
        try:
            alg_params = {
                'INPUT': outputs['LinhasNoTalhao']['OUTPUT'],
                'OVERLAY': outputs['VegetacaoSimplificada']['OUTPUT'],
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
            outputs['GerarFalhas'] = processing.run(
                'native:difference', alg_params,
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            feedback.reportError(f'Erro ao gerar falhas: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(
            f'Passo {step}/{self.TOTAL_STEPS}: Explodindo geometrias multipartes...')
        try:
            alg_params = {
                'INPUT': outputs['GerarFalhas']['OUTPUT'],
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
            outputs['PartesSimples'] = processing.run(
                'native:multiparttosingleparts', alg_params,
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            feedback.reportError(f'Erro ao explodir multipartes: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(
            f'Passo {step}/{self.TOTAL_STEPS}: Calculando comprimento das falhas...')
        try:
            alg_params = {
                'FIELD_LENGTH': 10,
                'FIELD_NAME': 'comp_m',
                'FIELD_PRECISION': 2,
                'FIELD_TYPE': 0,
                'FORMULA': '$length',
                'INPUT': outputs['PartesSimples']['OUTPUT'],
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
            outputs['ComComprimento'] = processing.run(
                'native:fieldcalculator', alg_params,
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            feedback.reportError(f'Erro ao calcular comprimento: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(
            f'Passo {step}/{self.TOTAL_STEPS}: Filtrando falhas < {comp_minimo}m...')
        try:
            alg_params = {
                'FIELD': 'comp_m',
                'INPUT': outputs['ComComprimento']['OUTPUT'],
                'OPERATOR': 2,
                'VALUE': str(comp_minimo),
                'OUTPUT': parameters[self.OUTPUT_FAILURES],
            }
            outputs['ResultadoFinal'] = processing.run(
                'native:extractbyattribute', alg_params,
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            feedback.reportError(f'Erro ao filtrar por comprimento: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        results[self.OUTPUT_FAILURES] = outputs['ResultadoFinal']['OUTPUT']

        step += 1
        feedback.pushInfo(f'Passo {step}/{self.TOTAL_STEPS}: Gerando estatísticas...')
        try:
            stats = self._calcular_estatisticas(
                outputs['ResultadoFinal']['OUTPUT'],
                outputs['LinhasNoTalhao']['OUTPUT'],
                context, feedback)
            results[self.OUTPUT_STATS] = stats
            feedback.pushInfo(stats)
        except Exception as e:
            feedback.reportError(f'Aviso: Estatísticas indisponíveis: {e}')
            results[self.OUTPUT_STATS] = 'Estatísticas indisponíveis'
        feedback.setCurrentStep(step)

        logger.info('Análise de falha de plantio concluída com sucesso.')
        return results

    def _calcular_estatisticas(self, falhas_output, linhas_output, context, feedback):

        alg_params = {
            'FIELD_LENGTH': 10,
            'FIELD_NAME': 'comp_linha_m',
            'FIELD_PRECISION': 2,
            'FIELD_TYPE': 0,
            'FORMULA': '$length',
            'INPUT': linhas_output,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
        }
        linhas_com_comp = processing.run(
            'native:fieldcalculator', alg_params,
            context=context, feedback=feedback, is_child_algorithm=True)

        stats_linhas = processing.run(
            'qgis:basicstatisticsforfields', {
                'FIELD_NAME': 'comp_linha_m',
                'INPUT': linhas_com_comp['OUTPUT'],
                'OUTPUT_HTML_FILE': QgsProcessing.TEMPORARY_OUTPUT,
            },
            context=context, feedback=feedback, is_child_algorithm=True)
        comp_total_linhas = float(stats_linhas.get('SUM', 0))

        stats_falhas = processing.run(
            'qgis:basicstatisticsforfields', {
                'FIELD_NAME': 'comp_m',
                'INPUT': falhas_output,
                'OUTPUT_HTML_FILE': QgsProcessing.TEMPORARY_OUTPUT,
            },
            context=context, feedback=feedback, is_child_algorithm=True)

        total_falhas = int(stats_falhas.get('COUNT', 0))
        comp_total = float(stats_falhas.get('SUM', 0))
        comp_medio = float(stats_falhas.get('MEAN', 0))
        comp_max = float(stats_falhas.get('MAX', 0))

        percentual = (comp_total / comp_total_linhas * 100) if comp_total_linhas > 0 else 0.0

        return (
            '========== ESTATÍSTICAS DE FALHAS ==========\n'
            f'Total de falhas encontradas: {total_falhas}\n'
            f'Comprimento total de falhas: {comp_total:.2f} m\n'
            f'Comprimento médio por falha: {comp_medio:.2f} m\n'
            f'Maior falha encontrada:      {comp_max:.2f} m\n'
            f'Comprimento total de linhas: {comp_total_linhas:.2f} m\n'
            f'Percentual de falha:         {percentual:.2f}%\n'
            '============================================='
        )

    def name(self):
        return 'falha_plantio_estavel'

    def displayName(self):
        return 'Falha de Plantio (Cana-de-açúcar)'

    def group(self):
        return 'Análise'

    def groupId(self):
        return 'analise'

    def createInstance(self):
        return FalhaDePlantioAlgorithm()

    def shortHelpString(self):
        return (
            'Identifica falhas de plantio na cultura de cana-de-açúcar '
            'usando imagem aérea, linhas de plantio e contorno do talhão.\n\n'
            'OTIMIZADO para imagens de drone de alta resolução '
            '(>15.000×15.000 pixels).\n\n'
            'ENTRADAS:\n'
            '• Raster — imagem RGB de drone/satélite (ou multibanda com NIR)\n'
            '• Linhas de Plantio — camada vetorial de linhas\n'
            '• Contorno do Talhão — polígono delimitador da área\n\n'
            'PARÂMETROS DE ANÁLISE:\n'
            '• Índice de Vegetação — GLI (RGB) ou NDVI (NIR+Vermelho)\n'
            '• Limiar de Vegetação — valor mínimo do índice (padrão: 0.0)\n'
            '• Buffer do Contorno — expansão para evitar ruído nas bordas\n'
            '• Comprimento Mínimo — falhas menores são ignoradas (filtro)\n'
            '• Banda NIR — número da banda infravermelha (apenas NDVI)\n\n'
            'PARÂMETROS DE PERFORMANCE:\n'
            '• Sieve — remove grupos de pixels isolados menores que N '
            'pixels. Valores maiores = menos ruído, mais rápido (padrão: 50)\n'
            '• Resolução de Análise — reamostra o raster para esta resolução '
            'em metros antes de poligonizar. Ex: 0.20 = 20cm. '
            '0 = mantém resolução original (padrão: 0.20)\n'
            '• Tolerância de Simplificação — Douglas-Peucker nos polígonos '
            'de vegetação. Valores maiores = menos vértices (padrão: 0.1)\n\n'
            'SAÍDAS:\n'
            '• Linhas de falha com atributo comp_m (comprimento em metros)\n'
            '• Estatísticas: total, comprimento médio, maior falha, '
            'percentual\n\n'
            'Desenvolvido por CainC0de — Código livre (GPL v2+)'
        )

    def helpUrl(self):
        return 'https://github.com/CainC0de/Analise-de-falha-QGIS'