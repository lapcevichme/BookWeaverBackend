"""
Централизованный модуль для управления и форматирования всех промптов.
**ВЕРСИЯ 3.1 - Финальная оптимизация**
"""
import json
from typing import List, Dict, Optional

from core.data_models import (
    ChapterSummary,
    CharacterArchive,
    CharacterReconResult,
    CharacterPatchList,
    RawScenario,
    AmbientTransitionList,
    EmotionMap
)
from core.project_context import ProjectContext
from utils.prompt_utils import generate_human_schema


def format_summary_generation_prompt(context: ProjectContext) -> str:
    """
    Формирует промпт для генерации двух типов пересказа главы.
    """
    schema_description = generate_human_schema(ChapterSummary)

    return f"""
ТЫ — ОПЫТНЫЙ ЛИТЕРАТУРНЫЙ РЕДАКТОР.

ТВОЯ ЗАДАЧА:
Прочитай "Текст главы" и создай для него ДВА типа пересказа: "тизер" и "конспект".
Верни результат в виде JSON-объекта, который строго соответствует предоставленному формату.

ОПИСАНИЕ ТИПОВ ПЕРЕСКАЗА:
1.  `teaser`: Краткий (40-60 слов) интригующий абзац. БЕЗ СПОЙЛЕРОВ.
2.  `synopsis`: Детальный (100-150 слов) конспект. СОДЕРЖИТ СПОЙЛЕРЫ.

ФОРМАТ ОТВЕТА (JSON):
Ты должен вернуть объект со следующими полями:
{schema_description}

ТЕКСТ ГЛАВЫ:
{context.get_chapter_text()}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


# --- ПРОМПТЫ ДЛЯ АНАЛИЗА ПЕРСОНАЖЕЙ ---
def format_character_recon_prompt(chapter_text: str, known_characters_json: str) -> str:
    """Промпт для 'умной разведки': сопоставление с известными и поиск новых."""
    schema_description = generate_human_schema(CharacterReconResult)

    return f"""
Твоя задача - провести "разведку" персонажей в тексте главы.

ИНСТРУКЦИЯ:
1.  Изучи `СПИСОК ИЗВЕСТНЫХ ПЕРСОНАЖЕЙ`.
2.  Внимательно прочитай `ТЕКСТ ГЛАВЫ`.
3.  Сопоставь упоминания в тексте с персонажами из списка.
4.  Определи персонажей, которых нет в списке.
5.  Верни результат в виде JSON-объекта.

ПРАВИЛА:
-   В `mentioned_existing_character_ids` должны попасть только **ID** из предоставленного списка.
-   В `newly_discovered_names` включай только тех, кого точно нет в списке.
-   Игнорируй общие понятия (например, "девушка", "старик").

ФОРМАТ ОТВЕТА (JSON):
Твой ответ должен быть JSON-объектом со следующими полями:
{schema_description}

СПИСОК ИЗВЕСТНЫХ ПЕРСОНАЖЕЙ:
{known_characters_json}

ТЕКСТ ГЛАВЫ:
{chapter_text}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


def format_character_patch_prompt(
        relevant_chars_json: str,
        newly_discovered_names: List[str],
        chapter_text: str,
        volume: int,
        chapter: int
) -> str:
    """Промпт для 'операции': создание 'патча' с изменениями."""
    schema_description = generate_human_schema(CharacterPatchList)
    chapter_id = f"vol_{volume}_chap_{chapter}"

    return f"""
Твоя роль: Ты - система анализа изменений. Твоя задача - создать JSON-"патч" для обновления базы данных персонажей.

ЗАДАЧА:
1. Прочитай `ДАННЫЕ РЕЛЕВАНТНЫХ ПЕРСОНАЖЕЙ` и `СПИСОК НОВЫХ ИМЕН`.
2. Прочитай `ТЕКСТ НОВОЙ ГЛАВЫ`.
3. Создай JSON-объект, содержащий **ТОЛЬКО ИЗМЕНЕНИЯ И ДОБАВЛЕНИЯ**.

ПРАВИЛА ГЕНЕРАЦИИ 'ПАТЧА':
- **ВОЗВРАЩАЙ ТОЛЬКО ИЗМЕНЕНИЯ:** Если существующий персонаж упоминается, но его данные не меняются, НЕ включай для него патч.
- **НОВЫЕ ПЕРСОНАЖИ:** Для каждого имени из `СПИСКА НОВЫХ ИМЕН` создай полный объект-патч.
- **ОБНОВЛЕНИЕ ПОЛЕЙ:** Для существующих персонажей включай в патч только `id` и те поля, которые нужно обновить.
    - `description`: Должно быть **синтезом** старой информации и новых фактов. Может содержать спойлеры.
    - `aliases`: **КРИТИЧЕСКИ ВАЖНО** добавлять в этот список все титулы, звания и альтернативные имена.
    - `chapter_mentions`: **ОБЯЗАТЕЛЬНО** добавь ОДНУ новую запись для `{chapter_id}` с краткой сводкой действий персонажа в этой главе.

ФОРМАТ ОТВЕТА (JSON):
Твой ответ должен быть JSON-объектом со следующей структурой:
{schema_description}

ДАННЫЕ РЕЛЕВАНТНЫХ ПЕРСОНАЖЕЙ:
{relevant_chars_json}

СПИСОК НОВЫХ ИМЕН:
{json.dumps(newly_discovered_names, ensure_ascii=False)}

ТЕКСТ НОВОЙ ГЛАВЫ (Том {volume}, Глава {chapter}):
{chapter_text}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON с 'патчами'):
"""


