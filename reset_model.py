import shutil
import os
from pathlib import Path
from TTS.utils.manage import ModelManager

import config


def reset_vc_model():
    print("🧹 Очистка кэша поврежденной модели...")

    model_name = config.VC_MODEL_NAME

    manager = ModelManager()

    try:
        model_path, _, _ = manager.download_model(model_name)
        model_dir = Path(model_path).parent

        print(f"📍 Найдена директория модели: {model_dir}")

        if model_dir.exists():
            print(f"🗑️ Удаление {model_dir}...")
            shutil.rmtree(model_dir)
            print("✅ Кэш очищен. Теперь запустите debug_vc.py снова, чтобы скачать модель заново.")
        else:
            print("⚠️ Папка не найдена. Возможно, она уже удалена.")

    except Exception as e:
        # Если стандартный метод не сработал, пробуем "грубую силу" - стандартные пути
        print(f"⚠️ Не удалось определить путь через API ({e}). Проверяем стандартные пути...")

        home = Path.home()
        possible_paths = [
            home / ".local/share/tts",
            home / "AppData/Local/tts"
        ]

        found = False
        for base_path in possible_paths:
            target = base_path / "voice_conversion_models--multilingual--vctk--freevc24"
            if target.exists():
                print(f"🗑️ Удаление {target}...")
                shutil.rmtree(target)
                found = True

        if found:
            print("✅ Кэш очищен.")
        else:
            print("❌ Не удалось найти папку с моделью. Попробуйте удалить её вручную.")
            print(f"Ищите папку с названием 'freevc24' внутри {possible_paths}")


if __name__ == "__main__":
    reset_vc_model()