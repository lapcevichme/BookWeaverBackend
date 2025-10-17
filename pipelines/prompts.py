"""
Централизованный модуль для управления и форматирования всех промптов.
"""

import json
from typing import List, Dict, Optional

from core.data_models import (
    CharacterReconResult,
    CharacterPatchList,
    RawScenario,
    AmbientTransitionList,
    EmotionMap, ChapterSummary, CharacterArchive
)
from core.project_context import ProjectContext


def format_summary_generation_prompt(context: ProjectContext) -> str:
    """
    Формирует промпт для генерации двух типов пересказа главы.
    """
    schema = ChapterSummary.model_json_schema()
    chapter_text = context.get_chapter_text()

    return f"""
ТЫ — ОПЫТНЫЙ ЛИТЕРАТУРНЫЙ РЕДАКТОР.

ТВОЯ ЗАДАЧА:
Прочитай "Текст главы" и создай для него ДВА типа пересказа: "тизер" и "конспект".
Верни результат в виде JSON-объекта, который строго соответствует предоставленной схеме.

ОПИСАНИЕ ТИПОВ ПЕРЕСКАЗА:
1.  `teaser`: Краткий (40-60 слов) интригующий абзац для пользователя. Он должен знакомить с завязкой главы, но **НЕ ДОЛЖЕН СОДЕРЖАТЬ СПОЙЛЕРОВ** и не раскрывать ключевые события. Его цель - заинтересовать.
2.  `synopsis`: Детальный (100-150 слов, 2-3 абзаца) конспект для внутреннего использования. Он должен четко и последовательно излагать все ключевые события, повороты сюжета и действия персонажей в главе. Этот текст будет использоваться как контекст для других ИИ-моделей.

JSON SCHEMA:
```json
{json.dumps(schema, indent=2, ensure_ascii=False)}
```

ТЕКСТ ГЛАВЫ:
{chapter_text}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


# --- ПРОМПТЫ ДЛЯ АНАЛИЗА ПЕРСОНАЖЕЙ ---
def format_character_recon_prompt(chapter_text: str, known_characters_json: str) -> str:
    """
    Промпт для 'умной разведки'.
    **ИЗМЕНЕНО:** Теперь работает с UUID персонажей.
    """
    schema = CharacterReconResult.model_json_schema()
    return f"""
Твоя задача - провести "разведку" персонажей в тексте главы.

ИНСТРУКЦИЯ:
1.  Изучи `СПИСОК ИЗВЕСТНЫХ ПЕРСОНАЖЕЙ`. У каждого персонажа есть уникальный `id`, `name` и `aliases`.
2.  Внимательно прочитай `ТЕКСТ ГЛАВЫ`.
3.  Сопоставь упоминания в тексте (имена, псевдонимы, титулы) с персонажами из списка.
4.  Если ты нашел упоминание известного персонажа, ты должен вернуть его **уникальный `id`**.
5.  Если ты нашел персонажа, которого нет в списке, верни его имя.
6.  Верни результат в виде JSON-объекта, соответствующего схеме.

ПРАВИЛА:
-   В `mentioned_existing_character_ids` должны попасть только **уникальные `id`** из предоставленного списка.
-   В `newly_discovered_names` включай только имена тех, кого точно нет в списке.
-   Игнорируй общие понятия (например, "девушка", "старик"), если это не явный псевдоним.

JSON SCHEMA:
```json
{json.dumps(schema, indent=2, ensure_ascii=False)}
```

СПИСОК ИЗВЕСТНЫХ ПЕРСОНАЖЕЙ (с их уникальными ID):
{known_characters_json}

ТЕКСТ ГЛАВЫ:
{chapter_text}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


