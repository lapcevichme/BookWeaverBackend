"""
Этот файл содержит Pydantic-модели (DTOs), соответствующие обновленному ТЗ
для оптимизации мобильного клиента (On-Demand Loading).
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict


# Общие / Служебные модели

class OnboardingDataDto(BaseModel):
    """Данные для QR-кода (знакомство)."""
    ip: str
    port: int
    token: str
    serverName: str

class PingResponseDto(BaseModel):
    """Ответ для health-check."""
    status: str
    server_name: str


# "Хаб книги" (/structure)

class BookManifestStructureDto(BaseModel):
    """
    Облегченная версия манифеста для экрана структуры.
    Включает готовые URL для обложки.
    """
    book_name: str
    title: str = Field(description="Отображаемое название (обычно совпадает с book_name или из метаданных)")
    author: Optional[str] = None
    version: int = Field(1, description="Версия манифеста для кеширования")
    poster_url: str = Field(description="Полный URL к обложке книги (/static/...)")


class ChapterStubDto(BaseModel):
    """
    Краткая информация о главе для списка.
    """
    id: str
    title: str
    version: int = 1
    volume_number: Optional[int] = None
    has_audio: bool = False


class BookStructureResponseDto(BaseModel):
    """
    Ответ для GET /api/books/{bookId}/structure
    Максимально легкий JSON.
    """
    manifest: BookManifestStructureDto
    chapters: List[ChapterStubDto]


# "Список персонажей" (/characters)

class CharacterListEntryDto(BaseModel):
    """
    Элемент списка персонажей. Только фото и имя.
    """
    id: str
    name: str
    avatar_url: Optional[str] = Field(None, description="URL аватарки персонажа")
    short_role: Optional[str] = Field(None, description="Короткая роль (пока не реализовано в бэкенде, резерв)")


# "Детали персонажа" (/characters/{id})

class CharacterDetailsDto(BaseModel):
    """
    Полная информация о персонаже. Загружается точечно.
    """
    id: str
    name: str
    avatar_url: Optional[str] = None
    description: str
    spoiler_free_description: str
    aliases: List[str] = Field(default_factory=list)
    chapter_mentions: Dict[str, str] = Field(default_factory=dict)


# "Инфо о главе" (/chapters/{id}/info)

class ChapterInfoDto(BaseModel):
    """
    Превью главы (тизер и синопсис) перед прослушиванием.
    """
    chapter_id: str
    title: str
    teaser: str
    synopsis: str


# Модели для Плеера

class SyncMapEntryDto(BaseModel):
    """
    Запись для синхронизации текста с большим аудиофайлом.
    """
    text: str
    start_ms: int
    end_ms: int
    speaker: str
    ambient: str = "none"
    # words: List[DomainWordEntryDto] = []

class PlaybackDataResponseDto(BaseModel):
    """
    Формат ответа для плеера.
    Аудио отдается одним файлом.
    """
    audio_url: Optional[str] = Field(None, description="Ссылка на единый склеенный MP3 файл главы. Null, если аудио еще нет.")
    duration_ms: int = Field(description="Общая длительность аудиофайла в мс")
    sync_map: List[SyncMapEntryDto] = Field(description="Карта таймкодов относительно начала файла")


# Legacy

class BookManifestDto(BaseModel):
    book_name: str
    author: Optional[str] = None
    character_voices: Dict[str, str] = Field(default_factory=dict)
    default_narrator_voice: str

class CharacterDto(BaseModel):
    id: str
    name: str
    description: str
    spoiler_free_description: str
    aliases: List[str] = Field(default_factory=list)
    chapter_mentions: Dict[str, str] = Field(default_factory=dict)

class ChapterSummaryDto(BaseModel):
    chapter_id: str
    teaser: str
    synopsis: str

class BookDetailsResponseDto(BaseModel):
    """
    DEPRECATED: Полный, тяжелый ответ.
    """
    manifest: BookManifestDto
    characters: List[CharacterDto]
    summaries: Dict[str, ChapterSummaryDto]
    chapters: List[ChapterStubDto]