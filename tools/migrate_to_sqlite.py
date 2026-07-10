import json
import logging
from pathlib import Path
from uuid import UUID
from sqlmodel import Session, select
from core.database import engine, init_db
from core.data_models import Book, Chapter, Character, ScenarioEntry, ChapterSummary, CharacterType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate():
    init_db()
    output_dir = Path("output")
    
    if not output_dir.exists():
        logger.error("Папка output/ не найдена. Нечего мигрировать.")
        return

    with Session(engine) as session:
        for book_path in output_dir.iterdir():
            if not book_path.is_dir():
                continue
            
            book_id = book_path.name
            manifest_file = book_path / "manifest.json"
            
            if not manifest_file.exists():
                logger.warning(f"Манифест не найден для {book_id}, пропускаем.")
                continue

            logger.info(f"Миграция книги: {book_id}")
            
            # 1. Загружаем Манифест -> Книга
            with open(manifest_file, "r", encoding="utf-8") as f:
                m_data = json.load(f)
            
            book = session.get(Book, book_id)
            if not book:
                book = Book(
                    id=book_id,
                    title=m_data.get("meta", {}).get("title", book_id),
                    author=m_data.get("meta", {}).get("author"),
                    description=m_data.get("meta", {}).get("description"),
                    status=m_data.get("meta", {}).get("status", "ongoing"),
                    tags=m_data.get("meta", {}).get("tags", []),
                    config=m_data.get("config", {})
                )
                session.add(book)
            
            # 2. Персонажи
            char_archive_file = book_path / "character_archive.json"
            char_map = {} # Нам понадобится для привязки сценария
            
            if char_archive_file.exists():
                with open(char_archive_file, "r", encoding="utf-8") as f:
                    c_data = json.load(f)
                    # character_archive.json может быть либо списком, либо объектом с ключом 'characters'
                    characters_list = c_data.get("characters", []) if isinstance(c_data, dict) else c_data
                
                for c in characters_list:
                    char_id = UUID(c["id"]) if isinstance(c["id"], str) else c["id"]
                    character = session.get(Character, char_id)
                    if not character:
                        character = Character(
                            id=char_id,
                            book_id=book_id,
                            name=c["name"],
                            entity_type=c.get("entity_type", CharacterType.PERSON),
                            aliases=c.get("aliases", []),
                            gender=c.get("gender"),
                            role_tier=c.get("role_tier", "background"),
                            spoiler_free_description=c.get("spoiler_free_description", ""),
                            description=c.get("description", ""),
                            visual_base=c.get("visual_base"),
                            voice_base=c.get("voice_base", ""),
                            voice_timeline=c.get("voice_timeline", {}),
                            visual_timeline=c.get("visual_timeline", {}),
                            chapter_mentions=c.get("chapter_mentions", {})
                        )
                        session.add(character)
                    char_map[c["name"]] = char_id

            # 3. Главы и Сценарии
            # Сначала загрузим общие саммари, если они есть
            summaries_file = book_path / "chapter_summaries.json"
            all_summaries = {}
            if summaries_file.exists():
                with open(summaries_file, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                    all_summaries = s_data.get("summaries", {})

            for chapter_item in m_data.get("structure", []):
                chap_id = chapter_item["id"]
                chapter = session.get(Chapter, chap_id)
                if not chapter:
                    chapter = Chapter(
                        id=chap_id,
                        book_id=book_id,
                        volume_num=chapter_item.get("vol", 1),
                        chapter_num=chapter_item.get("chap"),
                        title=chapter_item.get("title"),
                        status=chapter_item.get("status", "draft"),
                        order_index=chapter_item.get("order", 0)
                    )
                    session.add(chapter)
                
                # Саммари главы
                if chap_id in all_summaries:
                    summ = all_summaries[chap_id]
                    summary_obj = session.get(ChapterSummary, chap_id)
                    if not summary_obj:
                        summary_obj = ChapterSummary(
                            chapter_id=chap_id,
                            teaser=summ.get("teaser", ""),
                            synopsis=summ.get("synopsis", "")
                        )
                        session.add(summary_obj)

                # Сценарий
                scenario_file = book_path / chap_id / "scenario.json"
                if scenario_file.exists():
                    with open(scenario_file, "r", encoding="utf-8") as f:
                        entries_list = json.load(f)
                    
                    for i, e in enumerate(entries_list):
                        e_id = UUID(e["id"]) if isinstance(e["id"], str) else e["id"]
                        entry = session.get(ScenarioEntry, e_id)
                        if not entry:
                            # Ищем ID персонажа по имени
                            speaker_id = char_map.get(e.get("speaker"))
                            
                            entry = ScenarioEntry(
                                id=e_id,
                                chapter_id=chap_id,
                                speaker_id=speaker_id,
                                type=e["type"],
                                text=e.get("text"),
                                tts_text=e.get("tts_text"),
                                speaker_name=e.get("speaker"),
                                instruct_prompt=e.get("instruct_prompt", "neutral"),
                                ambient=e.get("ambient", "none"),
                                sfx=e.get("sfx"),
                                audio_file=e.get("audio_file"),
                                src=e.get("src"),
                                order_index=i
                            )
                            session.add(entry)
            
            session.commit()
            logger.info(f"Книга {book_id} успешно перенесена.")

if __name__ == "__main__":
    migrate()
