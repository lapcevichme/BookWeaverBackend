"""
Файл для запуска BookWeaver в режиме командной строки (CLI).
"""
import logging
import os
import sys

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from main import Application
from services.model_manager import ModelManager
from core.project_context import ProjectContext
from utils.setup_logging import setup_logging

logger = logging.getLogger(__name__)


class BookWeaverCLI:
    def __init__(self, app: Application):
        self.app = app

    def run_character_analysis(self):
        """Запускает пайплайн анализа персонажей."""
        book_name = input("Введите название книги (имя папки): ")
        if not book_name:
            print("Название книги не может быть пустым.")
            return
        self.app.character_pipeline.run(book_name)

    def run_summary_generation(self):
        """Запускает пайплайн генерации пересказов."""
        book_name = input("Введите название книги (имя папки): ")
        if not book_name:
            print("Название книги не может быть пустым.")
            return
        context = ProjectContext(book_name)
        self.app.summary_pipeline.run(context)

    def run_scenario_generation(self):
        """Запускает пайплайн генерации сценария для главы."""
        context = self._get_chapter_context_from_user()
        if context:
            self.app.scenario_pipeline.run(context)

    def run_tts_synthesis(self):
        """Запускает пайплайн синтеза речи для главы."""
        print("\n--- Запуск синтеза речи для главы ---")
        context = self._get_chapter_context_from_user()
        if context:
            self.app.tts_pipeline.run(context)

    def run_voice_conversion(self):
        """Запускает пайплайн применения эмоциональной окраски."""
        print("\n--- Запуск применения эмоций (Voice Conversion) ---")
        context = self._get_chapter_context_from_user()
        if context:
            self.app.vc_pipeline.run(context)

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
            context.get_chapter_text()  # Проверка существования файла
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

            if choice == '1':
                self.run_character_analysis()
            elif choice == '2':
                self.run_summary_generation()
            elif choice == '3':
                self.run_scenario_generation()
            elif choice == '4':
                self.run_tts_synthesis()
            elif choice == '5':
                self.run_voice_conversion()
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
    print("ЗАПУСК В РЕЖИМЕ CLI")
    try:
        setup_logging()
        cli_model_manager = ModelManager()
        application = Application(model_manager=cli_model_manager)
        
        # Запуск CLI
        cli_app = BookWeaverCLI(app=application)
        cli_app.main_menu()

    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ: {e}")
        import traceback

        traceback.print_exc()
        input("\nНажмите Enter для выхода...")
