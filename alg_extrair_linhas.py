from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingMultiStepFeedback,
                       QgsProcessingParameterRasterLayer,
                       QgsProcessingParameterVectorLayer,
                       QgsProcessingParameterFeatureSink,
                       QgsProject)
import processing

class ExtracaoLinhasAlgorithm(QgsProcessingAlgorithm):

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterRasterLayer('input_raster', '1. Imagem RGB (Drone)', defaultValue=None))
        self.addParameter(QgsProcessingParameterVectorLayer('area_contorno', '2. Contorno do Talhão', types=[QgsProcessing.TypeVectorPolygon], defaultValue=None, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink('LinhasExtraidas', 'Linhas de Plantio (Centro da Cana)', type=QgsProcessing.TypeVectorLine, createByDefault=True, defaultValue=None))

    def processAlgorithm(self, parameters, context, model_feedback):
        feedback = QgsProcessingMultiStepFeedback(5, model_feedback)
        results = {}
        
        context.setTransformContext(QgsProject.instance().transformContext())
        project_crs = QgsProject.instance().crs().authid()

        # 1. RECORTE E REDUÇÃO DE RESOLUÇÃO (Otimizado para 0.4m)
        out_recorte = processing.run('gdal:cliprasterbymasklayer', {
            'INPUT': parameters['input_raster'],
            'MASK': parameters['area_contorno'],
            'TARGET_RESOLUTION': 0.4,
            'SOURCE_CRS': project_crs, 'TARGET_CRS': project_crs,
            'NODATA': 0, 'CROP_TO_CUTLINE': True,
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }, context=context, feedback=feedback)
        feedback.setCurrentStep(1)

        # 2. ÍNDICE GLI BINÁRIO
        # Fórmula: $$GLI = \frac{2.0 \cdot G - R - B}{2.0 \cdot G + R + B + 0.0001} > 0.06$$
        out_binario = processing.run('gdal:rastercalculator', {
            'INPUT_A': out_recorte['OUTPUT'], 'BAND_A': 2,
            'INPUT_B': out_recorte['OUTPUT'], 'BAND_B': 1,
            'INPUT_C': out_recorte['OUTPUT'], 'BAND_C': 3,
            'FORMULA': '((2.0*A-B-C)/(2.0*A+B+C+0.0001)) > 0.06', 
            'RTYPE': 1, # Int16 (CELL)
            'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
        }, context=context, feedback=feedback)
        feedback.setCurrentStep(2)

        # 3. ESQUELETIZAÇÃO (r.thin)
        out_thin = processing.run('grass7:r.thin', {
            'input': out_binario['OUTPUT'], 'iterations': 100,
            'output': QgsProcessing.TEMPORARY_OUTPUT
        }, context=context, feedback=feedback)
        feedback.setCurrentStep(3)

        # 4. VETORIZAÇÃO (r.to.vect)
        out_vetor = processing.run('grass7:r.to.vect', {
            'input': out_thin['output'], 'type': 0,
            'output': QgsProcessing.TEMPORARY_OUTPUT
        }, context=context, feedback=feedback)
        feedback.setCurrentStep(4)

        # 5. SIMPLIFICAÇÃO FINAL
        # Verificação para evitar o erro de 'arquivo não encontrado'
        if out_vetor['output']:
            processing.run('native:simplifygeometries', {
                'INPUT': out_vetor['output'], 'METHOD': 0, 'TOLERANCE': 0.5,
                'OUTPUT': parameters['LinhasExtraidas']
            }, context=context, feedback=feedback)
        
        return {'LinhasExtraidas': parameters['LinhasExtraidas']}

    def name(self): return 'extrair_linhas_otimizado'
    def displayName(self): return '1. Extrair Linhas de Plantio (Otimizado)'
    def group(self): return 'Automação'
    def groupId(self): return 'Automação'
    def createInstance(self): return ExtracaoLinhasAlgorithm()