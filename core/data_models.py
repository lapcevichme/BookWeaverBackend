"""
Центральный модуль, определяющий все основные структуры данных проекта.
Поддерживает SQLModel для БД. В этой архитектуре каждая книга имеет свою БД.
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
    age_group: str = Field(..., description="Группа: child, teen, adult, elderly")
    age_exact: Optional[str] = Field(None, description="Точный возраст (строкой), если известен.")
    voice_description: str = Field(..., description="Описание звучания для человека (на русском).")
    search_tags: Optional[str] = Field(None, description="Теги для поиска голоса (на английском).")
    assigned_voice_id: Optional[str] = Field(None, description="ID голоса в ElevenLabs.")

class CharacterVisualState(SQLModel):
    description: str = Field(..., description="Общее описание внешности и одежды в этой главе.")
    image_prompt: Optional[str] = Field(None, description="Готовый промпт для генерации (на английском).")
    reference_image_path: Optional[str] = Field(None, description="Путь к сгенерированному референсу.")

# --- Database Tables (Local to each Book DB) ---

class Book(SQLModel, table=True):
    """Метаданные проекта (в каждой БД будет ровно одна запись)."""
    id: str = Field(primary_key=True)
    title: str = Field(index=True)
    author: Optional[str] = None
    description: Optional[str] = None
    status: str = Field(default="ongoing")
    cover_image_path: Optional[str] = None
    tags: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    config: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    
    # Relationships
    chapters: List["Chapter"] = Relationship(back_populates="book")
    characters: List["Character"] = Relationship(back_populates="book")

class Chapter(SQLModel, table=True):
    """Таблица глав книги."""
    id: str = Field(primary_key=True, description="Local ID: vol_X_chap_Y")
    book_id: str = Field(foreign_key="book.id", index=True)
    
    volume_num: int = Field(default=1)
    chapter_num: int
    title: Optional[str] = None
    status: str = Field(default="draft")
    order_index: int = Field(default=0)
    raw_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    
    # Relationships
    book: "Book" = Relationship(back_populates="chapters")
    summary: Optional["ChapterSummary"] = Relationship(back_populates="chapter")
    entries: List["ScenarioEntry"] = Relationship(back_populates="chapter")

class ChapterSummary(SQLModel, table=True):
    """Сводка/саммари главы."""
    chapter_id: str = Field(foreign_key="chapter.id", primary_key=True)
    teaser: str = Field(..., description="Краткий тизер без спойлеров.")
    synopsis: str = Field(sa_column=Column(Text), description="Детальный конспект.")
    
    # Relationships
    chapter: "Chapter" = Relationship(back_populates="summary")

class VolumeSummary(SQLModel):
    """Глобальный пересказ целого тома."""
    volume_num: int
    summary: str = Field(description="Сжатый пересказ событий всего тома.")

class Character(SQLModel, table=True):
    """Персонажи книги."""
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    book_id: str = Field(foreign_key="book.id", index=True)
    
    name: str = Field(..., index=True)
    entity_type: CharacterType = Field(default=CharacterType.PERSON)
    aliases: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    gender: Optional[str] = Field(None)
    role_tier: str = Field(default="background")
    spoiler_free_description: str = Field(..., sa_column=Column(Text))
    description: str = Field(..., sa_column=Column(Text))
    visual_base: Optional[str] = Field(None)
    voice_base: str = Field(default="")
    
    voice_timeline: Dict[str, CharacterVoiceState] = Field(default_factory=dict, sa_column=Column(JSON))
    visual_timeline: Dict[str, CharacterVisualState] = Field(default_factory=dict, sa_column=Column(JSON))
    chapter_mentions: Dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    
    # Relationships
    book: "Book" = Relationship(back_populates="characters")
    scenario_entries: List["ScenarioEntry"] = Relationship(back_populates="speaker")

class ScenarioEntry(SQLModel, table=True):
    """Записи сценария."""
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    chapter_id: str = Field(foreign_key="chapter.id", index=True)
    speaker_id: Optional[UUID] = Field(default=None, foreign_key="character.id")
    
    type: str = Field(..., description="dialogue, narration, thought, image")
    text: Optional[str] = Field(default=None, sa_column=Column(Text))
    tts_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    speaker_name: Optional[str] = None
    instruct_prompt: str = Field(default="neutral")
    ambient: str = Field(default="none")
    sfx: Optional[str] = None
    audio_file: Optional[str] = None
    src: Optional[str] = None
    order_index: int = Field(default=0)
    
    # Relationships
    chapter: "Chapter" = Relationship(back_populates="entries")
    speaker: Optional["Character"] = Relationship(back_populates="scenario_entries")

# --- Non-Table Models (Prompts/API) ---

class CharacterReconResult(SQLModel):
    mentioned_existing_character_ids: List[UUID] = Field(default_factory=list)
    newly_discovered_names: List[str] = Field(default_factory=list)

class CharacterPatch(SQLModel):
    id: Optional[UUID] = None
    entity_type: Optional[CharacterType] = None
    naming_reasoning: Optional[str] = None
    name: Optional[str] = None
    role_tier: Optional[str] = None
    description: Optional[str] = None
    spoiler_free_description: Optional[str] = None
    aliases: Optional[List[str]] = None
    gender: Optional[str] = None
    visual_base: Optional[str] = None
    voice_base: Optional[str] = None
    current_chapter_action: Optional[str] = None
    timeline_voice_update: Optional[CharacterVoiceState] = None
    timeline_visual_update: Optional[CharacterVisualState] = None

    @model_validator(mode='before')
    def validate_and_fix_data(cls, values):
        if values.get('entity_type') and isinstance(values.get('entity_type'), str):
            values['entity_type'] = values['entity_type'].lower()
        return values

class CharacterPatchList(SQLModel):
    patches: List[CharacterPatch]

class RawChapterSummary(SQLModel):
    teaser: str = Field(...)
    synopsis: str = Field(...)

class RawScenarioEntry(SQLModel):
    id: UUID = Field(default_factory=uuid4)
    type: Literal["dialogue", "narration", "thought", "image"]
    speaker: Optional[str] = None
    text: Optional[str] = None
    src: Optional[str] = None

class RawScenario(SQLModel):
    scenario: List[RawScenarioEntry]

class LlmRawScenarioEntry(SQLModel):
    type: Literal["dialogue", "narration", "thought", "image"]
    speaker: Optional[str] = None
    text: Optional[str] = None
    src: Optional[str] = None

class LlmRawScenario(SQLModel):
    scenario: List[LlmRawScenarioEntry]

class SoundDesignItem(SQLModel):
    entry_id: str = Field(...)
    ambient: Optional[str] = None
    sfx: Optional[str] = None

class SoundDesignResult(SQLModel):
    design: List[SoundDesignItem]

class VoiceDirection(SQLModel):
    instruct: str = Field(...)
    tts_text: Optional[str] = None

class EmotionMap(SQLModel):
    emotions: Dict[UUID, VoiceDirection]

# Legacy
class ChapterSummaryArchive(SQLModel):
    summaries: Dict[str, ChapterSummary] = Field(default_factory=dict)
class CharacterArchive(SQLModel):
    characters: List[Character]
    processed_chapters: List[str] = Field(default_factory=list)
class Scenario(SQLModel):
    entries: List[ScenarioEntry]

class ManifestMeta(SQLModel):
    title: str = "Без названия"
    author: Optional[str] = "Неизвестный автор"
    description: Optional[str] = ""
    tags: List[str] = Field(default_factory=list)
    status: str = "ongoing"

class ManifestChapterEntry(SQLModel):
    order: int
    title: str
    vol: int = 1
    chap: int
    status: str = "draft"
    id: Optional[str] = None

class ManifestConfig(SQLModel):
    default_narrator_voice: str = "narrator_default"
    character_voices: Dict[UUID, str] = Field(default_factory=dict)

class BookManifest(SQLModel):
    project_id: str
    meta: ManifestMeta
    structure: List[ManifestChapterEntry] = Field(default_factory=list)
    config: ManifestConfig = Field(default_factory=ManifestConfig)

    @classmethod
    def load(cls, path: Path) -> "BookManifest":
        if not path.exists(): raise FileNotFoundError(f"Manifest not found: {path}")
        return cls.model_validate_json(path.read_text("utf-8"))
