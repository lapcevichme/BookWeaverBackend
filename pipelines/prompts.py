"""
Централизованный модуль для управления и форматирования всех промптов.
**ВЕРСИЯ 3.1 - Финальная оптимизация**
"""
import json
from typing import List, Dict, Optional

from core.data_models import (
    CharacterArchive,
    CharacterReconResult,
    CharacterPatchList,
    AmbientTransitionList,
    EmotionMap, RawChapterSummary, ChapterSummary, LlmRawScenario
)
from core.project_context import ProjectContext
from utils.prompt_utils import generate_human_schema


def format_summary_generation_prompt(
        context: ProjectContext,
        previous_summaries: list[ChapterSummary]
) -> str:
    """
    Формирует промпт для генерации пересказа главы,
    учитывая контекст предыдущих глав.
    Fixme!!! Тут стоит фильтр, его надо бы убирать.
    """
    schema_description = generate_human_schema(RawChapterSummary)

    previous_context_str = ""
    if previous_summaries:
        context_lines = ["КОНТЕКСТ ПРЕДЫДУЩИХ ГЛАВ (ДЛЯ СПРАВКИ):"]
        for summary in previous_summaries:
            context_lines.append(f"Глава {summary.chapter_id}:\n{summary.synopsis}\n")
        previous_context_str = "\n".join(context_lines)
    return f"""
ТЫ — ОПЫТНЫЙ ЛИТЕРАТУРНЫЙ РЕДАКТОР.

ТВОЯ ЗАДАЧА:
Прочитай "Текст главы" и создай для него ДВА типа пересказа: "тизер" и "конспект".
**Крайне важно: УЧИТЫВАЙ КОНТЕКСТ ПРЕДЫДУЩИХ ГЛАВ, если он предоставлен.** Это поможет тебе понять общую сюжетную линию и правильно расставить акценты.

{previous_context_str}

**!!! ВАЖНЫЕ ПРАВИЛА БЕЗОПАСНОСТИ !!!**
**- Избегай прямого упоминания и детального описания сцен насилия, жестокости или сексуального контента.**
**- Используй нейтральные и литературные формулировки. Вместо прямолинейных терминов (особенно связанных с сексуальностью) используй эвфемизмы или описывай намерения персонажей более обтекаемо.**
**- Сосредоточься на сюжете, мотивации персонажей и развитии событий, а не на шокирующих деталях.**

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
# --- ПРОМПТЫ ДЛЯ ГЕНЕРАЦИИ СЦЕНАРИЯ ---
def format_scenario_generation_prompt(
        context: ProjectContext,
        character_archive: CharacterArchive,
        chapter_summary: Optional[str] = None
) -> str:
    """
    Формирует промпт для генерации "сырого" сценария главы.
    Версия 4.5 - Улучшена обработка монологов и стиля повествования.
    """
    schema_description = generate_human_schema(LlmRawScenario)
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
ТЫ — ИИ-РЕЖИССЕР, который превращает текст книги в детализированный сценарий для аудиоспектакля.
Твоя задача — прочитать текст главы и скрупулезно преобразовать его в последовательность JSON-объектов, строго следуя правилам.

{summary_block}

СПИСОК ПЕРСОНАЖЕЙ И ИХ ПСЕВДОНИМОВ (ДЛЯ СПРАВКИ):
{char_aliases_json}

ПРАВИЛА РАЗМЕТКИ СЦЕНАРИЯ:

1.  **Типы записей (`type`):**
    -   `narration`: Текст, который читает Рассказчик.
    -   `dialogue`: Прямая речь персонажа.
    -   **ВНИМАНИЕ:** Внутренние монологи (мысли персонажа, часто в кавычках « ») размечай как `dialogue`, а не `narration`. Это критически важно для их последующей звуковой обработки.

2.  **Определение говорящего (`speaker`):**
    -   Для `dialogue` (включая монологи) используй основное, каноническое имя персонажа.
    -   Для `narration` `speaker` всегда должен быть "Рассказчик".
    -   **Обработка неизвестных:** Если говорящего действительно невозможно определить по контексту (например, реплика из толпы), используй краткую и осмысленную роль (например, "Стражник", "Торговец", "Голос из толпы"). НИКОГДА не используй псевдонимы или общее слово "Неизвестен".

3.  **Очистка текста (`text`):**
    -   Текст реплик (`dialogue`) должен быть ПОЛНОСТЬЮ очищен от слов автора (например, "сказал он", "прошептала она", "подумал Джон").
    -   Текст должен содержать только то, что произносится вслух или мыслится.

4.  **Критически важное правило разделения (для звукорежиссера):**
    -   Если внутри одного абзаца повествования происходит явное звуковое событие (стук в дверь, звон мечей, крик на фоне) или резкая смена обстановки, **ОБЯЗАТЕЛЬНО раздели этот абзац на два или более блока `narration`**.
    -   Событие должно оказаться в начале нового блока. Это КЛЮЧЕВОЙ момент для точной расстановки звуковых эффектов.

5.  **Стилистический совет:**
    -   Старайся объединять короткие, идущие подряд предложения Рассказчика в один логический блок `narration`, если они описывают одну сцену и между ними нет смены действия. Это делает повествование более плавным.

ФОРМАТ ОТВЕТА (строго JSON, соответствующий этой структуре):
{schema_description}

ТЕКСТ ГЛАВЫ:
{chapter_text}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


def format_ambient_extraction_prompt(
        raw_scenario_json: str, ambient_library: List[Dict]
) -> str:
    """
    Формирует промпт для извлечения точек смены эмбиента.
    Принимает готовый сценарий в JSON и работает с UUID.
    """
    schema_description = generate_human_schema(AmbientTransitionList)
    library_str = json.dumps(ambient_library, ensure_ascii=False, indent=2)
    return f"""
