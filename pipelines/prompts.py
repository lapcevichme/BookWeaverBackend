"""
Централизованный модуль для управления и форматирования всех промптов.
"""
# TODO - вероятно на xml теги перейти, говорят что так лучше контекст идет
import json
from typing import List, Dict, Optional

from core.data_models import (
    CharacterArchive,
    CharacterReconResult,
    CharacterPatchList,
    EmotionMap, RawChapterSummary, ChapterSummary, LlmRawScenario
)
from core.project_context import ProjectContext
from utils.prompt_utils import generate_human_schema


def format_volume_summary_prompt(volume_num: int, chapter_summaries: List[str]) -> str:
    """
    Промпт для создания 'Рекапа' целого тома на основе пересказов его глав.
    """
    joined_summaries = "\n\n".join(chapter_summaries)

    return f"""
ТЫ — ГЛАВНЫЙ РЕДАКТОР КНИЖНОЙ СЕРИИ.
Мы закончили обработку ТОМА {volume_num}.

ТВОЯ ЗАДАЧА:
Напиши **ГЛОБАЛЬНОЕ САММАРИ (Recap)** для всего этого тома.
Твой текст будет использоваться как контекст для следующего тома, чтобы ИИ не забыл, что произошло.

ИНСТРУКЦИЯ:
1. Прочитай краткие содержания всех глав ниже.
2. Выдели основные сюжетные арки, ключевые поворотные моменты и итог тома.
3. Игнорируй мелкие детали ("попил чаю"), фокусируйся на глобальных изменениях (кто умер, кто влюбился, куда уехали, как изменился мир).
4. Объем: 300-500 слов.

ПЕРЕСКАЗЫ ГЛАВ ТОМА {volume_num}:
{joined_summaries}

ТВОЙ ОТВЕТ (ТОЛЬКО ТЕКСТ САММАРИ):
"""


def format_summary_generation_prompt(
        context: ProjectContext,
        previous_summaries: list[ChapterSummary],
        prev_volume_summary: Optional[str] = None
) -> str:
    """Формирует промпт для генерации пересказа главы."""
    schema_description = generate_human_schema(RawChapterSummary)

    # Формируем блок "Глобальный контекст"
    global_context_block = ""
    if prev_volume_summary:
        global_context_block = f"""
ГЛОБАЛЬНЫЙ КОНТЕКСТ (СОБЫТИЯ ПРЕДЫДУЩЕГО ТОМА)
В прошлом томе произошло следующее:
{prev_volume_summary}
"""

    previous_context_str = ""
    if previous_summaries:
        context_lines = ["КОНТЕКСТ ПРЕДЫДУЩИХ ГЛАВ (ДЛЯ СВЯЗНОСТИ):"]
        for summary in previous_summaries:
            context_lines.append(f"Глава {summary.chapter_id}:\n{summary.synopsis}\n")
        previous_context_str = "\n".join(context_lines)

    return f"""
ТЫ — ОПЫТНЫЙ ЛИТЕРАТУРНЫЙ РЕДАКТОР.

ТВОЯ ЗАДАЧА:
Прочитай "Текст главы" и создай для него ДВА типа пересказа: "тизер" и "конспект".
УЧИТЫВАЙ КОНТЕКСТ ПРЕДЫДУЩИХ ГЛАВ, если он предоставлен.

{global_context_block}

{previous_context_str}

**!!! ВАЖНЫЕ ПРАВИЛА БЕЗОПАСНОСТИ !!!**
**- Избегай прямого упоминания и детального описания сцен насилия или сексуального контента.**
**- Используй нейтральные и литературные формулировки.**

ФОРМАТ ОТВЕТА (JSON):
{schema_description}

ТЕКСТ ГЛАВЫ:
{context.get_chapter_text()}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


# --- ПРОМПТЫ ДЛЯ АНАЛИЗА ПЕРСОНАЖЕЙ ---
def format_character_recon_prompt(chapter_text: str, known_characters_json: str,
                                  chapter_summary: Optional[str] = None) -> str:
    """
    Промпт для 'умной разведки'.
    Теперь включает контекст саммари для устранения неоднозначностей.
    """
    schema_description = generate_human_schema(CharacterReconResult)

    summary_block = ""
    if chapter_summary:
        summary_block = f"""
