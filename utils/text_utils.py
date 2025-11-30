import json
import re
from pathlib import Path

# TODO: рассмотреть, насколько сейчас нужен этот метод. Раньше были проблемы с TXT, но при переходе на epub и парсинг с моей стороны это, похоже, бесполезно
def cleanup_filename(name: str) -> str:
    """
    Очищает строку, чтобы ее можно было безопасно использовать в качестве имени файла.
    - Удаляет недопустимые символы.
    - Заменяет пробелы на подчеркивания.
    - Приводит к нижнему регистру.
    """
    if not name:
        return "unknown"
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip('_')
    name = name.lower()
    return name if name else "unknown"


def load_pronunciation_dictionary(path: Path) -> dict:
    """Загружает словарь произношений из JSON файла."""
    if not path.exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


# TODO: при переходе на cosy voice посмотреть где возникают артифакты и пофиксить некоторые из них
def preprocess_text_for_tts(text: str, dictionary: dict) -> str:
    """
    Полный конвейер предобработки текста для TTS:
    1. Применяет словарь произношений.
    2. Очищает от нежелательных символов.
    """
    for word, pronunciation in dictionary.items():
        text = re.sub(r'\b' + re.escape(word) + r'\b', pronunciation, text, flags=re.IGNORECASE)

    text = text.replace('«', '').replace('»', '').replace('"', '')
    text = text.replace('!.', '!').replace('.!', '!')
    text = text.replace('?.', '?').replace('.?', '?')
    text = text.strip()

    return text
