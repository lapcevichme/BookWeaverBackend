import logging
from typing import Callable, Optional

from core.project_context import ProjectContext
from services.model_manager import ModelManager

logger = logging.getLogger(__name__)


class VCPipeline:
    """
    Пайплайн для наложения эмоций (Voice Conversion) на уже синтезированную речь.
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
        update_progress(0.0, stage, f"Запуск Voice Conversion для главы {context.chapter_id}")

        try:
            scenario = context.load_scenario()
            if not scenario:
                update_progress(1.0, "Ошибка", "Сценарий не найден.")
                return

            vc_service = self.model_manager.get_vc_service()
            if not vc_service.vc_model:
                update_progress(1.0, "Ошибка", "Модель VC не загружена. Прерывание.")
                return

            audio_dir = context.get_audio_output_dir()
            if not audio_dir.exists():
                update_progress(1.0, "Ошибка", "Папка с аудио не найдена. Сначала запустите TTS.")
                return

            stage = "Наложение эмоций"
            total_entries = len(scenario.entries)
            processed_count = 0

            for i, entry in enumerate(scenario.entries):
                progress = 0.1 + (0.9 * (i / total_entries))

                if not entry.emotion or entry.emotion.lower() in ["нейтрально", "neutral", "none"]:
                    continue

                audio_filename = f"{entry.id}.wav"
                source_audio_path = audio_dir / audio_filename

                if not source_audio_path.exists():
                    logger.warning(f"Файл {audio_filename} не найден. Пропуск.")
                    continue

                reference_wav_path = vc_service.find_reference_wav_for_emotion(entry.emotion)
                if not reference_wav_path:
                    logger.debug(f"Нет референса для эмоции '{entry.emotion}'. Пропуск.")
                    continue

                update_progress(progress, stage,
                                f"[{i + 1}/{total_entries}] Эмоция '{entry.emotion}' -> {audio_filename}")

                try:
                    vc_service.vc_model.voice_conversion_to_file(
                        source_wav=str(source_audio_path),
                        target_wav=str(reference_wav_path),
                        file_path=str(source_audio_path)
                    )
                    processed_count += 1
                except Exception as e:
                    logger.error(f"Ошибка VC для {audio_filename}: {e}")

            stage = "Завершение"
            update_progress(1.0, stage, f"Обработано {processed_count} файлов с эмоциями.")

        except Exception as e:
            error_msg = f"Критическая ошибка VC: {e}"
            update_progress(1.0, "Ошибка", error_msg)
            logger.error(error_msg, exc_info=True)
            raise
