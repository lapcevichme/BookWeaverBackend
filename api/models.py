from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Dict, Any
from enum import Enum
from uuid import UUID

# --- Server State ---

class ServerStateEnum(str, Enum):
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    ERROR = "ERROR"

class ServerStatus(BaseModel):
    status: ServerStateEnum
    message: str = ""

# --- Tasks ---

class ChapterTaskRequest(BaseModel):
    book_name: str
    volume_num: int
    chapter_num: int

class BookTaskRequest(BaseModel):
    book_name: str

class TaskStatusResponse(BaseModel):
    task_id: str
    status: Literal["queued", "processing", "complete", "failed"]
    progress: float
    stage: str
    message: str

# --- Artifacts & Metadata ---

class BookArtifactName(str, Enum):
    MANIFEST = "manifest"
    CHARACTER_ARCHIVE = "character_archive"
    CHAPTER_SUMMARIES = "summary_archive"

class ChapterArtifactName(str, Enum):
    SCENARIO = "scenario"
    SUBTITLES = "subtitles"
    CACHE_RAW_SCENARIO = "cache_raw_scenario"
    CACHE_AMBIENT = "cache_ambient"

class AmbientMetadata(BaseModel):
    id: str
    description: str
    tags: List[str]

class BookStatusResponse(BaseModel):
    book_name: str
    total_chapters: int = 0
    chapters_with_scenario: int = 0
    chapters_with_tts: int = 0
    is_ready_for_export: bool = Field(
        False,
        description="True, если хотя бы одна глава полностью готова (сценарий + TTS)."
    )

# --- UI / Streaming ---

class PlaylistEntry(BaseModel):
    """Одна запись в плейлисте главы, соответствует одной реплике."""
    id: Optional[UUID] = None
    audio_file: Optional[str] = Field(None, description="Имя аудиофайла.")
    text: Optional[str] = Field(None, description="Текст реплики.")
    speaker: str = Field(description="Имя говорящего персонажа.")
    ambient: Optional[str] = Field(None, description="ID эмбиент-звука.")

class ChapterPlaylistResponse(BaseModel):
    """Модель ответа для плейлиста главы."""
    chapter_id: str
    entries: List[PlaylistEntry]

class UpdateScenarioEntryRequest(BaseModel):
    text: Optional[str] = None
    tts_text: Optional[str] = None
    instruct_prompt: Optional[str] = None
    ambient: Optional[str] = None
    sfx: Optional[str] = None
