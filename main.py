"""
Главный класс приложения, который инициализирует все необходимые сервисы и пайплайны.
Этот модуль используется `api_server.py` для создания экземпляра приложения.
"""
import logging
import os
import sys

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.model_manager import ModelManager
from pipelines.character_analysis import CharacterAnalysisPipeline
from pipelines.scenario_generation import ScenarioGenerationPipeline
from pipelines.summary_generation import SummaryGenerationPipeline
from pipelines.tts_pipeline import TTSPipeline
from pipelines.vc_pipeline import VCPipeline

logger = logging.getLogger(__name__)


class Application:
    """
    Основной класс приложения, отвечающий за инициализацию и конфигурацию
    всех необходимых компонентов, таких как пайплайны обработки данных.
    """
    def __init__(self, model_manager: ModelManager):
        """
        Инициализирует приложение с менеджером моделей.

        Args:
            model_manager: Экземпляр ModelManager для доступа к моделям.
        """
        self.model_manager = model_manager
        self._initialize_pipelines()

    def _initialize_pipelines(self):
        """
        Инициализирует все пайплайны, передавая им ModelManager.
        """
        logger.info("Конфигурирование пайплайнов с передачей ModelManager...")
        self.character_pipeline = CharacterAnalysisPipeline(self.model_manager)
        self.scenario_pipeline = ScenarioGenerationPipeline(self.model_manager)
        self.summary_pipeline = SummaryGenerationPipeline(self.model_manager)
        self.tts_pipeline = TTSPipeline(self.model_manager)
        self.vc_pipeline = VCPipeline(self.model_manager)
        logger.info("✅ Все пайплайны успешно сконфигурированы.")
