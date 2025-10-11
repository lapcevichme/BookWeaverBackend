import re
import json
from pathlib import Path

def cleanup_filename(name: str) -> str:
    """
    Очищает строку, чтобы ее можно было безопасно использовать в качестве имени файла.
    - Удаляет недопустимые символы.
    - Заменяет пробелы на подчеркивания.
    - Приводит к нижнему регистру.
    """
    if not name:
        return "unknown"
    # Удаляем символы, недопустимые в большинстве файловых систем
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    # Заменяем пробелы и несколько подчеркиваний на одно
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'_+', '_', name)
    # Убираем подчеркивания в начале/конце
    name = name.strip('_')
    # Приводим к нижнему регистру для консистентности
    name = name.lower()
    # Если после всех манипуляций строка оказалась пустой, возвращаем "unknown"
    return name if name else "unknown"


def load_pronunciation_dictionary(path: Path) -> dict:
    """Загружает словарь произношений из JSON файла."""
    if not path.exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def preprocess_text_for_tts(text: str, dictionary: dict) -> str:
    """
    Полный конвейер предобработки текста для TTS:
    1. Применяет словарь произношений.
    2. Очищает от нежелательных символов.
    ИСПРАВЛЕНО: Разделение на предложения теперь выполняется самой TTS-моделью,
    поэтому эта функция возвращает единую очищенную строку.
    """
    # 1. Применяем словарь произношений
    for word, pronunciation in dictionary.items():
        # Используем word boundaries (\b) для замены только целых слов
        text = re.sub(r'\b' + re.escape(word) + r'\b', pronunciation, text, flags=re.IGNORECASE)

    # 2. Базовая очистка и нормализация текста
    # Удаляем кавычки-ёлочки и стандартные кавычки
    text = text.replace('«', '').replace('»', '').replace('"', '')
    # Объединяем "!" и "." в один знак.
    text = text.replace('!.', '!').replace('.!', '!')
    text = text.replace('?.', '?').replace('.?', '?')
    # Убираем лишние пробелы в начале и конце
    text = text.strip()

    # 3. Разделение на предложения УДАЛЕНО.
    return text
