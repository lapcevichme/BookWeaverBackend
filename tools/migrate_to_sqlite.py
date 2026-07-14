import json
import logging
from pathlib import Path
from uuid import UUID
from sqlmodel import Session, select
from core.database import engine, init_db
from core.data_models import Book, Chapter, Character, ScenarioEntry, ChapterSummary, CharacterType

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def migrate():
    init_db()
    output_dir = Path("output")
    input_dir = Path("input/books")
    
    if not output_dir.exists():
        logger.error("Папка output/ не найдена. Нечего мигрировать.")
        return

    with Session(engine) as session:
        # Проходим по всем папкам книг в output
        books_processed = 0
        for book_path in output_dir.iterdir():
            if not book_path.is_dir():
                continue
            
            book_id = book_path.name
            manifest_file = book_path / "manifest.json"
            
            if not manifest_file.exists():
                logger.warning(f"  [SKIPPED] Манифест не найден для {book_id}")
                continue

            logger.info(f">>> Миграция книги: {book_id}")
            
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
                    cover_image_path=m_data.get("meta", {}).get("cover_image"),
                    tags=m_data.get("meta", {}).get("tags", []),
                    config=m_data.get("config", {})
                )
                session.add(book)
                session.flush() # Чтобы ID книги был доступен для связей
            
            # 2. Персонажи
            char_archive_file = book_path / "character_archive.json"
            char_name_to_id = {}
            
            if char_archive_file.exists():
                with open(char_archive_file, "r", encoding="utf-8") as f:
                    c_data = json.load(f)
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
                    char_name_to_id[c["name"]] = char_id
                logger.info(f"  - Загружено персонажей: {len(characters_list)}")

            # 3. Главы и Сценарии
            summaries_file = book_path / "chapter_summaries.json"
            all_summaries = {}
            if summaries_file.exists():
                with open(summaries_file, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                    all_summaries = s_data.get("summaries", {})

            chapters_list = m_data.get("structure", [])
            for chapter_item in chapters_list:
                local_chap_id = chapter_item["id"]
                global_chap_id = f"{book_id}:{local_chap_id}" # Глобально уникальный ID
                
                # Парсим vol и chap из ID, если их нет
                vol = chapter_item.get('vol')
                chap = chapter_item.get('chap')
                if vol is None or chap is None:
                    import re
                    match = re.search(r'vol_(\d+)_chap_(\d+)', local_chap_id)
                    if match:
                        vol = int(match.group(1))
                        chap = int(match.group(2))
                    else:
                        vol = vol or 1
                        chap = chap or 0
                
                # Пытаемся найти текст главы в input/books
                raw_text = None
                vol_dir = input_dir / book_id / f"vol_{vol}"
                if vol_dir.exists():
                    for ext in [".md", ".txt"]:
                        text_path = vol_dir / f"chapter_{chap}{ext}"
                        if text_path.exists():
                            raw_text = text_path.read_text("utf-8")
                            break

                chapter = session.get(Chapter, global_chap_id)
                if not chapter:
                    chapter = Chapter(
                        id=global_chap_id,
                        book_id=book_id,
                        chapter_id=local_chap_id,
                        volume_num=vol,
                        chapter_num=chap,
                        title=chapter_item.get("title"),
                        status=chapter_item.get("status", "draft"),
                        order_index=chapter_item.get("order", 0),
                        raw_text=raw_text
                    )
                    session.add(chapter)
                    session.flush()
                
                # Саммари
                if local_chap_id in all_summaries:
                    summ = all_summaries[local_chap_id]
                    summary_obj = session.get(ChapterSummary, global_chap_id)
                    if not summary_obj:
                        summary_obj = ChapterSummary(
                            chapter_id=global_chap_id,
                            teaser=summ.get("teaser", ""),
                            synopsis=summ.get("synopsis", "")
                        )
                        session.add(summary_obj)

                # Сценарий
                scenario_file = book_path / local_chap_id / "scenario.json"
                if scenario_file.exists():
                    with open(scenario_file, "r", encoding="utf-8") as f:
                        entries_list = json.load(f)
                    
                    entries_count = 0
                    for i, e in enumerate(entries_list):
                        e_id = UUID(e["id"]) if isinstance(e["id"], str) else e["id"]
                        entry = session.get(ScenarioEntry, e_id)
                        if not entry:
                            speaker_name = e.get("speaker")
                            speaker_id = char_name_to_id.get(speaker_name)
                            
                            entry = ScenarioEntry(
                                id=e_id,
                                chapter_id=global_chap_id, # Ссылка на глобальный ID главы
                                speaker_id=speaker_id,
                                type=e["type"],
                                text=e.get("text"),
                                tts_text=e.get("tts_text"),
                                speaker_name=speaker_name,
                                instruct_prompt=e.get("instruct_prompt", "neutral"),
                                ambient=e.get("ambient", "none"),
                                sfx=e.get("sfx"),
                                audio_file=e.get("audio_file") or e.get("audio_file_path"),
                                src=e.get("src"),
                                order_index=i
                            )
                            session.add(entry)
                            entries_count += 1
                    # logger.info(f"    * Глава {local_chap_id}: {entries_count} реплик.")
            
            session.commit()
            books_processed += 1
            logger.info(f"  [DONE] Книга {book_id} полностью перенесена.")

    logger.info(f"\nМиграция завершена! Перенесено книг: {books_processed}")

if __name__ == "__main__":
    migrate()
