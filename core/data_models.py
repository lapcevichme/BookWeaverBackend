"""
Центральный модуль, определяющий все основные структуры данных проекта.
Поддерживает SQLModel для БД и сохраняет метаданные для генерации промптов.
"""
import json
from pathlib import Path
from typing import List, Optional, Dict, Literal, Any
from uuid import UUID, uuid4
from enum import Enum

from pydantic import model_validator, ValidationError
from sqlmodel import SQLModel, Field, Relationship, Column, JSON
from sqlalchemy import Text

# --- Enums ---

class CharacterType(str, Enum):
    PERSON = "person"
    ANIMAL = "animal"
    OBJECT = "object"
    UNKNOWN = "unknown"

# --- Timeline Models (Stored as JSON in DB) ---

class CharacterVoiceState(SQLModel):
    """
    Состояние голоса персонажа в конкретный момент времени (Keyframe).
    """
    age_group: str = Field(..., description="Группа: child, teen, adult, elderly")
    age_exact: Optional[str] = Field(None, description="Точный возраст (строкой), если известен.")
    voice_description: str = Field(..., description="Описание звучания для человека (на русском).")
    search_tags: Optional[str] = Field(None,
                                       description="Теги для поиска голоса (на английском), например: 'young male, raspy'.")
    assigned_voice_id: Optional[str] = Field(None, description="ID голоса в ElevenLabs (заполняется скриптом, не LLM).")

class CharacterVisualState(SQLModel):
    """
    Состояние внешности персонажа в конкретный момент времени (Keyframe).
    """
    description: str = Field(..., description="Общее описание внешности и одежды в этой главе.")
    image_prompt: Optional[str] = Field(None, description="Готовый промпт для генерации (на английском, для SD).")
    reference_image_path: Optional[str] = Field(None, description="Путь к сгенерированному референсу.")

# --- Database Tables ---

class Chapter(SQLModel, table=True):
    """Таблица глав книги."""
    id: str = Field(primary_key=True, description="Global Unique ID: {book_id}:{chapter_id}")
    book_id: str = Field(foreign_key="book.id", index=True)
    
    volume_num: int = Field(default=1)
    chapter_num: int
    chapter_id: str = Field(description="Local ID: vol_X_chap_Y")
    title: Optional[str] = None
    status: str = Field(default="draft") # draft, scenario_ready, audio_ready
    order_index: int = Field(default=0)
    raw_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    
    # Relationships
    book: "Book" = Relationship(back_populates="chapters")
    summary: Optional["ChapterSummary"] = Relationship(back_populates="chapter")
    entries: List["ScenarioEntry"] = Relationship(back_populates="chapter")

class Book(SQLModel, table=True):
    """Основная таблица книги/проекта."""
    id: str = Field(primary_key=True, description="Например: geroi-nashego-vremeni")
    title: str = Field(index=True)
    author: Optional[str] = None
    description: Optional[str] = None
    status: str = Field(default="ongoing")
    cover_image_path: Optional[str] = None
    tags: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    config: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    
    # Relationships
    chapters: List["Chapter"] = Relationship(back_populates="book", sa_relationship_kwargs={"order_by": "Chapter.order_index"})
    characters: List["Character"] = Relationship(back_populates="book")

class ChapterSummary(SQLModel, table=True):
    """Сводка/саммари главы."""
    chapter_id: str = Field(foreign_key="chapter.id", primary_key=True)
    teaser: str = Field(..., description="Краткий (40-60 слов), интригующий тизер для пользователя. БЕЗ спойлеров.")
    synopsis: str = Field(sa_column=Column(Text), description="Детальный (100-150 слов) конспект для внутреннего использования. СОДЕРЖИТ спойлеры.")
    
    # Relationships
    chapter: "Chapter" = Relationship(back_populates="summary")

