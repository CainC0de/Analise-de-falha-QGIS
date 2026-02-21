
__author__ = 'CainC0de'
__date__ = '2022-09-25'
__copyright__ = '(C) 2026 CainC0de'

import logging
from qgis.core import QgsApplication
from .Falhadeplantio_provider import FalhaDePlantioProvider

logger = logging.getLogger('FalhaDePlantio')


class FalhaDePlantioPlugin:

    def __init__(self):
        self.provider = None

    def initProcessing(self):
        self.provider = FalhaDePlantioProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)
        logger.info('Plugin Falha de Plantio carregado com sucesso.')

    def initGui(self):
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            logger.info('Plugin Falha de Plantio descarregado.')
