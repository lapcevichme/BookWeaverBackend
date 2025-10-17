"""
Главный исполнительный файл проекта BookWeaver.

Этот файл инициализирует все необходимые сервисы и пайплайны,
а также предоставляет пользователю текстовый интерфейс (CLI)
для запуска различных этапов обработки книги.
"""
import os
import sys
import logging

from utils.setup_logging import setup_logging

# Добавляем корневую директорию проекта в sys.path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- ИЗМЕНЕНИЕ: Импортируем ModelManager и пайплайны ---
from services.model_manager import ModelManager
from pipelines.character_analysis import CharacterAnalysisPipeline
from pipelines.scenario_generation import ScenarioGenerationPipeline
from pipelines.summary_generation import SummaryGenerationPipeline
from pipelines.tts_pipeline import TTSPipeline
from pipelines.vc_pipeline import VCPipeline
from core.project_context import ProjectContext

logger = logging.getLogger(__name__)

class Application:
    """
    Главный класс приложения, который теперь не создает сервисы,
    а получает готовый менеджер и передает его пайплайнам.
    """
    def __init__(self, model_manager: ModelManager):
        """
        Конструктор теперь принимает ModelManager.
        Это делает инициализацию класса мгновенной.
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


    # --- Методы для CLI-режима остаются для отладки ---

    def run_character_analysis(self):
        """Запускает пайплайн анализа персонажей."""
        book_name = input("Введите название книги (имя папки): ")
        if not book_name:
            print("Название книги не может быть пустым.")
            return
        self.character_pipeline.run(book_name)

    def run_summary_generation(self):
        """Запускает пайплайн генерации пересказов."""
        book_name = input("Введите название книги (имя папки): ")
        if not book_name:
            print("Название книги не может быть пустым.")
            return
        context = ProjectContext(book_name)
        self.summary_pipeline.run(context)

    def run_scenario_generation(self):
        """Запускает пайплайн генерации сценария для главы."""
        context = self._get_chapter_context_from_user()
        if context:
            self.scenario_pipeline.run(context)

    def run_tts_synthesis(self):
        """Запускает пайплайн синтеза речи для главы."""
        print("\n--- Запуск синтеза речи для главы ---")
        context = self._get_chapter_context_from_user()
        if context:
            self.tts_pipeline.run(context)

    def run_voice_conversion(self):
        """Запускает пайплайн применения эмоциональной окраски."""
        print("\n--- Запуск применения эмоций (Voice Conversion) ---")
        context = self._get_chapter_context_from_user()
        if context:
            self.vc_pipeline.run(context)

    def _get_chapter_context_from_user(self) -> ProjectContext | None:
        """Запрашивает у пользователя данные и создает контекст для главы."""
        context = None
        try:
            book_name = input("Введите название книги (имя папки): ")
            volume_num_str = input("Введите номер тома: ")
            chapter_num_str = input("Введите номер главы: ")

            if not all([book_name, volume_num_str, chapter_num_str]):
                print("❌ ОШИБКА: Все поля должны быть заполнены.")
                return None

            volume_num = int(volume_num_str)
            chapter_num = int(chapter_num_str)

            context = ProjectContext(book_name, volume_num, chapter_num)
            context.get_chapter_text() # Проверка существования файла
            return context

        except FileNotFoundError:
            print(f"❌ ОШИБКА: Файл главы не найден по пути: {context.chapter_file if context else 'N/A'}")
            return None
        except ValueError:
            print("❌ ОШИБКА: Номер тома и главы должны быть целыми числами.")
            return None
        except Exception as e:
            print(f"Произошла ошибка: {e}")
            return None

    def main_menu(self):
        """Отображает главное меню и управляет выбором пользователя."""
        while True:
            print("\n" + "=" * 50)
            print("ГЛАВНОЕ МЕНЮ BOOKWEAVER (CLI-отладчик)")
            print("1. Анализ персонажей по всей книге")
            print("2. Генерация пересказов для всех глав")
            print("3. Генерация сценария для главы")
            print("4. Синтез речи по сценарию (TTS)")
            print("5. Применить эмоциональную окраску (Voice Conversion)")
            print("0. Выход")
            print("=" * 50)

            choice = input("Ваш выбор: ")

            if choice == '1': self.run_character_analysis()
            elif choice == '2': self.run_summary_generation()
            elif choice == '3': self.run_scenario_generation()
            elif choice == '4': self.run_tts_synthesis()
            elif choice == '5': self.run_voice_conversion()
            elif choice == '0':
                print("Выход из программы.")
                break
            else:
                print("Неверный ввод.")


if __name__ == "__main__":
    """
    Этот блок запускает приложение в режиме командной строки (CLI) для отладки.
    Он НЕ используется, когда приложение запускается через api_server.py.
    """
    print("ЗАПУСК В РЕЖИМЕ ОТЛАДКИ (CLI)")
    try:
        setup_logging()
        # Для CLI-режима мы создаем свой собственный экземпляр ModelManager
        cli_model_manager = ModelManager()
        app = Application(model_manager=cli_model_manager)
        app.main_menu()
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        import traceback
        traceback.print_exc()
        input("\nНажмите Enter для выхода...")
