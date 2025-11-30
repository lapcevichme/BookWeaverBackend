import json
import logging
import re
import socket
from typing import List

import config
from api import state
from api.security import verify_token
from core.data_models import BookManifest, CharacterArchive, ChapterSummaryArchive, Scenario
from core.project_context import ProjectContext
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from utils.audio_merger import merge_chapter_audio

from api.mobile.mobile_api_models import (
    BookStructureResponseDto,
    BookManifestStructureDto,
    CharacterListEntryDto,
    CharacterDetailsDto,
    ChapterInfoDto,
    ChapterStubDto,
    OnboardingDataDto,
    PingResponseDto,
    PlaybackDataResponseDto,
    SyncMapEntryDto,
    BookManifestDto
)

logger = logging.getLogger(__name__)

# Роутеры
api_router = APIRouter(prefix="/api", tags=["Mobile API (JSON)"])
static_router = APIRouter(prefix="/static", tags=["Mobile API (Static Files)"], dependencies=[Depends(verify_token)])
download_router = APIRouter(prefix="/download", tags=["Mobile API (Downloads)"], dependencies=[Depends(verify_token)])


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def parse_chapter_id(chapter_id: str) -> (int, int):
    match = re.match(r"vol_(\d+)_chap_(\d+)", chapter_id)
    if not match:
        raise HTTPException(status_code=400, detail=f"Invalid chapterId format: {chapter_id}")
    return int(match.group(1)), int(match.group(2))


