import logging
from fastapi import APIRouter, HTTPException
from sqlmodel import select

from core.book_repository import BookRepository
from api.models import BookArtifactName, ProjectMetricsResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{book_name}/metrics", response_model=ProjectMetricsResponse)
async def get_project_metrics(book_name: str):
    """Возвращает детальные метрики книги: токены, RTF и агрегированные ошибки."""
    from core.data_models import LLMMetric, AudioMetric, MetricCounter, ScenarioEntry
    from sqlalchemy import func

    repo = BookRepository(book_id=book_name)
    db_chapters = repo.get_all_chapters()

    total_tokens = 0
    book_chapters_data = []

    book_counters = {
        "json_parse_errors": 0,
        "name_collisions": 0,
        "tts_hallucinations": 0,
        "tts_retries": 0,
        "api_retries": 0
    }

    try:
        with repo.get_session() as session:
            llm_calls = session.exec(select(LLMMetric)).all()
            audio_calls = session.exec(select(AudioMetric)).all()
            counters = session.exec(select(MetricCounter)).all()

            for chap in db_chapters:
                chap_llm = [m for m in llm_calls if m.chapter_id == chap.id]
                chap_audio = [m for m in audio_calls if m.chapter_id == chap.id]
                chap_counters = [m for m in counters if m.chapter_id == chap.id]

                chap_errs = {c.counter_name: c.value for c in chap_counters}

                for c in chap_counters:
                    if c.counter_name in book_counters:
                        book_counters[c.counter_name] += c.value

                avg_rtf = sum(a.rtf for a in chap_audio) / len(chap_audio) if chap_audio else 0
                total_audio_sec = sum(a.audio_duration_ms for a in chap_audio) / 1000
                chap_tokens = sum(m.input_tokens + m.output_tokens for m in chap_llm)
                total_tokens += chap_tokens

                book_chapters_data.append({
                    "chapter_id": chap.id,
                    "llm_calls": len(chap_llm),
                    "total_tokens": chap_tokens,
                    "audio_units": len(chap_audio),
                    "total_audio_duration_sec": round(total_audio_sec, 2),
                    "avg_rtf": round(avg_rtf, 3),
                    "avg_cer": round(sum(a.cer for a in chap_audio) / len(chap_audio), 4) if chap_audio else 0,
                    "errors": chap_errs
                })
    except Exception as e:
        logger.error(f"Error querying metrics from DB for project {book_name}: {e}")
        return {"chapters": [], "total_tokens": 0, "counters": {}}

    character_activity = {}
    try:
        with repo.get_session() as session:
            query = session.query(
                ScenarioEntry.chapter_id,
                ScenarioEntry.speaker_id,
                func.count(ScenarioEntry.id)
            ).filter(ScenarioEntry.speaker_id != None).group_by(
                ScenarioEntry.chapter_id, ScenarioEntry.speaker_id
            )

            for chap_id, char_id, count in query.all():
                char_id_str = str(char_id)
                if char_id_str not in character_activity:
                    character_activity[char_id_str] = {}
                character_activity[char_id_str][chap_id] = count
    except Exception as e:
        logger.warning(f"Error calculating character activity for project {book_name}: {e}")

    return {
        "book_id": book_name,
        "total_tokens": total_tokens,
        "counters": book_counters,
        "chapters": book_chapters_data,
        "character_activity": character_activity
    }


@router.get("/{book_name}/artifacts/{artifact_name}")
async def get_book_artifact(book_name: str, artifact_name: BookArtifactName):
    """Возвращает данные артефакта уровня книги из БД."""
    repo = BookRepository(book_id=book_name)

    if artifact_name == BookArtifactName.MANIFEST:
        return repo.load_manifest()
    elif artifact_name == BookArtifactName.CHARACTER_ARCHIVE:
        return repo.get_character_archive()
    elif artifact_name == BookArtifactName.CHAPTER_SUMMARIES:
        return repo.get_summary_archive()

    raise HTTPException(status_code=404, detail="Артефакт не найден.")
