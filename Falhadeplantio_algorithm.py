
__author__ = 'CainC0de'
__date__ = '2022-09-25'
__copyright__ = '(C) 2026 CainC0de'

import logging
import os
import tempfile
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
    QgsRasterLayer,
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

        raster_layer = self.parameterAsRasterLayer(parameters, self.INPUT_RASTER, context)
        raster_path = raster_layer.source()

        logger.info(
            'Análise de falha: índice=%s, threshold=%.3f, sieve=%d, '
            'resolução=%.3f, simplificação=%.3f',
            self.INDEX_CHOICES[indice], threshold, sieve_size,
            resolucao, simplify_tol)

        tmp_dir = tempfile.mkdtemp(prefix='falha_plantio_')

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
            clipped_path = os.path.join(tmp_dir, 'clipped.tif')
            self._clip_raster_by_mask(
                raster_path,
                outputs['BufferContorno']['OUTPUT'],
                clipped_path,
                context, feedback)
            outputs['RasterRecortado'] = {'OUTPUT': clipped_path}
        except Exception as e:
            feedback.reportError(f'Erro ao recortar raster: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(f'Passo {step}/{self.TOTAL_STEPS}: Calculando índice de vegetação...')
        try:
            indice_path = os.path.join(tmp_dir, 'indice.tif')
            self._calc_vegetation_index(
                clipped_path, indice_path, indice, banda_nir, context, feedback)
            outputs['CalculoIndice'] = {'OUTPUT': indice_path}
        except Exception as e:
            feedback.reportError(f'Erro no índice de vegetação: {e}', fatalError=True)
            return {}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(
            f'Passo {step}/{self.TOTAL_STEPS}: Máscara binária '
            f'(threshold={threshold})...')
        try:
            mask_path = os.path.join(tmp_dir, 'mask.tif')
            self._calc_binary_mask(indice_path, mask_path, threshold, context, feedback)
            outputs['MascaraBinaria'] = {'OUTPUT': mask_path}
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
                sieved_path = os.path.join(tmp_dir, 'sieved.tif')
                self._apply_sieve(mask_path, sieved_path, sieve_size, context, feedback)
                outputs['SieveFiltrado'] = {'OUTPUT': sieved_path}
            except Exception as e:
                feedback.reportError(f'Erro no sieve filter: {e}', fatalError=True)
                return {}
        else:
            feedback.pushInfo(
                f'Passo {step}/{self.TOTAL_STEPS}: Sieve filter desabilitado (tamanho=0).')
            outputs['SieveFiltrado'] = {'OUTPUT': mask_path}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        current_raster = outputs['SieveFiltrado']['OUTPUT']
        if resolucao > 0:
            feedback.pushInfo(
                f'Passo {step}/{self.TOTAL_STEPS}: Reamostrando para '
                f'{resolucao}m de resolução...')
            try:
                resampled_path = os.path.join(tmp_dir, 'resampled.tif')
                self._resample_raster(current_raster, resampled_path, resolucao, context, feedback)
                outputs['Reamostrado'] = {'OUTPUT': resampled_path}
            except Exception as e:
                feedback.reportError(f'Erro na reamostragem: {e}', fatalError=True)
                return {}
        else:
            feedback.pushInfo(
                f'Passo {step}/{self.TOTAL_STEPS}: Reamostragem desabilitada (resolução=0).')
            outputs['Reamostrado'] = {'OUTPUT': current_raster}
        feedback.setCurrentStep(step)
        if feedback.isCanceled():
            return {}

        step += 1
        feedback.pushInfo(
            f'Passo {step}/{self.TOTAL_STEPS}: Convertendo raster em polígonos...')
        try:
            poly_path = os.path.join(tmp_dir, 'polygons.gpkg')
            self._polygonize_raster(outputs['Reamostrado']['OUTPUT'], poly_path, context, feedback)
            outputs['Vetorizar'] = {'OUTPUT': poly_path}
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
                'INPUT': poly_path,
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
                'OVERLAY': outputs['BufferContorno']['OUTPUT'],
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT,
            }
            outputs['LinhasNoTalhao'] = processing.run(
                'native:clip', alg_params,
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

    def _clip_raster_by_mask(self, raster_path, mask_layer_ref, output_path, context, feedback):
        alg_params = {
            'INPUT': raster_path,
            'MASK': mask_layer_ref,
            'CROP_TO_CUTLINE': True,
            'KEEP_RESOLUTION': True,
            'NODATA': None,
            'OUTPUT': output_path,
        }
        try:
            processing.run('gdal:cliprasterbymasklayer', alg_params,
                           context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            raise RuntimeError(f'gdal:cliprasterbymasklayer falhou: {e}')
            
        if not os.path.exists(output_path):
            raise RuntimeError('gdal:cliprasterbymasklayer não gerou o output esperado')
            
        feedback.pushInfo(f'Raster recortado salvo em: {output_path}')

    def _calc_vegetation_index(self, raster_path, output_path, indice, banda_nir, context, feedback):
        if indice == 0:
            feedback.pushInfo('Calculando GLI (RGB)...')
            # GLI = (2*G - R - B) / (2*G + R + B)
            # Bandas usuais RGB: 1=Red, 2=Green, 3=Blue
            expression = '(2.0 * "A@2" - "A@1" - "A@3") / (2.0 * "A@2" + "A@1" + "A@3" + 0.0001)'
        else:
            feedback.pushInfo(f'Calculando NDVI (NIR=banda {banda_nir})...')
            # NDVI = (NIR - R) / (NIR + R)
            expression = f'("A@{banda_nir}" - "A@1") / ("A@{banda_nir}" + "A@1" + 0.0001)'

        alg_params = {
            'EXPRESSION': expression,
            'LAYERS': [raster_path],
            'CELLSIZE': 0,
            'EXTENT': None,
            'CRS': None,
            'OUTPUT': output_path,
        }
        try:
            processing.run('native:rastercalculator', alg_params,
                           context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            raise RuntimeError(f'native:rastercalculator (vegetation index) falhou: {e}')

        if not os.path.exists(output_path):
            raise RuntimeError('Falha ao gerar o índice de vegetação via rastercalculator')

    def _calc_binary_mask(self, raster_path, output_path, threshold, context, feedback):
        # Limiarização: Retorna 1 se > threshold, senão 0
        expression = f'("A@1" > {threshold}) * 1'
        
        alg_params = {
            'EXPRESSION': expression,
            'LAYERS': [raster_path],
            'CELLSIZE': 0,
            'EXTENT': None,
            'CRS': None,
            'OUTPUT': output_path,
        }
        try:
            processing.run('native:rastercalculator', alg_params,
                           context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            raise RuntimeError(f'native:rastercalculator (binary mask) falhou: {e}')

        if not os.path.exists(output_path):
            raise RuntimeError('Falha ao gerar a máscara binária via rastercalculator')

    def _apply_sieve(self, raster_path, output_path, threshold, context, feedback):
        alg_params = {
            'INPUT': raster_path,
            'THRESHOLD': threshold,
            'EIGHT_CONNECTEDNESS': False,
            'NO_MASK': False,
            'MASK_LAYER': None,
            'EXTRA': '',
            'OUTPUT': output_path,
        }
        try:
            processing.run('gdal:sieve', alg_params,
                           context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            raise RuntimeError(f'gdal:sieve falhou: {e}')

        if not os.path.exists(output_path):
            raise RuntimeError('Falha ao aplicar o filtro sieve')
            
        feedback.pushInfo(f'Sieve filter aplicado (threshold={threshold})')

    def _resample_raster(self, raster_path, output_path, target_res, context, feedback):
        alg_params = {
            'INPUT': raster_path,
            'SOURCE_CRS': None,
            'TARGET_CRS': None,
            'RESAMPLING': 0, # Nearest Neighbour
            'NODATA': None,
            'TARGET_RESOLUTION': target_res,
            'OPTIONS': '',
            'DATA_TYPE': 0, # Use Input Layer Data Type
            'TARGET_EXTENT': None,
            'TARGET_EXTENT_CRS': None,
            'MULTITHREADING': False,
            'EXTRA': '',
            'OUTPUT': output_path,
        }
        try:
            processing.run('gdal:warpresolution', alg_params,
                           context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            raise RuntimeError(f'gdal:warpresolution falhou na reamostragem: {e}')

        if not os.path.exists(output_path):
            raise RuntimeError('Falha ao reamostrar o raster')
            
        feedback.pushInfo(f'Reamostrado para {target_res}m')

    def _polygonize_raster(self, raster_path, output_path, context, feedback):
        alg_params = {
            'INPUT': raster_path,
            'BAND': 1,
            'FIELD': 'DN',
            'EIGHT_CONNECTEDNESS': False,
            'EXTRA': '',
            'OUTPUT': output_path,
        }
        try:
            processing.run('gdal:polygonize', alg_params,
                           context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as e:
            raise RuntimeError(f'gdal:polygonize falhou: {e}')

        if not os.path.exists(output_path):
            raise RuntimeError('Falha ao poligonizar o raster')
            
        feedback.pushInfo(f'Poligonização concluída: {output_path}')

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