# --- ПРОМПТЫ ДЛЯ ГЕНЕРАЦИИ СЦЕНАРИЯ ---
def format_scenario_generation_prompt(
    context: ProjectContext,
    character_archive: CharacterArchive,
    chapter_summary: Optional[str] = None
) -> str:
    """
    Формирует промпт для генерации "сырого" сценария главы.
    """
    schema_description = generate_human_schema(RawScenario)
    chapter_text = context.get_chapter_text()
    char_aliases = {char.name: char.aliases for char in character_archive.characters}
    char_aliases_json = json.dumps(char_aliases, ensure_ascii=False, indent=2)

    summary_block = ""
    if chapter_summary:
        summary_block = f"""
КОНСПЕКТ ГЛАВЫ ДЛЯ КОНТЕКСТА:
{chapter_summary}
"""

    return f"""
ТЫ — ИИ-РЕЖИССЕР, который превращает текст книги в сценарий для аудиоспектакля.

ТВОЯ ЗАДАЧА:
Прочитай "Текст главы" и преобразуй его в последовательность JSON-объектов, строго следуя "Правилам разметки" и формату ответа.

{summary_block}

СПИСОК ПЕРСОНАЖЕЙ И ИХ ПСЕВДОНИМОВ:
{char_aliases_json}

ПРАВИЛА РАЗМЕТКИ:
1.  **Типы записей**:
    -   `narration`: Текст, который читает Рассказчик.
    -   `dialogue`: Прямая речь персонажа.
2.  **Определение говорящего (`speaker`):**
    -   Используй основное имя персонажа для реплик (`dialogue`).
    -   Для `narration` `speaker` всегда "Рассказчик", кроме случаев внутреннего монолога.
    -   НИКОГДА не используй "Неизвестен".

ФОРМАТ ОТВЕТА (JSON):
{schema_description}

ТЕКСТ ГЛАВЫ:
{chapter_text}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


def format_ambient_extraction_prompt(
        context: ProjectContext, ambient_library: List[Dict]
) -> str:
    """Формирует промпт для извлечения точек смены эмбиента."""
    schema_description = generate_human_schema(AmbientTransitionList)
    chapter_text = context.get_chapter_text()
    library_str = json.dumps(ambient_library, ensure_ascii=False, indent=2)
    return f"""
ТЫ — ПРОДВИНУТЫЙ ЗВУКОРЕЖИССЕР.
Твоя задача: найти в тексте моменты смены атмосферы и подобрать для них звук из библиотеки.
Если атмосфера не меняется, верни ПУСТОЙ массив `transitions`.

ФОРМАТ ОТВЕТА (JSON):
{schema_description}

БИБЛИОТЕКА ЭМБИЕНТА:
{library_str}

ТЕКСТ ГЛАВЫ:
{chapter_text}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


def format_emotion_analysis_prompt(
        replicas: List[Dict], character_profiles: Dict, emotion_list: List[str]
) -> str:
    """
    Формирует промпт для пакетного анализа эмоций.
    """
    schema_description = generate_human_schema(EmotionMap)
    character_profiles_json = json.dumps(character_profiles, ensure_ascii=False, indent=2)
    replicas_scenario_json = json.dumps(replicas, ensure_ascii=False, indent=2)
    emotion_list_json = json.dumps(emotion_list, ensure_ascii=False)
    return f"""
ТЫ — ГЛАВНЫЙ РЕЖИССЕР АУДИОТЕАТРА.
Твоя задача: для КАЖДОЙ реплики из сценария ВЫБЕРИ ОДНУ эмоцию ИЗ СПИСКА. Учти описание персонажей и контекст.

ФОРМАТ ОТВЕТА (JSON):
{schema_description}

СПИСОК ДОСТУПНЫХ ЭМОЦИЙ:
{emotion_list_json}

ОПИСАНИЯ ПЕРСОНАЖЕЙ:
{character_profiles_json}

СЦЕНАРИЙ РЕПЛИК:
{replicas_scenario_json}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""

