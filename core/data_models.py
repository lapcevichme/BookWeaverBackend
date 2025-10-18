"""
Центральный модуль, определяющий все основные структуры данных проекта.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Optional, Dict, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError, model_validator


# --- 1. Промежуточные модели (ответы от LLM) ---

class CharacterReconResult(BaseModel):
    """
    Модель для 'умной разведки'. Разделяет найденных персонажей на
    существующих (по ID) и абсолютно новых (по именам).
    **ИЗМЕНЕНО:** Работает с UUID.
    """
    mentioned_existing_character_ids: List[UUID] = Field(
        default_factory=list,
        description="Список ID существующих персонажей, которые были упомянуты в тексте."
    )
    newly_discovered_names: List[str] = Field(
        default_factory=list,
        description="Список имен новых персонажей, которых не было в предоставленном списке."
    )


class CharacterPatch(BaseModel):
    """
    Модель для 'патча'. Содержит ТОЛЬКО измененные или новые данные персонажей.
    """
    id: Optional[UUID] = Field(None,
                               description="ID существующего персонажа для обновления. Если null - создается новый.")
    name: Optional[str] = Field(None,
                                description="Каноническое имя. Обязательно для новых персонажей (когда id is null).")
    description: Optional[str] = None
    spoiler_free_description: Optional[str] = None
    aliases: Optional[List[str]] = None
    chapter_mentions: Optional[Dict[str, str]] = None

    @model_validator(mode='before')
    def check_name_for_new_character(cls, values):
        """
        Проверяет, что если создается новый персонаж (id отсутствует),
        то поле 'name' обязательно должно быть предоставлено.
        """
        if values.get('id') is None and not values.get('name'):
            raise ValueError("Поле 'name' является обязательным для новых персонажей (когда id не указан).")
        return values


class CharacterPatchList(BaseModel):
    """Контейнер для списка патчей от LLM."""
    patches: List[CharacterPatch]


class RawScenarioEntry(BaseModel):
    """'Сырая' запись сценария, как ее возвращает LLM."""
    id: UUID = Field(default_factory=uuid4)  # <-- ДОБАВЛЕНО
    type: Literal["dialogue", "narration"]
    speaker: str
    text: str


class RawScenario(BaseModel):
    """Контейнер для 'сырого' сценария от LLM."""
    scenario: List[RawScenarioEntry]


class AmbientTransition(BaseModel):
    """Представляет одну точку смены эмбиента в тексте."""
    entry_id: UUID = Field(description="ID записи из сценария, с которой начинается новый эмбиент.")  # <-- ЗАМЕНЕНО
    ambientSoundId: str = Field(description="ID нового звука из библиотеки эмбиента.")


class AmbientTransitionList(BaseModel):
    """Контейнер для списка смен эмбиента."""
    transitions: List[AmbientTransition]


class EmotionMap(BaseModel):
    """Результат анализа эмоций."""
    emotions: Dict[UUID, str]


# --- 2. Финальные модели (основные сущности) ---
class RawChapterSummary(BaseModel):
    """'Сырой' пересказ главы, как его возвращает LLM."""
    teaser: str = Field(description="Краткий (40-60 слов), интригующий тизер для пользователя. БЕЗ спойлеров.")
    synopsis: str = Field(
        description="Детальный (100-150 слов) конспект для внутреннего использования. СОДЕРЖИТ спойлеры.")


class ChapterSummary(BaseModel):
    """
    Хранит два вида пересказа для одной главы.
    """
    chapter_id: str = Field(description="Уникальный идентификатор главы, например 'vol_1_chap_1'.")
    teaser: str = Field(description="Краткий (40-60 слов), интригующий тизер для пользователя. БЕЗ спойлеров.")
    synopsis: str = Field(
        description="Детальный (100-150 слов) конспект для внутреннего использования и для пользователя, чтобы освежить память. СОДЕРЖИТ все ключевые события и спойлеры.")


class ChapterSummaryArchive(BaseModel):
    """Контейнер для хранения архива всех пересказов по главам."""
    summaries: Dict[str, ChapterSummary] = Field(default_factory=dict)

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        # Преобразуем в словарь для сохранения
        data_to_save = {key: summary.model_dump() for key, summary in self.summaries.items()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        print(f"✅ Архив пересказов успешно сохранен в: {path}")

    @classmethod
    def load(cls, path: Path) -> ChapterSummaryArchive:
        if not path.exists():
            return cls(summaries={})
        data = json.loads(path.read_text("utf-8"))
        # Преобразуем из словаря обратно в объекты Pydantic
        summaries_obj = {key: ChapterSummary.model_validate(value) for key, value in data.items()}
        return cls(summaries=summaries_obj)


class ScenarioEntry(BaseModel):
    """Представляет одну запись (строку) в финальном сценарии."""
    type: Literal["dialogue", "narration"]
    text: str
    speaker: str
    emotion: Optional[str] = None
    ambient: str = "none"
    audio_file: Optional[str] = None


class Scenario(BaseModel):
    """Полный сценарий для одной главы."""
    entries: List[ScenarioEntry]

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        data_to_save = [entry.model_dump(exclude_none=True) for entry in self.entries]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        print(f"✅ Финальный сценарий успешно сохранен в: {path}")

    @classmethod
    def load(cls, path: Path) -> Scenario:
        if not path.exists():
            raise FileNotFoundError(f"Файл сценария не найден: {path}")
        return cls(entries=json.loads(path.read_text("utf-8")))


class Character(BaseModel):
    """Полная информация о персонаже, собранная со всей книги."""
    id: UUID = Field(default_factory=uuid4, description="Уникальный, неизменяемый ID персонажа.")
    name: str = Field(description="Полное, основное имя персонажа.")
    description: str = Field(description="Детальное, полное описание персонажа, которое может содержать спойлеры.")
    spoiler_free_description: str = Field(description="Краткое описание персонажа без спойлеров.")
    aliases: List[str] = Field(default_factory=list, description="Список альтернативных имен или прозвищ.")
    chapter_mentions: Dict[str, str] = Field(default_factory=dict, description="Сводка действий персонажа по главам.")


class CharacterArchive(BaseModel):
    """Контейнер для хранения полного списка (архива) персонажей."""
    characters: List[Character]

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        data_to_save = self.model_dump(mode='json')
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_to_save['characters'], f, ensure_ascii=False, indent=2)
        print(f"✅ Архив персонажей сохранен в: {path}")

    @classmethod
    def load(cls, path: Path) -> CharacterArchive:
        if not path.exists():
            return cls(characters=[])
        data = json.loads(path.read_text("utf-8"))
        return cls(characters=data)


class BookManifest(BaseModel):
    """Содержит метаданные и настройки для всей книги."""
    book_name: str
    character_voices: Dict[UUID, str] = Field(
        default_factory=dict,
        description="Сопоставление: ID персонажа -> ID голоса (имя папки в /input/voices)."
    )
    default_narrator_voice: str = Field(
        "narrator_default",
        description="ID голоса, используемого для Рассказчика и как запасной вариант."
    )

    def save(self, path: Path):
        """Сохраняет манифест в файл."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2, exclude_defaults=True), encoding="utf-8")
        print(f"✅ Манифест книги сохранен в: {path}")

    @classmethod
    def load(cls, path: Path) -> BookManifest:
        """Загружает манифест из файла, создавая его, если он не существует."""
        if not path.exists():
            print(f"⚠️ Манифест не найден по пути {path}. Будет создан новый.")
            book_name = path.parent.name
            manifest = cls(book_name=book_name)
            manifest.save(path)
            return manifest
        try:
            return cls.model_validate_json(path.read_text("utf-8"))
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"🛑 ОШИБКА: Не удалось загрузить или провалидировать манифест: {path}. Ошибка: {e}")
            raise ValueError(f"Некорректный файл манифеста: {path}") from e


# Эти модели созданы специально для того, чтобы показывать их LLM.
# Они не содержат поля `id`, чтобы не путать модель.

class LlmRawScenarioEntry(BaseModel):
    """'Облегченная' версия RawScenarioEntry для показа LLM."""
    type: Literal["dialogue", "narration"]
    speaker: str
    text: str

class LlmRawScenario(BaseModel):
    """'Облегченный' контейнер для показа LLM."""
    scenario: List[LlmRawScenarioEntry]