ТЫ — ПРОДВИНУТЫЙ ЗВУКОРЕЖИССЕР.
Твоя задача: изучить готовый сценарий и определить, с какой строки (entry) должна начаться смена атмосферы.

ИНСТРУКЦИЯ:
1. Прочитай СЦЕНАРИЙ. Каждая запись в нем имеет уникальный `id`.
2. Проанализируй БИБЛИОТЕКУ ЭМБИЕНТА.
3. Определи моменты, где меняется атмосфера.
4. В ответе укажи `entry_id` той записи, с которой должен начаться новый звук.
5. Если атмосфера в главе не меняется, верни ПУСТОЙ массив `transitions`.

ФОРМАТ ОТВЕТА (JSON):
{schema_description}

БИБЛИОТЕКА ЭМБИЕНТА:
{library_str}

СЦЕНАРИЙ (ВХОДНЫЕ ДАННЫЕ):
{raw_scenario_json}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


def format_emotion_analysis_prompt(
        replicas: List[Dict], character_profiles: Dict, emotion_list: List[str]
) -> str:
    """
    Формирует промпт для пакетного анализа эмоций.
    Работает с UUID в качестве `id` реплик.
    """
    schema_description = generate_human_schema(EmotionMap)
    character_profiles_json = json.dumps(character_profiles, ensure_ascii=False, indent=2)
    replicas_scenario_json = json.dumps(replicas, ensure_ascii=False, indent=2)
    emotion_list_json = json.dumps(emotion_list, ensure_ascii=False)
    return f"""
ТЫ — ГЛАВНЫЙ РЕЖИССЕР АУДИОТЕАТРА.
Твоя задача: для КАЖДОЙ реплики из сценария ВЫБЕРИ ОДНУ эмоцию ИЗ СПИСКА.
В твоем ответе ключом в словаре `emotions` должен быть `id` реплики из входных данных.

ФОРМАТ ОТВЕТА (JSON):
{schema_description}

СПИСОК ДОСТУПНЫХ ЭМОЦИЙ:
{emotion_list_json}

ОПИСАНИЯ ПЕРСОНАЖЕЙ:
{character_profiles_json}

СЦЕНАРИЙ РЕПЛИК (ВХОДНЫЕ ДАННЫЕ):
{replicas_scenario_json}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""