# abcolute vibecode
@api_router.get("/show-qr", response_class=HTMLResponse)
async def show_qr_code_page():
    html_content = """
    <!DOCTYPE html>
    <html lang="ru">
    <head><title>QR Connect</title><script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script></head>
    <body style="display:flex;justify-content:center;align-items:center;height:100vh;font-family:sans-serif;">
        <div style="text-align:center;">
            <h1>Scan to Connect</h1>
            <div id="qrcode"></div>
            <script>
                fetch('/api/onboarding-data').then(r=>r.json()).then(d=>{
                    new QRCode(document.getElementById("qrcode"), JSON.stringify(d));
                });
            </script>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@api_router.get("/onboarding-data", response_model=OnboardingDataDto)
async def get_onboarding_data():
    return OnboardingDataDto(
        ip=get_local_ip(),
        port=config.SERVER_PORT,
        token=state.SERVER_TOKEN,
        serverName="BookWeaver Server"
    )


@api_router.get("/ping", response_model=PingResponseDto)
async def ping():
    return PingResponseDto(status="ok", server_name="BookWeaver Server")


# Книги и Структура

@api_router.get("/books", response_model=List[BookManifestDto], dependencies=[Depends(verify_token)])
async def get_all_books():
    books_list = []
    books_dir = config.OUTPUT_DIR
    if not books_dir.exists():
        return []

    for book_dir in books_dir.iterdir():
        if book_dir.is_dir():
            try:
                context = ProjectContext(book_name=book_dir.name)
                if not context.manifest_file.exists():
                    continue

                manifest_data = BookManifest.load(context.manifest_file)
                character_voices_dto = {str(uuid): voice for uuid, voice in manifest_data.character_voices.items()}

                books_list.append(BookManifestDto(
                    book_name=manifest_data.book_name,
                    author=manifest_data.author,
                    character_voices=character_voices_dto,
                    default_narrator_voice=manifest_data.default_narrator_voice
                ))
            except Exception as e:
                logger.warning(f"Не удалось загрузить манифест для '{book_dir.name}': {e}")
                continue

    return books_list


@api_router.get("/books/{bookId}/structure", response_model=BookStructureResponseDto,
                dependencies=[Depends(verify_token)])
async def get_book_structure(bookId: str):
    try:
        context = ProjectContext(book_name=bookId)
        if not context.manifest_file.exists():
            raise HTTPException(status_code=404, detail="Книга не найдена (нет манифеста).")

        manifest_data = BookManifest.load(context.manifest_file)

        manifest_structure = BookManifestStructureDto(
            book_name=manifest_data.book_name,
            title=manifest_data.book_name.replace("_", " ").title(),
            author=manifest_data.author,
            version=1,
            poster_url=f"/static/books/{bookId}/cover.jpg"
        )

        chapters_dto = []
        ordered_chapters = context.get_ordered_chapters()
        for vol_num, chap_num in ordered_chapters:
            chapter_id = f"vol_{vol_num}_chap_{chap_num}"

            # Проверка наличия аудио
            chapter_audio_dir = context.book_output_dir / chapter_id / "audio"
            has_audio = False
            if chapter_audio_dir.exists():
                try:
                    if any(chapter_audio_dir.iterdir()):
                        has_audio = True
                except OSError:
                    pass

            chapters_dto.append(ChapterStubDto(
                id=chapter_id,
                title=f"Том {vol_num}, Глава {chap_num}",
                version=1,
                volume_number=vol_num,
                has_audio=has_audio
            ))

        return BookStructureResponseDto(
            manifest=manifest_structure,
            chapters=chapters_dto
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Ошибка /structure для {bookId}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/books/{bookId}/{chapterId}/originalText", response_class=PlainTextResponse,
                dependencies=[Depends(verify_token)])
async def get_original_chapter_text(bookId: str, chapterId: str):
    """
    Возвращает оригинальный текст главы (Raw Text).
    """
    try:
        vol, chap = parse_chapter_id(chapterId)
        context = ProjectContext(book_name=bookId, volume_num=vol, chapter_num=chap)

        if not hasattr(context, 'chapter_file') or not context.chapter_file.exists():
            raise HTTPException(status_code=404, detail="Original text file not found")

        content = context.chapter_file.read_text(encoding="utf-8")
        return PlainTextResponse(content=content, media_type="text/plain")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error serving original text for {bookId}/{chapterId}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Персонажи

@api_router.get("/books/{bookId}/characters", response_model=List[CharacterListEntryDto],
                dependencies=[Depends(verify_token)])
async def get_book_characters(bookId: str):
    try:
        context = ProjectContext(book_name=bookId)
        if not context.character_archive_file.exists():
            return []

        char_archive = CharacterArchive.load(context.character_archive_file)
        result_list = []

        for char in char_archive.characters:
            avatar_url = f"/static/books/{bookId}/chars/{char.id}.jpg"
            result_list.append(CharacterListEntryDto(
                id=str(char.id),
                name=char.name,
                avatar_url=avatar_url,
                short_role=None
            ))

        return result_list
    except Exception as e:
        logger.error(f"Ошибка /characters для {bookId}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/books/{bookId}/characters/{characterId}", response_model=CharacterDetailsDto,
                dependencies=[Depends(verify_token)])
async def get_character_details(bookId: str, characterId: str):
    try:
        context = ProjectContext(book_name=bookId)
        if not context.character_archive_file.exists():
            raise HTTPException(status_code=404, detail="Архив персонажей не найден.")

        char_archive = CharacterArchive.load(context.character_archive_file)
        target_char = next((c for c in char_archive.characters if str(c.id) == characterId), None)

        if not target_char:
            raise HTTPException(status_code=404, detail="Персонаж не найден.")

        return CharacterDetailsDto(
            id=str(target_char.id),
            name=target_char.name,
            avatar_url=f"/static/books/{bookId}/chars/{target_char.id}.jpg",
            description=target_char.description,
            spoiler_free_description=target_char.spoiler_free_description,
            aliases=target_char.aliases,
            chapter_mentions=target_char.chapter_mentions
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Ошибка получения персонажа {characterId}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Детали главы

@api_router.get("/books/{bookId}/chapters/{chapterId}/info", response_model=ChapterInfoDto,
                dependencies=[Depends(verify_token)])
async def get_chapter_info(bookId: str, chapterId: str):
    try:
        context = ProjectContext(book_name=bookId)
        if not context.summary_archive_file.exists():
            vol, chap = parse_chapter_id(chapterId)
            return ChapterInfoDto(
                chapter_id=chapterId,
                title=f"Том {vol}, Глава {chap}",
                teaser="Описание отсутствует.",
                synopsis="Синопсис не сгенерирован."
            )

        summary_archive = ChapterSummaryArchive.load(context.summary_archive_file)
        summary = summary_archive.summaries.get(chapterId)
        vol, chap = parse_chapter_id(chapterId)

        if summary:
            return ChapterInfoDto(
                chapter_id=chapterId,
                title=f"Том {vol}, Глава {chap}",
                teaser=summary.teaser,
                synopsis=summary.synopsis
            )
        else:
            return ChapterInfoDto(
                chapter_id=chapterId,
                title=f"Том {vol}, Глава {chap}",
                teaser="Описание пока не готово.",
                synopsis=""
            )
    except Exception as e:
        logger.error(f"Ошибка /chapters/.../info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Playback Data

@api_router.get("/books/{bookId}/{chapterId}/playbackData", response_model=PlaybackDataResponseDto,
                dependencies=[Depends(verify_token)])
async def get_chapter_playback_data(bookId: str, chapterId: str, force_rebuild: bool = False):
    """
    Возвращает данные для воспроизведения: единый файл + карта синхронизации.
    Если аудио нет, возвращает sync_map с пустым audio_url.
    """
    try:
        vol, chap = parse_chapter_id(chapterId)
        context = ProjectContext(book_name=bookId, volume_num=vol, chapter_num=chap)

        # Файлы кеша для склеенной версии
        full_audio_path = context.chapter_audio_dir / "full_chapter.mp3"
        sync_map_path = context.chapter_audio_dir / "full_chapter_map.json"

        # Пытаемся отдать из кеша (если он есть и валиден)
        if full_audio_path.exists() and sync_map_path.exists() and not force_rebuild:
            logger.info(f"Serving cached playback data for {chapterId}")
            try:
                sync_data = json.loads(sync_map_path.read_text("utf-8"))
                duration_ms = 0
                if sync_data:
                    duration_ms = sync_data[-1]["end_ms"]

                return PlaybackDataResponseDto(
                    audio_url=f"/static/books/{bookId}/{chapterId}/audio/full_chapter.mp3",
                    duration_ms=duration_ms,
                    sync_map=[SyncMapEntryDto(**item) for item in sync_data]
                )
            except Exception as e:
                logger.warning(f"Cache corrupted for {chapterId}, rebuilding... {e}")

        # Проверяем наличие сценария (без него мы вообще ничего не можем отдать)
        if not context.scenario_file.exists():
            raise HTTPException(status_code=404,
                                detail=f"Scenario not found for {chapterId}. Cannot build playback data.")

        scenario_data = Scenario.load(context.scenario_file)

        # Проверяем наличие исходных аудиофайлов
        has_source_audio = False
        if context.chapter_audio_dir.exists():
            for f in context.chapter_audio_dir.iterdir():
                if f.is_file() and f.name != "full_chapter.mp3" and f.suffix.lower() in ['.wav', '.mp3', '.ogg',
                                                                                         '.flac']:
                    has_source_audio = True
                    break

        if not has_source_audio:
            logger.info(f"Audio not found for {chapterId}. Returning text-only sync map.")

            text_only_map = []
            for entry in scenario_data.entries:
                text_only_map.append(SyncMapEntryDto(
                    text=entry.text,
                    start_ms=0,
                    end_ms=0,
                    speaker=entry.speaker,
                    ambient=entry.ambient if entry.ambient else "none"
                ))

            return PlaybackDataResponseDto(
                audio_url=None,
                duration_ms=0,
                sync_map=text_only_map
            )

        # Если аудио ЕСТЬ, запускаем склейку
        subtitles_map = {}
        if context.subtitles_file.exists():
            try:
                sub_json = json.loads(context.subtitles_file.read_text("utf-8"))
                if isinstance(sub_json, list):
                    subtitles_map = {e.get("id"): e for e in sub_json if e.get("id")}
            except Exception:
                pass

        total_duration, sync_map_raw = merge_chapter_audio(
            scenario=scenario_data,
            audio_dir=context.chapter_audio_dir,
            output_file_path=full_audio_path,
            subtitles_map=subtitles_map
        )

        with open(sync_map_path, "w", encoding="utf-8") as f:
            json.dump(sync_map_raw, f, ensure_ascii=False, indent=2)

        return PlaybackDataResponseDto(
            audio_url=f"/static/books/{bookId}/{chapterId}/audio/full_chapter.mp3",
            duration_ms=total_duration,
            sync_map=[SyncMapEntryDto(**item) for item in sync_map_raw]
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Playback generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Static Files

@static_router.get("/books/{bookId}/chars/{charId}.jpg")
async def get_character_avatar(bookId: str, charId: str):
    char_img_path = config.OUTPUT_DIR / bookId / "chars" / f"{charId}.jpg"
    if not char_img_path.exists():
        return HTTPException(status_code=404, detail="Avatar not found")
    return FileResponse(char_img_path)


@static_router.get("/books/{bookId}/cover.jpg")
async def get_book_cover(bookId: str):
    context = ProjectContext(book_name=bookId)
    if context.cover_file.exists():
        return FileResponse(context.cover_file)
    raise HTTPException(status_code=404)


@static_router.get("/books/{bookId}/{chapterId}/audio/")
async def get_chapter_audio_empty_check(bookId: str, chapterId: str):
    logger.warning(f"Client requested empty audio file for {bookId}/{chapterId}")
    return JSONResponse(status_code=404, content={"detail": "Missing filename"})


@static_router.get("/books/{bookId}/{chapterId}/audio/{audioFileName}")
async def get_chapter_audio(bookId: str, chapterId: str, audioFileName: str):
    try:
        vol, chap = parse_chapter_id(chapterId)
        context = ProjectContext(book_name=bookId, volume_num=vol, chapter_num=chap)
        audio_path = context.chapter_audio_dir / audioFileName

        if audio_path.exists():
            return FileResponse(audio_path)

        stem = audio_path.stem
        for ext in ['.wav', '.mp3', '.ogg', '.flac']:
            alt_path = context.chapter_audio_dir / f"{stem}{ext}"
            if alt_path.exists():
                return FileResponse(alt_path)

        raise HTTPException(status_code=404, detail="Audio file not found")

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error serving audio {audioFileName}: {e}")
        raise HTTPException(status_code=404)


# Global Ambient
# TODO: пересмотреть логику эмбиентов на бэке: рассмотреть хранение в самой книге
@static_router.get("/ambient/{ambientName}")
async def get_global_ambient_file(ambientName: str):
    p = config.AMBIENT_DIR / ambientName
    if not p.exists():
        for ext in ['.mp3', '.wav', '.ogg']:
            if (config.AMBIENT_DIR / (ambientName + ext)).exists():
                p = config.AMBIENT_DIR / (ambientName + ext)
                break
    if p.exists():
        return FileResponse(p)
    logger.warning(f"Эмбиент не найден: {ambientName}")
    raise HTTPException(status_code=404, detail="Ambient file not found")


@static_router.get("/books/{bookId}/ambient/{ambientName}")
async def get_ambient_file_legacy(bookId: str, ambientName: str):
    return await get_global_ambient_file(ambientName)
