"""
Главный исполнительный файл проекта BookWeaver.

Этот файл инициализирует все необходимые сервисы и пайплайны,
а также предоставляет пользователю текстовый интерфейс (CLI)
для запуска различных этапов обработки книги.
"""

import os
import sys

from pipelines.vc_pipeline import VCPipeline

# Добавляем корневую директорию проекта в sys.path
# Это позволяет запускать main.py из любой вложенной папки
# и гарантирует, что все относительные импорты будут работать корректно.
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Импорты наших модулей
import config
from core.project_context import ProjectContext
from services.llm_service import LLMService
from services.tts_service import TTSService
from services.vc_service import VCService
from pipelines.character_analysis import CharacterAnalysisPipeline
from pipelines.scenario_generation import ScenarioGenerationPipeline
from pipelines.summary_generation import SummaryGenerationPipeline
from pipelines.tts_pipeline import TTSPipeline


class Application:
    """
    Главный класс приложения, который инкапсулирует всю логику
    инициализации и запуска.
    """

    def __init__(self):
        self._initialize_services()
        self._initialize_pipelines()

    def _initialize_services(self):
        """Инициализирует все сервисы, которые будут использоваться пайплайнами."""
        print("Инициализация сервисов...")
        # Создаем два экземпляра LLM-сервиса для разных задач
        self.fast_llm = LLMService(config.FAST_MODEL_NAME, temperature=0.3)
        self.powerful_llm = LLMService(config.POWERFUL_MODEL_NAME, temperature=0.6)
        # Инициализируем сервисы для TTS и VC
        self.tts_service = TTSService()
        self.vc_service = VCService()
        print("✅ Сервисы успешно инициализированы.")

    def _initialize_pipelines(self):
        """Инициализирует все пайплайны, передавая им необходимые сервисы."""
        print("Инициализация пайплайнов...")
        self.character_pipeline = CharacterAnalysisPipeline(self.fast_llm, self.powerful_llm)
        self.scenario_pipeline = ScenarioGenerationPipeline(self.fast_llm, self.powerful_llm)
        self.summary_pipeline = SummaryGenerationPipeline(self.fast_llm)
        # ДОБАВЛЕНО: Инициализация TTS пайплайна
        self.tts_pipeline = TTSPipeline(self.tts_service)
        self.vc_pipeline = VCPipeline(self.vc_service)
        print("✅ Пайплайны успешно инициализированы.")


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

    # ДОБАВЛЕНО: Метод для запуска озвучки
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
        # ИСПРАВЛЕНО: Инициализируем context как None перед блоком try
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
            # Проверим, существует ли файл главы, чтобы сразу выдать ошибку
            context.get_chapter_text()
            return context

        except FileNotFoundError:
            # Теперь 'context' здесь гарантированно существует (хоть и может быть None)
            # Но в данном случае он точно будет объектом, так как ошибка возникает после его создания.
            print(f"❌ ОШИБКА: Файл главы не найден по пути: {context.chapter_file}")
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
            print("ГЛАВНОЕ МЕНЮ BOOKWEAVER (v2.1 API-Ready)")
            print("1. Анализ персонажей по всей книге")
            print("2. Генерация пересказов для всех глав")
            print("3. Генерация сценария для главы")
            print("4. Синтез речи по сценарию (TTS)")
            print("5. Применить эмоциональную окраску (Voice Conversion)")
            print("0. Выход")
            print("=" * 50)

            choice = input("Ваш выбор: ")

            if choice == '1':
                self.run_character_analysis()
            elif choice == '2':
                self.run_summary_generation()
            elif choice == '3':
                self.run_scenario_generation()
            # ИСПРАВЛЕНО: Раскомментирован и подключен вызов TTS
            elif choice == '4':
                self.run_tts_synthesis()
            elif choice == '5':
                self.run_voice_conversion()
            elif choice == '0':
                print("Выход из программы.")
                break
            else:
                print("Неверный ввод. Пожалуйста, выберите один из предложенных вариантов.")


if __name__ == "__main__":
    try:
        app = Application()
        app.main_menu()
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        import traceback
        traceback.print_exc()
        input("\nНажмите Enter для выхода...")