=== КОНТЕКСТ ГЛАВЫ ===
Используй это краткое содержание как "истину" для разрешения споров о именах.
Если в тексте написано "Служанка", а в саммари сказано, что это Маомао - используй имя "Маомао".
САММАРИ:
{chapter_summary}
"""

    return f"""
Твоя задача - провести "разведку" персонажей в тексте главы.

ИНСТРУКЦИЯ:
1.  Изучи `СПИСОК ИЗВЕСТНЫХ ПЕРСОНАЖЕЙ`.
2.  Внимательно прочитай `ТЕКСТ ГЛАВЫ`.
3.  Сопоставь упоминания в тексте с персонажами из списка.
4.  Определи персонажей, которых нет в списке.

{summary_block}

ПРАВИЛА:
-   В `mentioned_existing_character_ids` должны попасть только **ID** из списка.
-   В `newly_discovered_names` включай только тех, кого точно нет.
-   Игнорируй общие понятия ("девушка", "солдат"), если они не являются важными действующими лицами согласно Саммари.

ФОРМАТ ОТВЕТА (JSON):
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
    """
    Промпт для создания патчей.
    ОБЪЕДИНЕНАЯ ЛОГИКА: Hierarchy Protection + Detailed Timeline Instructions + Entity Types.
    """
    schema_description = generate_human_schema(CharacterPatchList)

    return f"""
Твоя роль: Ты - система анализа изменений персонажей (State Tracker).
Твоя задача - создать JSON-"патч" для обновления базы данных.

ЗАДАЧА:
1. Прочитай `ДАННЫЕ ПЕРСОНАЖЕЙ` и `ТЕКСТ НОВОЙ ГЛАВЫ`.
2. Создай объект патчей для каждого активного или нового персонажа.

=== 1. ТИПЫ СУЩНОСТЕЙ (Entity Types) ===
Для каждого нового или существующего персонажа укажи правильный `entity_type`.

- **person**: Люди, гуманоиды, демоны (если похожи на людей). Основные актеры.
- **animal**: Животные или монстры (ТОЛЬКО если есть кличка или активное участие).

**СПИСОК ИСКЛЮЧЕНИЙ (СТРОГО ИГНОРИРОВАТЬ):**
- Неодушевленные предметы (Какао, Яд, Письма, Артефакты).
- Абстрактные понятия (Императорский Двор, Судьба).
- Группы без конкретных личностей (Толпа, Солдаты).
**ИНСТРУКЦИЯ:** Даже если "Какао" или "Яд" является причиной событий, НЕ СОЗДАВАЙ для них запись. Мы ищем только живых актеров.

=== 2. ПРАВИЛА ВЫБОРА ИМЕНИ (Naming Protocol) ===
Мы используем строгую иерархию имен. Твоя цель — Уровень 1.
- **Уровень 1 (Идеально):** Имя Собственное / Кличка. (Примеры: "Хоннян", "Мисато", "Гарри").
- **Уровень 2 (Допустимо):** Титул + Имя. (Примеры: "Доктор Ли", "Командующая Кацураги").
- **Уровень 3 (Только если нет выбора):** Профессия / Роль. (Примеры: "Доктор", "Служанка", "Деревенщина 1").

**ПРАВИЛА ЗАМЕНЫ:**
- РАЗРЕШЕНО повышать уровень (Уровень 2 -> Уровень 1): "Командующая Кацураги" -> "Мисато".
- ЗАПРЕЩЕНО понижать уровень (Уровень 1 -> Уровень 3): "Хоннян" -> "Доктор". Даже если в тексте её 100 раз назвали "Доктор", оставляй имя "Хоннян".

=== 3. ТАЙМЛАЙНЫ (State Timelines) - КЛЮЧЕВОЙ МОМЕНТ ===
Заполняй эти поля ТОЛЬКО если есть РЕАЛЬНЫЕ изменения. Иначе оставь `null`.

- **timeline_voice_update (ГОЛОС/ВОЗРАСТ):**
  - Заполняй, если прошел "таймскип" или голос изменился.
  - `search_tags`: 5-7 тегов на АНГЛИЙСКОМ (например: "old man, raspy, wise").

- **timeline_visual_update (ВНЕШНОСТЬ):**
  - Заполняй, если изменилась одежда (надел доспехи) или тело (шрамы, прическа).
  - **СТИЛЬ:** НЕ пиши слова 'realistic', 'anime', '4k'. Описывай ТОЛЬКО контент (одежда, поза, окружение).
  - **БЕЗОПАСНОСТЬ:** Заменяй чувствительные роли на визуальные синонимы (Slave -> Servant).
  - `image_prompt`: Напиши готовый промпт на АНГЛИЙСКОМ (например: "medieval knight, shining armor, blood on face, holding sword").

- **role_tier:** Оцени важность персонажа строго одним из слов:
  - 'protagonist' (Главный герой)
  - 'major' (Значимый персонаж сюжета)
  - 'minor' (Второстепенный, эпизодический)
  - 'background' (Массовка, фоновый)
  
ФОРМАТ ОТВЕТА (JSON):
{schema_description}

ДАННЫЕ ПЕРСОНАЖЕЙ (Текущее состояние):
{relevant_chars_json}

СПИСОК НОВЫХ ИМЕН (Кандидаты):
{json.dumps(newly_discovered_names, ensure_ascii=False)}

ТЕКСТ НОВОЙ ГЛАВЫ (Том {volume}, Глава {chapter}):
{chapter_text}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


# --- ПРОМПТЫ ДЛЯ ГЕНЕРАЦИИ СЦЕНАРИЯ ---
def format_scenario_generation_prompt(
        text_chunk: str,
        character_archive: CharacterArchive,
        chapter_summary: Optional[str] = None,
        chunk_index: int = 0,
        total_chunks: int = 1
) -> str:
    """
    Формирует промпт для генерации "сырого" сценария главы (или её части).
    """
    schema_description = generate_human_schema(LlmRawScenario)

    character_profiles = [
        f"- {char.name}: {char.spoiler_free_description}"
        for char in character_archive.characters
    ]
    character_profiles_block = "\n".join(character_profiles)

    summary_block = ""
    if chapter_summary:
        summary_block = f"""
