import logging
from typing import Callable, Optional

from core.project_context import ProjectContext
from services.model_manager import ModelManager

logger = logging.getLogger(__name__)

# FIXME!!!!!!!!!!!!!!!!!!!!!!!!! ЭТА ШТУКА ПЕРЕСТАЛА РАБОТАТЬ ТАК КАК КОЕ-КАКОЙ ВЕЛИКИЙ ЧЕЛОВЕК НА HUGGING FACE ЗАРУИНИЛ СВОЙ РЕПОЗИТОРИЙ

class VCPipeline:
    """
    Пайплайн для применения эмоциональной окраски (Voice Conversion)
    к аудиофайлам озвученной главы.
    """

    def __init__(self, model_manager: ModelManager):
        self.model_manager = model_manager
        logger.info("✅ Пайплайн VCPipeline (Voice Conversion) инициализирован.")

    def run(self, context: ProjectContext, progress_callback: Optional[Callable[[float, str, str], None]] = None):
        """
        Выполняет процесс конвертации голоса для указанной главы.
        """

        def update_progress(progress: float, stage: str, message: str):
            logger.info(f"[Progress {progress:.0%}] [{stage}] {message}")
            if progress_callback:
                progress_callback(progress, stage, message)

        stage = "Подготовка"
        update_progress(0.0, stage, f"Запуск эмоциональной окраски (VC) для главы {context.chapter_id}")

        try:
            # 1: Загрузка сценария
            update_progress(0.05, stage, "Загрузка файла сценария...")
            scenario = context.load_scenario()
            if not scenario:
                update_progress(1.0, "Ошибка", f"Файл сценария не найден для главы {context.chapter_id}. Прерывание.")
                return
            logger.info("Сценарий успешно загружен.")

            vc_service = self.model_manager.get_vc_service()

            vc_model = vc_service.vc_model
            if not vc_model:
                update_progress(1.0, "Ошибка", "Не удалось загрузить модель Voice Conversion. Прерывание.")
                return

            # 2: Обработка реплик
            stage = "Обработка реплик"
            update_progress(0.1, stage, "Начало применения эмоциональной окраски...")
            total_entries = len(scenario.entries)
            processed_count = 0

            for i, entry in enumerate(scenario.entries):
                progress = 0.1 + (0.9 * (i / total_entries))
                entry_id = i + 1

                logger.info(f"Обработка реплики {entry_id}/{total_entries}...")

                # Пропускаем реплики без эмоций или с нейтральной эмоцией
                if not entry.emotion or entry.emotion.lower() in ["нейтрально", "neutral", "none"]:
                    logger.debug(f"Реплика {entry_id} имеет нейтральную эмоцию. Пропуск.")
                    continue

                # Ищем исходный аудиофайл, созданный TTS пайплайном
                audio_filename = f"entry_{entry_id}.wav"
                source_audio_path = context.get_audio_output_dir() / audio_filename

                if not source_audio_path.exists():
                    logger.warning(f"Исходный аудиофайл не найден: {audio_filename}. Пропуск.")
                    continue

                # Ищем референсный аудиофайл для нужной эмоции
                reference_wav_path = vc_service.find_reference_wav_for_emotion(entry.emotion)

                if not reference_wav_path:
                    logger.warning(f"Не найден референс для эмоции '{entry.emotion}'. Пропуск реплики {entry_id}.")
                    continue

                update_progress(progress, stage,
                                f"Реплика {entry_id}/{total_entries}: применение эмоции '{entry.emotion}'...")
                logger.info(f"Применение стиля из: {reference_wav_path.name}")

                try:
                    # Выполняем конвертацию и перезаписываем исходный файл
                    vc_model.voice_conversion_to_file(
                        source_wav=str(source_audio_path),
                        target_wav=str(reference_wav_path),
                        file_path=str(source_audio_path)
                    )
                    logger.info(f"Эмоция успешно применена к {audio_filename}")
                    processed_count += 1
                except Exception as e:
                    error_msg = f"Ошибка во время конвертации голоса для {audio_filename}: {e}"
                    logger.error(error_msg, exc_info=True)

            # 3: Завершение
            stage = "Завершение"
            final_message = f"Обработка завершена. Эмоции применены к {processed_count} аудиофайлам."
            update_progress(1.0, stage, final_message)

        except Exception as e:
            error_msg = f"Критическая ошибка в пайплайне Voice Conversion: {e}"
            update_progress(1.0, "Ошибка", error_msg)
            logger.error(error_msg, exc_info=True)
            raise
