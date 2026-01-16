"""
Пайплайн для генерации визуального контента (портретов персонажей) через ComfyUI.
"""
import logging
from typing import Optional, Callable
from pathlib import Path
from core.project_context import ProjectContext
from services.comfy_service import ComfyService

logger = logging.getLogger(__name__)


class ImageGenerationPipeline:
    def __init__(self):
        self.comfy_service = ComfyService()
        logger.info("✅ Пайплайн ImageGenerationPipeline инициализирован.")

    def run(self, context: ProjectContext, progress_callback: Optional[Callable[[float, str, str], None]] = None):
        """
        Проходит по архиву персонажей и генерирует изображения для тех таймлайнов,
        где есть image_prompt, но нет reference_image_path.
        """
        def update_progress(progress: float, stage: str, message: str):
            logger.info(f"[Progress {progress:.0%}] [{stage}] {message}")
            if progress_callback:
                progress_callback(progress, stage, message)

        if not self.comfy_service.is_reachable():
            update_progress(0.0, "Ошибка", "Сервер ComfyUI недоступен (127.0.0.1:8188). Запустите ComfyUI!")
            return

        update_progress(0.0, "Старт", "Загрузка архива персонажей...")
        archive = context.load_character_archive()

        tasks = []
        for char in archive.characters:
            for chapter_key, visual_state in char.visual_timeline.items():
                if visual_state.image_prompt and not visual_state.reference_image_path:
                    tasks.append({
                        "char_id": char.id,
                        "char_name": char.name,
                        "chapter": chapter_key,
                        "prompt": visual_state.image_prompt,
                        "state_obj": visual_state
                    })

        total_tasks = len(tasks)
        if total_tasks == 0:
            update_progress(1.0, "Готово", "Нет новых задач для генерации изображений.")
            return

        update_progress(0.05, "Генерация", f"Найдено {total_tasks} задач на генерацию.")

        generated_count = 0

        for i, task in enumerate(tasks):
            char_name = task['char_name']
            prompt = task['prompt']

            progress_val = 0.05 + (i / total_tasks) * 0.9
            update_progress(progress_val, "Генерация", f"Генерация: {char_name} ({task['chapter']})...")

            try:
                # Отправка в очередь
                prompt_id = self.comfy_service.queue_prompt(prompt, width=512, height=768)

                # Ожидание
                outputs = self.comfy_service.wait_for_generation(prompt_id)

                if outputs:
                    # Сохранение
                    for node_id, node_data in outputs.items():
                        if 'images' in node_data:
                            img_info = node_data['images'][0]

                            filename = img_info['filename']
                            subfolder = img_info['subfolder']
                            folder_type = img_info['type']

                            ext = Path(filename).suffix
                            safe_name = f"{task['char_id']}_{task['chapter']}{ext}"
                            save_path = context.images_dir / safe_name

                            success = self.comfy_service.download_and_save_image(
                                filename, subfolder, folder_type, save_path
                            )

                            if success:
                                relative_path = f"images/{safe_name}"
                                task['state_obj'].reference_image_path = relative_path
                                generated_count += 1
                                archive.save(context.get_character_archive_path())
                            break
                else:
                    logger.warning(f"Не удалось получить результат для {char_name}")

            except Exception as e:
                logger.error(f"Ошибка при обработке {char_name}: {e}")

        update_progress(1.0, "Завершено", f"Сгенерировано изображений: {generated_count} из {total_tasks}")