КОНСПЕКТ ГЛАВЫ (ГЛОБАЛЬНЫЙ КОНТЕКСТ):
{chapter_summary}
"""

    context_info = ""
    if total_chunks > 1:
        context_info = f"ВНИМАНИЕ: Это ЧАСТЬ {chunk_index + 1} из {total_chunks} всей главы. Не пытайся завершить сюжет, если текст обрывается — просто обработай то, что видишь."

    return f"""
ТЫ — ИИ-РЕЖИССЕР, который превращает текст книги в детализированный сценарий для аудиоспектакля.
Твоя задача — прочитать текст и скрупулезно преобразовать его в последовательность JSON-объектов.

{context_info}

{summary_block}

КРАТКИЕ ОПИСАНИЯ ПЕРСОНАЖЕЙ:
{character_profiles_block}

ПРАВИЛА РАЗМЕТКИ СЦЕНАРИЯ:

1.  **Типы записей (`type`):**
    -   `narration`: Текст, который читает Рассказчик.
    -   `dialogue`: Прямая речь персонажа.
    -   **ВНИМАНИЕ:** Внутренние монологи (мысли персонажа, часто в кавычках « ») размечай как `dialogue`, а не `narration`.

2.  **Определение говорящего (`speaker`):**
    -   Для `dialogue` (включая монологи) используй основное, каноническое имя персонажа.
    -   Для `narration` `speaker` всегда должен быть "Рассказчик".
    -   **Обработка неизвестных:** Если говорящего действительно невозможно определить по контексту (например, реплика из толпы), используй краткую и осмысленную роль (например "Голос из толпы", "Служанка" и прочее). Если действительно невозможно понять, пиши предположительный пол персонажа, в худшем - "Неизвестно".

3.  **Очистка текста (`text`):**
    -   Текст реплик (`dialogue`) должен быть ПОЛНОСТЬЮ очищен от слов автора (например, "сказал он", "прошептала она", "подумал Джон").
    -   Текст должен содержать только то, что произносится вслух или мыслится.

4.  **Критически важное правило разделения (для звукорежиссера):**
    -   Если внутри одного абзаца повествования происходит явное звуковое событие (стук в дверь, звон мечей, крик на фоне) или резкая смена обстановки, **ОБЯЗАТЕЛЬНО раздели этот абзац на два или более блока `narration`**.
    -   Событие должно оказаться в начале нового блока. Это КЛЮЧЕВОЙ момент для точной расстановки звуковых эффектов.

ФОРМАТ ОТВЕТА (строго JSON):
{schema_description}

ТЕКСТ ДЛЯ ОБРАБОТКИ:
{text_chunk}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


