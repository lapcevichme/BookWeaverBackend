import logging
from typing import Optional, Dict, Any

from core.project_context import ProjectContext
from core.data_models import BookManifest, ManifestChapterEntry, ManifestMeta
from utils import file_utils
from utils.setup_logging import setup_logging

logger = logging.getLogger(__name__)


def init_manifest(
        book_name: str,
        metadata: Optional[Dict[str, Any]] = None
):
    """
    Создает manifest.json.
    Строгий режим: старые невалидные манифесты игнорируются.
    """
    if metadata is None:
        metadata = {}

    logger.info(f"🏁 ЗАПУСК ИНИЦИАЛИЗАЦИИ МАНИФЕСТА: '{book_name}'")

    context = ProjectContext(book_name=book_name)
    book_src_dir = context.book_dir
    manifest_path = context.manifest_file

    if not book_src_dir.exists():
        logger.error(f"❌ ПАПКА НЕ НАЙДЕНА: {book_src_dir}")
        return

    context.book_output_dir.mkdir(parents=True, exist_ok=True)

    chapter_paths = file_utils.get_all_chapters(book_src_dir)
    structure_entries = []

    for idx, path in enumerate(chapter_paths, 1):
        try:
            vol, chap = file_utils.parse_vol_chap_from_path(path)

            chapter_ctx = ProjectContext(book_name, vol, chap)
            status = "draft"
            if chapter_ctx.chapter_audio_dir.exists() and any(chapter_ctx.chapter_audio_dir.iterdir()):
                status = "audio_ready"

            display_title = f"Глава {chap}"
            if vol > 1: display_title += f" (Том {vol})"

            entry = ManifestChapterEntry(
                order=idx,
                title=display_title,
                vol=vol,
                chap=chap,
                status=status
            )
            structure_entries.append(entry)

        except Exception as e:
            logger.error(f"Ошибка с файлом {path}: {e}")

    old_manifest = None
    if manifest_path.exists():
        logger.info("📂 Обнаружен существующий manifest.json")
        try:
            old_manifest = BookManifest.load(manifest_path)
            logger.info("✅ Старый манифест валиден. Данные будут объединены.")
        except Exception:
            logger.warning("⚠️ СТАРЫЙ МАНИФЕСТ НЕСОВМЕСТИМ (LEGACY). ОН БУДЕТ ПЕРЕЗАПИСАН.")
            old_manifest = None

    old_meta = old_manifest.meta if old_manifest else ManifestMeta()

    final_meta = ManifestMeta(
        title=metadata.get("title") or old_meta.title,
        author=metadata.get("author") or old_meta.author,
        description=metadata.get("description") or old_meta.description,
        tags=metadata.get("tags") or old_meta.tags,
        source_url=metadata.get("source_url") or old_meta.source_url,
        status=metadata.get("status") or old_meta.status,
        version=old_meta.version,
        total_duration_ms=old_meta.total_duration_ms,
        cover_image=metadata.get("cover_image") or old_meta.cover_image,
        language=metadata.get("language") or old_meta.language or "ru"
    )

    new_manifest = BookManifest(
        project_id=book_name,
        meta=final_meta,
        structure=structure_entries
    )

    if old_manifest and old_manifest.config:
        new_manifest.config = old_manifest.config

    new_manifest.config.last_run_log = f"Found {len(structure_entries)} chapters"

    new_manifest.save(manifest_path)

    logger.info(f"💾 МАНИФЕСТ ОБНОВЛЕН: {final_meta.title} ({len(structure_entries)} глав)")


if __name__ == "__main__":
    setup_logging()
    init_manifest("test_book", {"title": "Test"})