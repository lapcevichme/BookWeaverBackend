import json
import re
from pathlib import Path
from typing import List


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


import re
from typing import List

def smart_split_text(text: str, chunk_size: int = 10000, overlap: int = 300) -> List[str]:
    """
    Разбивает текст на чанки, стараясь не разрывать абзацы.

    Args:
        text: Исходный текст.
        chunk_size: Максимальный размер чанка (рекомендуется 6000-12000 для корректной работы с JSON).
        overlap: Размер перекрытия из конца предыдущего чанка для сохранения контекста.
    """
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    # Пробуем разбиение по абзацам (двойной перенос), иначе по строкам
    paragraphs = re.split(r'\n\s*\n', text)
    if not paragraphs:
        paragraphs = text.split('\n')

    chunks = []
    current_chunk = []
    current_length = 0

    for para in paragraphs:
        para_len = len(para)

        if para_len > chunk_size:
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_length = 0

            # Разбиваем сверхбольшой параграф на части
            sub_chunks = [para[i:i + chunk_size] for i in range(0, len(para), chunk_size)]
            chunks.extend(sub_chunks)
            continue

        if current_length + para_len > chunk_size and current_chunk:
            full_chunk_text = "\n\n".join(current_chunk)
            chunks.append(full_chunk_text)

            # Формирование перекрытия для сохранения контекста LLM
            overlap_text = ""
            if overlap > 0 and len(full_chunk_text) > overlap:
                overlap_text = f"...{full_chunk_text[-overlap:]}\n--- (контекст) ---\n"

            current_chunk = [overlap_text + para]
            current_length = len(overlap_text) + para_len
        else:
            current_chunk.append(para)
            current_length += para_len + 2

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks