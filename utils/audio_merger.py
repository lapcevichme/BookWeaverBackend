import logging
from pathlib import Path
from typing import List, Dict, Tuple
from pydub import AudioSegment
from core.data_models import Scenario

logger = logging.getLogger(__name__)


def merge_chapter_audio(
        scenario: Scenario,
        audio_dir: Path,
        output_file_path: Path,
        subtitles_map: Dict = None
) -> Tuple[int, List[dict]]:
    """
    Склеивает аудиофайлы главы в один большой файл и создает карту синхронизации.
    Корректно обрабатывает новые типы данных, включая 'image' (без поиска аудио).
    """

    if subtitles_map is None:
        subtitles_map = {}

    combined_audio = AudioSegment.empty()
    sync_map = []
    current_offset_ms = 0

    gap_ms = 0
    silence = AudioSegment.silent(duration=gap_ms)

    logger.info(f"Начинаем склейку аудио для главы. Выходной файл: {output_file_path.name}")

    missing_files_count = 0

    for i, entry in enumerate(scenario.entries):
        eid = str(entry.id)

        instruct = getattr(entry, 'instruct_prompt', 'neutral')

        sync_item = {
            "id": eid,
            "text": entry.text,
            "speaker": entry.speaker,
            "type": entry.type,
            "emotion": instruct, # В мапе синхронизации оставляем ключ emotion для совместимости с фронтендом. TODO: Придумать что с фронтом делать
            "ambient": entry.ambient if entry.ambient else "none",
        }

        if entry.type == "image":
            sync_item["src"] = entry.src
            sync_item["start_ms"] = current_offset_ms
            sync_item["end_ms"] = current_offset_ms
            sync_map.append(sync_item)
            continue

        audio_filename = f"{eid}.wav"
        file_path = audio_dir / audio_filename

        segment_duration = 0

        if file_path.exists():
            try:
                segment = AudioSegment.from_file(str(file_path))
                segment_duration = len(segment)
                combined_audio += segment

                # Тишина после сегмента, если это не последний элемент и не картинка
                if gap_ms > 0 and i < len(scenario.entries) - 1:
                    next_entry = scenario.entries[i + 1]
                    if next_entry.type != "image":
                        combined_audio += silence

            except Exception as e:
                logger.error(f"Ошибка обработки аудиофайла {file_path.name}: {e}")
        else:
            missing_files_count += 1
            if missing_files_count <= 5:
                logger.warning(f"Аудиофайл не найден: {audio_filename}")

        entry_start = current_offset_ms
        entry_end = current_offset_ms + segment_duration

        sync_item["start_ms"] = entry_start
        sync_item["end_ms"] = entry_end

        # Alignment
        sub_info = subtitles_map.get(eid)
        if sub_info and 'words' in sub_info:
            adjusted_words = []
            for w in sub_info['words']:
                adjusted_words.append({
                    "word": w["word"],
                    "start": w["start"],
                    "end": w["end"]
                })
            sync_item["words"] = adjusted_words

        sync_map.append(sync_item)

        if segment_duration > 0:
            current_offset_ms = entry_end + gap_ms

    if missing_files_count > 0:
        logger.warning(f"Всего пропущено аудиофайлов: {missing_files_count}")

    output_file_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Экспорт общего аудиофайла: {output_file_path} (Длительность: {len(combined_audio)} мс)")

    if len(combined_audio) > 0:
        file_handle = combined_audio.export(str(output_file_path), format="mp3", bitrate="192k")
        file_handle.close()
    else:
        logger.warning("Итоговый аудиофайл пуст, экспорт не выполнен.")

    return len(combined_audio), sync_map