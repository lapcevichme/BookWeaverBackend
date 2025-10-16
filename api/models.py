"""
Этот файл содержит все Pydantic-модели, используемые в разных частях API.
Это помогает избежать циклических импортов.
"""
from pydantic import BaseModel, Field
from typing import List, Literal
from enum import Enum

class ServerStateEnum(str, Enum):
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    ERROR = "ERROR"

class ServerStatus(BaseModel):
    status: ServerStateEnum
    message: str = ""

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

class BookArtifactName(str, Enum):
    manifest = "manifest"
    character_archive = "character_archive"
    summary_archive = "summary_archive"

class ChapterArtifactName(str, Enum):
    scenario = "scenario"
    subtitles = "subtitles"

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

