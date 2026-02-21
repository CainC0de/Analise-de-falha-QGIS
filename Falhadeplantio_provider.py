
__author__ = 'CainC0de'
__date__ = '2022-09-25'
__copyright__ = '(C) 2026 CainC0de'

import os
from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon
from .Falhadeplantio_algorithm import FalhaDePlantioAlgorithm


class FalhaDePlantioProvider(QgsProcessingProvider):

    def __init__(self):
        super().__init__()

    def unload(self):
        pass

    def loadAlgorithms(self):
        self.addAlgorithm(FalhaDePlantioAlgorithm())

    def id(self):
        return 'falhadeplantio'

    def name(self):
        return self.tr('Falha de Plantio (Cana-de-açúcar)')

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), 'canaicone.png')
        return QIcon(icon_path)

    def longName(self):
        return self.tr('Falha de Plantio — Análise de cana-de-açúcar (v2.0)')