def format_character_patch_prompt(
        relevant_characters_json: str, newly_discovered_names: List[str], chapter_text: str, volume: int, chapter: int
) -> str:
    """
    Промпт для 'операции': создание 'патча' с изменениями.
    **ВЕРСИЯ 2.1 - Уточнены правила для поля name.**
    """
    schema = CharacterPatchList.model_json_schema()
    chapter_id = f"vol_{volume}_chap_{chapter}"

    new_names_block = ""
    if newly_discovered_names:
        new_names_list_json = json.dumps(newly_discovered_names, ensure_ascii=False, indent=2)
        new_names_block = f"""
СПИСОК НОВЫХ ОБНАРУЖЕННЫХ ИМЕН:
{new_names_list_json}"""

    return f"""
Твоя роль: Ты - система анализа изменений. Твоя задача - создать JSON-"патч" для обновления базы данных персонажей.

ЗАДАЧА:
1. Прочитай `ДАННЫЕ РЕЛЕВАНТНЫХ ПЕРСОНАЖЕЙ`. У каждого есть уникальный `id`.
2. Прочитай `ТЕКСТ НОВОЙ ГЛАВЫ`.
3. Создай JSON-объект, содержащий **ТОЛЬКО ИЗМЕНЕНИЯ И ДОБАВЛЕНИЯ**.

**КЛЮЧЕВОЕ ПРАВИЛО ОБНОВЛЕНИЯ:**
-   **ДЛЯ ОБНОВЛЕНИЯ СУЩЕСТВУЮЩЕГО ПЕРСОНАЖА:** Ты **ОБЯЗАН** включить в патч его точный `id` из предоставленных данных. Поле `name` в этом случае можно опустить.
-   **ДЛЯ СОЗДАНИЯ НОВОГО ПЕРСОНАЖА:** Поле `id` должно отсутствовать или быть `null`. Для нового персонажа поле `name` **ЯВЛЯЕТСЯ ОБЯЗАТЕЛЬНЫМ**.

ПРАВИЛА ГЕНЕРАЦИИ 'ПАТЧА':
- **ВОЗВРАЩАЙ ТОЛЬКО ИЗМЕНЕНИЯ:** Если персонаж упоминается, но его данные не меняются, НЕ включай его в ответ.
- **ОБНОВЛЕНИЕ ПОЛЕЙ:**
    - `description`: Должно быть **синтезом** старой информации и новых фактов. Может содержать спойлеры.
    - `spoiler_free_description`: Краткое описание без спойлеров. Оно также должно быть синтезом старой и новой информации, но оставаться интригующим и не раскрывать ключевые события.
    - `aliases`: **КРИТИЧЕСКИ ВАЖНО** добавлять в этот список все титулы и альтернативные имена. Объединяй новые псевдонимы с уже существующими.
    - `chapter_mentions`: **ОБЯЗАТЕЛЬНО** добавь ОДНУ новую запись для `{chapter_id}` с краткой сводкой действий персонажа в этой главе.
- **ЗАМОРОЖЕННЫЕ ПОЛЯ:** Ты **НЕ ИМЕЕШЬ ПРАВА** изменять поле `first_mention`.

JSON SCHEMA ДЛЯ ТВОЕГО ОТВЕТА (СТРОГО СЛЕДОВАТЬ):
```json
{json.dumps(schema, indent=2, ensure_ascii=False)}
```

ДАННЫЕ СУЩЕСТВУЮЩИХ ПЕРСОНАЖЕЙ (из основной базы):
{relevant_characters_json}
{new_names_block}

ТЕКСТ НОВОЙ ГЛАВЫ (Том {volume}, Глава {chapter}): {chapter_text}

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
    schema = RawScenario.model_json_schema()
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
Прочитай "Текст главы" и преобразуй его в последовательность JSON-объектов, строго следуя "Правилам разметки" и "JSON Schema".

{summary_block}

СПИСОК ПЕРСОНАЖЕЙ И ИХ ПСЕВДОНИМОВ:
{char_aliases_json}

ПРАВИЛА РАЗМЕТКИ:
1.  **Типы записей**:
    -   `narration`: Текст, который читает Рассказчик (описания, мысли персонажей).
    -   `dialogue`: Прямая речь персонажа, обычно начинающаяся с тире (—) или в кавычках.
2.  **Определение говорящего (`speaker`):**
    -   Используй основное имя персонажа из предоставленного списка для реплик (`dialogue`).
    -   **Рассказчик (Narrator):** По умолчанию, `speaker` для ВСЕХ записей типа `narration` должен быть "Рассказчик". Это основной голос, который описывает события, окружение и действия персонажей от третьего лица.
    -   **Внутренний монолог (Исключение):** Если `narration` содержит прямые мысли персонажа (обычно в кавычках, например: «Надеюсь, мой старик в порядке»), ТОЛЬКО ТОГДА `speaker` должен быть именем этого персонажа. Во всех остальных случаях — `speaker` это "Рассказчик".
    -   **КРИТИЧЕСКИ ВАЖНО:** НИКОГДА не используй "Неизвестен". Если говорящего нельзя определить точно, присвой ему временную роль: "Служанка 1", "Торговец".
    -   **ЗАПОМНИ:** В диалоге реплики обычно строго чередуются. Используй конспект, чтобы понять, кто с кем разговаривает.
3.  **Содержимое (`text`):**
    -   Включай в `dialogue` только прямую речь, без слов автора типа "сказал он".
4.  **Эмбиент (`ambient`):**
    -   Всегда начинай с `"ambient": "none"`.

JSON SCHEMA:
```json
{json.dumps(schema, indent=2, ensure_ascii=False)}
```

ТЕКСТ ГЛАВЫ:
{chapter_text}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


def format_ambient_extraction_prompt(
        context: ProjectContext, ambient_library: List[Dict]
) -> str:
    """Формирует промпт для извлечения точек смены эмбиента."""
    schema = AmbientTransitionList.model_json_schema()
    chapter_text = context.get_chapter_text()
    library_str = json.dumps(ambient_library, ensure_ascii=False, indent=2)
    return f"""
ТЫ — ПРОДВИНУТЫЙ ЗВУКОРЕЖИССЕР.
Прочитай "Текст главы" и найди ТОЧНЫЕ моменты смены атмосферы. Для каждого подбери звук из "Библиотеки эмбиента".
Твой ответ должен быть JSON-объектом, соответствующим схеме. Если атмосфера не меняется, верни ПУСТОЙ массив `transitions`.

JSON SCHEMA:
```json
{json.dumps(schema, indent=2, ensure_ascii=False)}
```

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
    ИСПРАВЛЕНО: Формирует промпт для пакетного анализа эмоций.
    Теперь принимает на вход обобщенный список 'replicas'.
    """
    schema = EmotionMap.model_json_schema()
    character_profiles_json = json.dumps(character_profiles, ensure_ascii=False, indent=2)
    replicas_scenario_json = json.dumps(replicas, ensure_ascii=False, indent=2)
    emotion_list_json = json.dumps(emotion_list, ensure_ascii=False)
    return f"""
ТЫ — ГЛАВНЫЙ РЕЖИССЕР АУДИОТЕАТРА.
Проанализируй сценарий и для КАЖДОЙ реплики ВЫБЕРИ ОДНУ эмоцию ИЗ СПИСКА. Учти описание персонажей и контекст.
Верни результат в виде ЕДИНОГО JSON-ОБЪЕКТА, соответствующего схеме.

JSON SCHEMA:
```json
{json.dumps(schema, indent=2, ensure_ascii=False)}
```

СПИСОК ДОСТУПНЫХ ЭМОЦИЙ:
{emotion_list_json}

ОПИСАНИЯ ПЕРСОНАЖЕЙ:
{character_profiles_json}

СЦЕНАРИЙ РЕПЛИК:
{replicas_scenario_json}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""