class Character(SQLModel, table=True):
    """
    Полная информация о персонаже, собранная со всей книги.
    """
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    book_id: str = Field(foreign_key="book.id", index=True)
    name: str = Field(..., index=True)
    entity_type: CharacterType = Field(default=CharacterType.PERSON)
    aliases: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    gender: Optional[str] = Field(None)
    related_identity_id: Optional[UUID] = Field(None)
    role_tier: str = Field(default="background")
    spoiler_free_description: str = Field(..., sa_column=Column(Text))
    description: str = Field(..., sa_column=Column(Text))
    visual_base: Optional[str] = Field(None)
    voice_base: str = Field(default="")
    
    # Timelines stored as JSON
    voice_timeline: Dict[str, CharacterVoiceState] = Field(default_factory=dict, sa_column=Column(JSON))
    visual_timeline: Dict[str, CharacterVisualState] = Field(default_factory=dict, sa_column=Column(JSON))
    chapter_mentions: Dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    
    # Relationships
    book: "Book" = Relationship(back_populates="characters")
    scenario_entries: List["ScenarioEntry"] = Relationship(back_populates="speaker")

class ScenarioEntry(SQLModel, table=True):
    """Представляет одну запись (строку) в финальном сценарии."""
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    chapter_id: str = Field(foreign_key="chapter.id", index=True)
    speaker_id: Optional[UUID] = Field(default=None, foreign_key="character.id")
    
    type: str = Field(..., description="dialogue, narration, thought, image")
    text: Optional[str] = Field(default=None, sa_column=Column(Text))
    tts_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    speaker_name: Optional[str] = None # Имя говорящего (из LLM)
    instruct_prompt: str = Field(default="neutral")
    ambient: str = Field(default="none")
    sfx: Optional[str] = None
    audio_file: Optional[str] = None
    src: Optional[str] = None
    order_index: int = Field(default=0)
    
    # Relationships
    chapter: "Chapter" = Relationship(back_populates="entries")
    speaker: Optional["Character"] = Relationship(back_populates="scenario_entries")

# --- Analysis & Patching Models (Non-Table) ---

class CharacterReconResult(SQLModel):
    """
    Модель для 'умной разведки'.
    """
    mentioned_existing_character_ids: List[UUID] = Field(
        default_factory=list,
        description="Список ID существующих персонажей, которые были упомянуты в тексте."
    )
    newly_discovered_names: List[str] = Field(
        default_factory=list,
        description="Список имен новых персонажей, которых не было в предоставленном списке."
    )

class CharacterPatch(SQLModel):
    """
    Патч изменений для персонажа. Отправляется LLM для анализа одной главы.
    """
    id: Optional[UUID] = Field(None, description="ID существующего персонажа. Если null - создается новый.")
    entity_type: Optional[CharacterType] = Field(
        None,
        description="Тип сущности (person, animal, object). Обязательно для новых."
    )
    naming_reasoning: Optional[str] = Field(
        None,
        description="Объяснение выбора имени. Обязательно, если меняется имя."
    )
    name: Optional[str] = Field(None, description="Каноническое (удобное) имя.")
    role_tier: Optional[str] = Field(None, description="Важность: protagonist, major, minor, background")

    description: Optional[str] = Field(
        None,
        description="ОБЯЗАТЕЛЬНО для новых персонажей. Подробное описание: внешность, характер, профессия, предыстория."
    )
    spoiler_free_description: Optional[str] = Field(
        None,
        description="ОБЯЗАТЕЛЬНО для новых персонажей. Краткое описание роли (1-2 предложения) без спойлеров к будущим событиям."
    )
    aliases: Optional[List[str]] = Field(
        None,
        description="Список титулов, профессий, прозвищ и других имен (например: 'Евнух', 'Господин', 'Супруга', 'Служанка')."
    )
    gender: Optional[str] = None
    visual_base: Optional[str] = Field(
        None,
        description="Базовые визуальные теги на английском (например: '1girl, red hair, green eyes, scar'). Используется как 'чертеж' для сохранения похожести."
    )
    voice_base: Optional[str] = Field(
        None,
        description="Базовые теги голоса на английском (например: 'young male, calm, deep'). Используется для инициализации новых персонажей."
    )

    current_chapter_action: Optional[str] = Field(
        None,
        description="Кратко опиши (1-2 предложения), что именно делал или говорил этот персонаж в ТЕКУЩЕЙ анализируемой главе. Если просто упоминался, напиши 'Упоминается'."
    )

    timeline_voice_update: Optional[CharacterVoiceState] = Field(
        None,
        description="Заполнить, если изменился возраст или голос."
    )
    timeline_visual_update: Optional[CharacterVisualState] = Field(
        None,
        description="Заполнить, если персонаж активно участвует в сцене. Опиши его одежду и позу."
    )

    @model_validator(mode='before')
    def validate_and_fix_data(cls, values):
        if values.get('entity_type') and isinstance(values.get('entity_type'), str):
            values['entity_type'] = values['entity_type'].lower()

        if values.get('id') is None:
            if not values.get('name'):
                raise ValueError("Поле 'name' является обязательным для новых персонажей.")
            if not values.get('description') or len(values.get('description', '')) < 10:
                raise ValueError("Для новых персонажей поле 'description' обязательно.")
            if not values.get('spoiler_free_description') or len(values.get('spoiler_free_description', '')) < 5:
                raise ValueError("Для новых персонажей поле 'spoiler_free_description' обязательно.")
        return values

