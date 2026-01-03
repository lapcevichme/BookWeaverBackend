"""
Файл для запуска BookWeaver в режиме командной строки (CLI).
Универсальный интерфейс для управления проектами.
"""
import logging
import os
import sys
from pathlib import Path

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

    def run_import_book(self):
        print("\n--- Импорт новой книги ---")
        path_str = input("Введите полный путь к файлу (.epub или .txt): ").strip().strip('"').strip("'")
        file_path = Path(path_str)

        if not file_path.exists():
            print(f"❌ Файл не найден: {file_path}")
            return

        try:
            book_name = self.app.import_book(file_path)
            print(f"✅ Книга успешно импортирована! ID проекта: '{book_name}'")
        except Exception as e:
            print(f"❌ Ошибка импорта: {e}")

    def run_full_generation(self):
        print("\n--- Полный цикл генерации (Auto-Pilot) ---")
        book_name = input("Введите название книги (имя папки): ")
        if not book_name: return

        print("Опции (Enter = выполнять этап, '-' = пропустить):")
        skip_sum = input("1. Саммари? ") == '-'
        skip_char = input("2. Персонажи? ") == '-'
        skip_scen = input("3. Сценарии? ") == '-'

        self.app.run_full_cycle(book_name, skip_sum, skip_char, skip_scen)

    def run_export_book(self):
        print("\n--- Экспорт книги в .bw архив ---")
        book_name = input("Введите название книги (имя папки): ")
        if not book_name: return

        archive_path = self.app.export_book(book_name)
        if archive_path:
            print(f"🎉 Архив готов: {archive_path}")
            print(f"📂 Папка экспорта: {archive_path.parent}")
        else:
            print("❌ Экспорт не удался (см. логи).")

    def run_character_analysis(self):
        book_name = input("Введите название книги (имя папки): ")
        if book_name: self.app.character_pipeline.run(book_name)

    def run_summary_generation(self):
        book_name = input("Введите название книги (имя папки): ")
        if book_name: self.app.summary_pipeline.run(ProjectContext(book_name))

    def run_scenario_generation(self):
        context = self._get_chapter_context_from_user()
        if context: self.app.scenario_pipeline.run(context)

    def run_tts_synthesis(self):
        context = self._get_chapter_context_from_user()
        if context: self.app.tts_pipeline.run(context)

    def run_voice_conversion(self):
        context = self._get_chapter_context_from_user()
        if context: self.app.vc_pipeline.run(context)

    def _get_chapter_context_from_user(self) -> ProjectContext | None:
        try:
            book_name = input("Книга: ")
            vol = int(input("Том: "))
            chap = int(input("Глава: "))
            ctx = ProjectContext(book_name, vol, chap)
            ctx.get_chapter_text()
            return ctx
        except Exception as e:
            print(f"Ошибка контекста: {e}")
            return None

    def main_menu(self):
        while True:
            print("\n" + "=" * 60)
            print("BOOKWEAVER CLI v2.0")
            print("=" * 60)
            print("📁 ПРОЕКТ:")
            print("  1. Импорт книги (из файла)")
            print("  2. Экспорт книги (в .bw)")
            print("-" * 20)
            print("🤖 АВТОПИЛОТ:")
            print("  3. Полный цикл генерации (Саммари -> Персы -> Сценарии)")
            print("-" * 20)
            print("🛠 РУЧНОЕ УПРАВЛЕНИЕ:")
            print("  4. Анализ персонажей (отдельно)")
            print("  5. Генерация саммари (отдельно)")
            print("  6. Генерация сценария главы (отдельно)")
            print("  7. Синтез речи (TTS) главы")
            print("  8. Voice Conversion главы")
            print("-" * 20)
            print("0. Выход")
            print("=" * 60)

            choice = input("Ваш выбор: ")

            if choice == '1': self.run_import_book()
            elif choice == '2': self.run_export_book()
            elif choice == '3': self.run_full_generation()
            elif choice == '4': self.run_character_analysis()
            elif choice == '5': self.run_summary_generation()
            elif choice == '6': self.run_scenario_generation()
            elif choice == '7': self.run_tts_synthesis()
            elif choice == '8': self.run_voice_conversion()
            elif choice == '0': break
            else: print("Неверный ввод.")

if __name__ == "__main__":
    setup_logging()
    cli_model_manager = ModelManager()
    application = Application(model_manager=cli_model_manager)

    cli = BookWeaverCLI(application)
    cli.main_menu()