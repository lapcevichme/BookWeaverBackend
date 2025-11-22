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
    Склеивает аудиофайлы главы в один большой файл.

    Args:
        scenario: Объект сценария (список реплик).
        audio_dir: Папка, где лежат отдельные .wav/.mp3 реплик.
        output_file_path: Путь, куда сохранить итоговый файл (например, full_chapter.mp3).
        subtitles_map: (Опционально) Словарь субтитров для уточнения имен файлов.

    Returns:
        (total_duration_ms, sync_map_list)
    """

    if subtitles_map is None:
        subtitles_map = {}

    combined_audio = AudioSegment.empty()
    sync_map = []
    current_offset_ms = 0

    gap_ms = 0
    silence = AudioSegment.silent(duration=gap_ms)

    logger.info(f"Начинаем склейку аудио для {output_file_path.name}...")

    for i, entry in enumerate(scenario.entries):
        eid = str(entry.id)
        sub_info = subtitles_map.get(eid, {})

        audio_filename = sub_info.get("audio_file")
        if not audio_filename:
            audio_filename = entry.audio_file
        if not audio_filename:
            audio_filename = f"{eid}.wav"

        file_path = audio_dir / audio_filename

        if not file_path.exists():
            for ext in ['.mp3', '.ogg', '.flac', '.wav']:
                alt = audio_dir / f"{file_path.stem}{ext}"
                if alt.exists():
                    file_path = alt
                    break

        segment_duration = 0

        if file_path.exists():
            try:
                segment = AudioSegment.from_file(str(file_path))
                segment_duration = len(segment)

                combined_audio += segment
                if gap_ms > 0 and i < len(scenario.entries) - 1:
                    combined_audio += silence

            except Exception as e:
                logger.error(f"Ошибка обработки файла {file_path.name}: {e}")
                pass
        else:
            logger.warning(f"Файл не найден: {audio_filename}. Пропускаем в склейке.")

        entry_start = current_offset_ms
        entry_end = current_offset_ms + segment_duration

        sync_item = {
            "text": entry.text,
            "start_ms": entry_start,
            "end_ms": entry_end,
            "speaker": entry.speaker,
            "ambient": entry.ambient if entry.ambient else "none"
        }
        sync_map.append(sync_item)

        current_offset_ms = entry_end + gap_ms

    output_file_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Экспорт файла: {output_file_path} (Длительность: {len(combined_audio)}ms)")

    file_handle = combined_audio.export(str(output_file_path), format="mp3", bitrate="192k")
    file_handle.close()

    return len(combined_audio), sync_map