def format_sound_design_prompt(
        scenario_json: str,
        ambient_menu: str,
        sfx_menu: str,
        schema_description: str
) -> str:
    """
    Формирует промпт для звукового дизайна (Ambient + SFX).
    Принимает уже сериализованные JSON-строки меню и сценария,
    а также описание схемы валидации.
    """
    return f"""
ТЫ — ЗВУКОРЕЖИССЕР АУДИОКНИГИ.
Твоя задача — выбрать подходящие звуки из ПРЕДОСТАВЛЕННОГО МЕНЮ.

ВХОДНЫЕ ДАННЫЕ:
1. Сценарий (фрагменты текста).
2. Меню Ambient (фоновые петли).
3. Меню SFX (короткие звуки).

ИНСТРУКЦИЯ:
Для каждой записи сценария (`entry_id`) определи:
- `ambient`: ID фонового звука. Если сцена изменилась — выбери новый. Если тишина — "none".
- `sfx`: ID короткого звука. ВНИМАНИЕ: Выбирай ТОЛЬКО если в тексте есть ЯВНОЕ действие (удар, крик, дверь), совпадающее со звуком из МЕНЮ SFX.

!!! ВАЖНО: ПРИНЦИП БЕЛОГО СПИСКА !!!
- Ты НЕ имеешь права придумывать свои ID.
- Если в тексте "разбилось стекло", но в МЕНЮ SFX нет звука стекла — оставь поле `sfx` пустым (null). НЕ выдумывай "glass_break".
- Используй только ID, перечисленные ниже.

МЕНЮ AMBIENT (ДОСТУПНЫЕ): {ambient_menu}
МЕНЮ SFX (ДОСТУПНЫЕ): {sfx_menu}

СЦЕНАРИЙ:
{scenario_json}

ФОРМАТ ОТВЕТА (JSON):
{schema_description}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""


def format_emotion_analysis_prompt(
        replicas: List[Dict],
        character_profiles: Dict,
        character_emotions: List[str],
        narrator_styles: List[str]
) -> str:
    """
    Формирует промпт для пакетного анализа эмоций с разделением на Narrator/Character.
    """
    schema_description = generate_human_schema(EmotionMap)

    character_profiles_json = json.dumps(character_profiles, ensure_ascii=False, indent=2)
    replicas_scenario_json = json.dumps(replicas, ensure_ascii=False, indent=2)

    chars_tags_json = json.dumps(character_emotions, ensure_ascii=False)
    narrator_tags_json = json.dumps(narrator_styles, ensure_ascii=False)

    return f"""
ТЫ — ГЛАВНЫЙ РЕЖИССЕР АУДИОКНИГИ.
Твоя задача: назначить тег стиля/эмоции (`emotion`) для КАЖДОЙ строки сценария.

!!! ВАЖНОЕ ПРАВИЛО РАЗДЕЛЕНИЯ !!!

1. ЕСЛИ speaker == "Рассказчик":
   - Ты выбираешь тег ИСКЛЮЧИТЕЛЬНО из списка `NARRATOR STYLES`.
   - Анализируй атмосферу сцены: спокойная, напряженная (suspense), быстрая (action), грустная.
   - Не используй эмоции типа "плачет" или "смеется" для рассказчика, если это не указано явно.

2. ЕСЛИ speaker — Имя Персонажа:
   - Ты выбираешь тег ИСКЛЮЧИТЕЛЬНО из списка `CHARACTER EMOTIONS`.
   - Анализируй смысл реплики и реакцию персонажа.

=== СПИСКИ ДОСТУПНЫХ ТЕГОВ ===
[NARRATOR STYLES]:
{narrator_tags_json}

[CHARACTER EMOTIONS]:
{chars_tags_json}

=== КОНТЕКСТ ===
ОПИСАНИЯ ПЕРСОНАЖЕЙ:
{character_profiles_json}

=== ЗАДАНИЕ ===
СЦЕНАРИЙ (ВХОДНЫЕ ДАННЫЕ):
{replicas_scenario_json}

ФОРМАТ ОТВЕТА (JSON):
Ты ОБЯЗАН вернуть объект с единственным полем "emotions".
Пример структуры:
{{
  "emotions": {{
    "uuid-1": "angry",
    "uuid-2": "neutral",
    "uuid-3": "whisper"
  }}
}}

Схема валидации:
{schema_description}

ТВОЙ ОТВЕТ (ТОЛЬКО JSON):
"""