class CharacterPatchList(SQLModel):
    patches: List[CharacterPatch]

# --- Legacy Containers (For Transition) ---

class ChapterSummaryArchive(SQLModel):
    """DEPRECATED: Используется для миграции старых JSON."""
    summaries: Dict[str, ChapterSummary] = Field(default_factory=dict)

class CharacterArchive(SQLModel):
    """DEPRECATED: Используется для миграции старых JSON."""
    characters: List[Character]
    processed_chapters: List[str] = Field(default_factory=list)

class Scenario(SQLModel):
    """DEPRECATED: Используется для миграции старых JSON."""
    entries: List[ScenarioEntry]

# --- Prompt Helpers ---

class RawChapterSummary(SQLModel):
    teaser: str = Field(..., description="Краткий (40-60 слов), интригующий тизер для пользователя. БЕЗ спойлеров.")
    synopsis: str = Field(..., description="Детальный (100-150 слов) конспект для внутреннего использования. СОДЕРЖИТ спойлеры.")

class RawScenarioEntry(SQLModel):
    id: UUID = Field(default_factory=uuid4)
    type: Literal["dialogue", "narration", "thought", "image"]
    speaker: Optional[str] = Field(None, description="Имя говорящего.")
    text: Optional[str] = Field(None, description="Текст реплики.")
    src: Optional[str] = Field(None, description="Относительный путь к файл (только для типа image).")

class RawScenario(SQLModel):
    scenario: List[RawScenarioEntry]

class LlmRawScenarioEntry(SQLModel):
    type: Literal["dialogue", "narration", "thought", "image"]
    speaker: Optional[str] = None
    text: Optional[str] = None
    src: Optional[str] = Field(None, description="Если это не image, ВООБЩЕ НЕ ВЫВОДИ ключ src")

class LlmRawScenario(SQLModel):
    scenario: List[LlmRawScenarioEntry]

class SoundDesignItem(SQLModel):
    entry_id: str = Field(description="ID записи сценария.")
    ambient: Optional[str] = Field(None, description="ID фонового звука. Если 'none' - ВООБЩЕ НЕ ВЫВОДИ поле.")
    sfx: Optional[str] = Field(None, description="ID звукового эффекта. Если нет - ВООБЩЕ НЕ ВЫВОДИ поле.")

class SoundDesignResult(SQLModel):
    design: List[SoundDesignItem]

class VoiceDirection(SQLModel):
    instruct: str = Field(description="Инструкция для диктора (до 5 слов), например: 'тихо, с грустью'.")
    tts_text: Optional[str] = Field(default=None, description="Текст с тегами (ГЕНЕРИРОВАТЬ ТОЛЬКО ЕСЛИ НУЖНЫ ТЕГИ).")

class EmotionMap(SQLModel):
    emotions: Dict[UUID, VoiceDirection]
