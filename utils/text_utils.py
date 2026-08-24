import json
import re
from pathlib import Path
from typing import List


def clean_raw_text(content: str) -> str:
    """
    Очищает сырой текст книги от типографического мусора:
    - Удаляет неразрывные пробелы (\u00A0) и нульширинные пробелы (\u200b).
    - Обрезает пробелы в конце каждой строки.
    - Схлопывает 3+ переноса строк в двойной перенос.
    """
    if not content:
        return ""
    content = content.replace('\u00A0', ' ').replace('\u200b', '')
    lines = [line.rstrip() for line in content.splitlines()]
    content = '\n'.join(lines)
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip() + '\n'


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
    """
    Загружает словарь произношений из JSON файла.
    """
    if not path.exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def preprocess_text_for_tts(text: str, dictionary: dict) -> str:
    """
    Полный конвейер предобработки текста для TTS:
    1. Применяет словарь произношений.
    2. Очищает от нежелательных символов и пунктуационных дублей.
    """
    for word, pronunciation in dictionary.items():
        text = re.sub(r'\b' + re.escape(word) + r'\b', pronunciation, text, flags=re.IGNORECASE)

    text = text.replace('«', '').replace('»', '').replace('"', '')
    text = text.replace('!.', '!').replace('.!', '!')
    text = text.replace('?.', '?').replace('.?', '?')
    text = text.strip()

    return text


def smart_split_text(text: str, chunk_size: int = 10000, overlap: int = 300) -> List[str]:
    """
    Разбивает текст на чанки, стараясь не разрывать абзацы.

    Args:
        text: Исходный текст.
        chunk_size: Максимальный размер чанка.
        overlap: Размер перекрытия из конца предыдущего чанка для сохранения контекста.
    """
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

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

            sub_chunks = [para[i:i + chunk_size] for i in range(0, len(para), chunk_size)]
            chunks.extend(sub_chunks)
            continue

        if current_length + para_len > chunk_size and current_chunk:
            full_chunk_text = "\n\n".join(current_chunk)
            chunks.append(full_chunk_text)

            overlap_text = ""
            if 0 < overlap < len(full_chunk_text):
                overlap_text = f"...{full_chunk_text[-overlap:]}\n--- (контекст) ---\n"

            current_chunk = [overlap_text + para]
            current_length = len(overlap_text) + para_len
        else:
            current_chunk.append(para)
            current_length += para_len + 2

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks