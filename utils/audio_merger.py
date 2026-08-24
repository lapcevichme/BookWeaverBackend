import logging
import subprocess
import json
import os
import tempfile
from pathlib import Path
from typing import List, Dict, Tuple
from core.data_models import Scenario

logger = logging.getLogger(__name__)

def get_audio_duration_ms(file_path: Path) -> int:
    """Получает длительность аудиофайла в миллисекундах через ffprobe."""
    try:
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        duration_sec = float(result.stdout.strip())
        return int(duration_sec * 1000)
    except Exception as e:
        logger.error(f"Ошибка при получении длительности {file_path.name}: {e}")
        return 0


def normalize_audio_file(
    src_path: Path,
    dst_path: Path,
    target_db: float = -25.0,
    trim_silence: bool = True,
    fade_ms: int = 50
) -> bool:
    """
    Обрабатывает и нормализует аудиофайл (громкость, обрезка тишины, fade in/out).
    """
    try:
        from pydub import AudioSegment
        sound = AudioSegment.from_file(src_path)

        if trim_silence:
            def detect_leading_silence(snd, silence_threshold=-50.0, chunk_size=10):
                trim_ms = 0
                while snd[trim_ms:trim_ms + chunk_size].dBFS < silence_threshold and trim_ms < len(snd):
                    trim_ms += chunk_size
                return trim_ms

            start_trim = detect_leading_silence(sound)
            end_trim = detect_leading_silence(sound.reverse())
            if start_trim + end_trim < len(sound):
                sound = sound[start_trim: len(sound) - end_trim]

        change_in_dBFS = target_db - sound.dBFS
        sound = sound.apply_gain(change_in_dBFS)

        if fade_ms > 0 and len(sound) > fade_ms * 2:
            sound = sound.fade_in(fade_ms).fade_out(fade_ms)

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        fmt = dst_path.suffix.lstrip('.') or "mp3"
        sound.export(dst_path, format=fmt, bitrate="192k")
        return True
    except Exception as e:
        logger.error(f"Ошибка нормализации аудио {src_path.name}: {e}")
        return False

def merge_chapter_audio(
        scenario: Scenario,
        audio_dir: Path,
        output_file_path: Path
) -> Tuple[int, List[dict]]:
    """
    Склеивает аудиофайлы главы через ffmpeg (стриминг, экономно по памяти).
    Создает карту синхронизации на основе метаданных файлов и данных из БД.
    """
    sync_map = []
    current_offset_ms = 0
    audio_files_to_concat = []
    
    missing_files_count = 0
    logger.info(f"Начинаем оптимизированную склейку аудио для {output_file_path.name}")

    for entry in scenario.entries:
        eid = str(entry.id)
        instruct = getattr(entry, 'instruct_prompt', 'neutral')

        sync_item = {
            "id": eid,
            "text": entry.text,
            "speaker": entry.speaker_name if hasattr(entry, 'speaker_name') else getattr(entry, 'speaker', 'Unknown'),
            "type": entry.type,
            "emotion": instruct,
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
            segment_duration = get_audio_duration_ms(file_path)
            if segment_duration > 0:
                audio_files_to_concat.append(file_path)
        else:
            missing_files_count += 1
            if missing_files_count <= 5:
                logger.warning(f"Аудиофайл не найден: {audio_filename}")

        entry_start = current_offset_ms
        entry_end = current_offset_ms + segment_duration

        sync_item["start_ms"] = entry_start
        sync_item["end_ms"] = entry_end

        # Alignment (субтитры по словам) - читаем из БД
        if hasattr(entry, 'audio_subtitles') and entry.audio_subtitles and 'words' in entry.audio_subtitles:
            relative_words = entry.audio_subtitles['words']
            # Конвертируем относительные тайминги в глобальные
            global_words = []
            for w in relative_words:
                global_words.append({
                    "word": w["word"],
                    "start": w["start"] + entry_start,
                    "end": w["end"] + entry_start
                })
            sync_item["words"] = global_words

        sync_map.append(sync_item)
        current_offset_ms = entry_end

    if not audio_files_to_concat:
        logger.warning("Нет аудиофайлов для склейки.")
        return 0, sync_map

    # Создаем временный файл для ffmpeg concat
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        for p in audio_files_to_concat:
            # Пути в concat файле должны быть экранированы
            safe_path = str(p.absolute()).replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")
        concat_list_path = f.name

    try:
        output_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Запускаем ffmpeg
        # -f concat: используем демуксер конкатенации
        # -safe 0: разрешаем любые пути
        # -y: перезаписывать выходной файл
        cmd = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', 
            '-i', concat_list_path, 
            '-acodec', 'libmp3lame', '-b:a', '192k', 
            str(output_file_path)
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        logger.info(f"✅ Успешно склеено в {output_file_path.name}. Итого: {current_offset_ms} мс")
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Ошибка ffmpeg: {e.stderr.decode()}")
        return 0, sync_map
    finally:
        if os.path.exists(concat_list_path):
            os.remove(concat_list_path)

    return current_offset_ms, sync_map
