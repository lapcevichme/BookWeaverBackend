"""
Центральный модуль, определяющий все основные структуры данных проекта.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Optional, Dict, Literal
from uuid import UUID, uuid4
from enum import Enum

from pydantic import BaseModel, Field, ValidationError, model_validator


# --- Enums ---

class CharacterType(str, Enum):
    PERSON = "person"
    ANIMAL = "animal"
    OBJECT = "object"
    UNKNOWN = "unknown"


# --- Timeline Models ---

class CharacterVoiceState(BaseModel):
    """
    Состояние голоса персонажа в конкретный момент времени (Keyframe).
    """
    age_group: str = Field(..., description="Группа: child, teen, adult, elderly")
    age_exact: Optional[str] = Field(None, description="Точный возраст (строкой), если известен.")
    voice_description: str = Field(..., description="Описание звучания для человека (на русском).")
    search_tags: Optional[str] = Field(None,
                                       description="Теги для поиска голоса (на английском), например: 'young male, raspy'.")
    assigned_voice_id: Optional[str] = Field(None, description="ID голоса в ElevenLabs (заполняется скриптом, не LLM).")


class CharacterVisualState(BaseModel):
    """
    Состояние внешности персонажа в конкретный момент времени (Keyframe).
    """
    description: str = Field(..., description="Общее описание внешности и одежды в этой главе.")
    image_prompt: Optional[str] = Field(None, description="Готовый промпт для генерации (на английском, для SD).")
    reference_image_path: Optional[str] = Field(None, description="Путь к сгенерированному референсу.")


# --- Analysis & Patching Models ---

class CharacterReconResult(BaseModel):
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


class CharacterPatch(BaseModel):
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


class CharacterPatchList(BaseModel):
    patches: List[CharacterPatch]


# --- Scenario Generation Models (Intermediate) ---

class RawScenarioEntry(BaseModel):
    """'Сырая' запись сценария (парсинг ответа)."""
    id: UUID = Field(default_factory=uuid4)
    type: Literal["dialogue", "narration", "thought", "image"]
    speaker: Optional[str] = Field(None, description="Имя говорящего.")
    text: Optional[str] = Field(None, description="Текст реплики.")
    src: Optional[str] = Field(None, description="Относительный путь к файл (только для типа image). Если картинки нет, НЕ СОЗДАВАЙ ЭТО ПОЛЕ")

class RawScenario(BaseModel):
    """Контейнер для 'сырого' сценария от LLM."""
    scenario: List[RawScenarioEntry]


# --- Sound Design Models ---

class SoundDesignItem(BaseModel):
    """
    Результат работы звукорежиссера для одной записи сценария.
    """
    entry_id: str = Field(description="ID записи сценария.")
    ambient: Optional[str] = Field(None, description="ID фонового звука. Если 'none' - ВООБЩЕ НЕ ВЫВОДИ поле.")
    sfx: Optional[str] = Field(None, description="ID звукового эффекта. Если нет - ВООБЩЕ НЕ ВЫВОДИ поле.")


class SoundDesignResult(BaseModel):
    """Контейнер для списка звуковых решений."""
    design: List[SoundDesignItem]


# --- Emotion & Prosody Models ---

class VoiceDirection(BaseModel):
    instruct: str = Field(
        description="Инструкция для диктора (до 5 слов), например: 'тихо, с грустью' или 'нагнетая саспенс'."
    )
    tts_text: Optional[str] = Field(
        default=None,
        description="ГЕНЕРИРОВАТЬ ТОЛЬКО ЕСЛИ НУЖНЫ ТЕГИ! Если текст произносится без тегов (<|pause|> и тд), ВООБЩЕ НЕ ВЫВОДИ ЭТО ПОЛЕ, чтобы сэкономить токены."
    )

class EmotionMap(BaseModel):
    """Результат анализа эмоций."""
    emotions: Dict[UUID, str]


# --- Summary Models ---

class RawChapterSummary(BaseModel):
    """'Сырой' пересказ главы, как его возвращает LLM."""
    teaser: str = Field(description="Краткий (40-60 слов), интригующий тизер для пользователя. БЕЗ спойлеров.")
    synopsis: str = Field(
        description="Детальный (100-150 слов) конспект для внутреннего использования. СОДЕРЖИТ спойлеры.")


class ChapterSummary(BaseModel):
    """Хранит два вида пересказа для одной главы."""
    chapter_id: str = Field(description="Уникальный идентификатор главы, например 'vol_1_chap_1'.")
    teaser: str = Field(description="Краткий (40-60 слов), интригующий тизер.")
    synopsis: str = Field(description="Детальный (100-150 слов) конспект.")

class VolumeSummary(BaseModel):
    """Глобальный пересказ целого тома."""
    volume_num: int
    summary: str = Field(description="Сжатый пересказ событий всего тома.")

class ChapterSummaryArchive(BaseModel):
    summaries: Dict[str, ChapterSummary] = Field(default_factory=dict)
    volume_summaries: Dict[str, VolumeSummary] = Field(default_factory=dict)

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        data_to_save = {
            "summaries": {k: s.model_dump() for k, s in self.summaries.items()},
            "volume_summaries": {k: s.model_dump() for k, s in self.volume_summaries.items()}
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: Path) -> ChapterSummaryArchive:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text("utf-8"))
        summaries_obj = {k: ChapterSummary(**v) for k, v in data.get("summaries", {}).items()}
        volume_obj = {k: VolumeSummary(**v) for k, v in data.get("volume_summaries", {}).items()}
        return cls(summaries=summaries_obj, volume_summaries=volume_obj)


# --- Final Scenario Models ---

class ScenarioEntry(BaseModel):
    """Представляет одну запись (строку) в финальном сценарии."""
    id: UUID
    type: Literal["dialogue", "narration", "thought", "image"]
    text: Optional[str] = None
    tts_text: Optional[str] = None
    speaker: Optional[str] = None
    instruct_prompt: str = Field("neutral")
    ambient: str = "none"
    sfx: Optional[str] = None
    audio_file: Optional[str] = None
    src: Optional[str] = None

class Scenario(BaseModel):
    """Полный сценарий для одной главы."""
    entries: List[ScenarioEntry]

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        data_to_save = [entry.model_dump(mode='json', exclude_none=True) for entry in self.entries]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        print(f"✅ Сценарий сохранен: {path}")

    @classmethod
    def load(cls, path: Path) -> Scenario:
        if not path.exists():
            raise FileNotFoundError(f"Файл сценария не найден: {path}")
        return cls(entries=json.loads(path.read_text("utf-8")))


# --- Character Archive Models ---

class Character(BaseModel):
    """
    Полная информация о персонаже, собранная со всей книги.
    """
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(...)
    entity_type: CharacterType = Field(default=CharacterType.PERSON)
    aliases: List[str] = Field(default_factory=list)
    gender: Optional[str] = Field(None)
    # TODO Ссылка на другое я - на бущее!
    related_identity_id: Optional[UUID] = Field(None)
    role_tier: str = Field("background")
    spoiler_free_description: str = Field(...)
    description: str = Field(...)
    visual_base: Optional[str] = Field(None)
    voice_timeline: Dict[str, CharacterVoiceState] = Field(default_factory=dict)
    visual_timeline: Dict[str, CharacterVisualState] = Field(default_factory=dict)
    chapter_mentions: Dict[str, str] = Field(default_factory=dict)

class CharacterArchive(BaseModel):
    characters: List[Character]
    processed_chapters: List[str] = Field(default_factory=list)

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        data_to_save = self.model_dump(mode='json')
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        print(f"✅ Архив персонажей сохранен: {path}")

    @classmethod
    def load(cls, path: Path) -> CharacterArchive:
        if not path.exists():
            return cls(characters=[])
        data = json.loads(path.read_text("utf-8"))
        if isinstance(data, list):
            return cls(characters=data)
        return cls(**data)


# --- Manifest Models ---

class ManifestMeta(BaseModel):
    """Метаданные книги."""
    title: str = "Без названия"
    author: Optional[str] = "Неизвестный автор"
    description: Optional[str] = ""
    tags: List[str] = Field(default_factory=list)
    source_url: Optional[str] = ""
    status: str = "ongoing"
    version: str = "1.0"
    total_duration_ms: int = 0
    cover_image: Optional[str] = Field(None)
    language: str = Field("ru")

class ManifestChapterEntry(BaseModel):
    """Одна запись в оглавлении (ToC)."""
    order: int
    title: str
    vol: int = 1
    chap: int
    status: str = "draft"
    path: Optional[str] = None
    id: Optional[str] = None
    src_dir: Optional[str] = None

    @model_validator(mode='after')
    def enforce_canonical_identifiers(self):
        """
        Гарантирует, что ID и src_dir соответствуют формату vol_X_chap_Y.
        Перезаписывает любые левые данные.
        """
        canonical_id = f"vol_{self.vol}_chap_{self.chap}"
        self.id = canonical_id
        if not self.src_dir:
            self.src_dir = canonical_id
        return self

class ManifestConfig(BaseModel):
    """Технические настройки генерации (для бэкенда)."""
    notes: Optional[str] = None
    last_run_log: Optional[str] = None
    default_narrator_voice: str = "narrator_default"
    character_voices: Dict[UUID, str] = Field(default_factory=dict)

class BookManifest(BaseModel):
    """Корневой манифест проекта (V2)."""
    project_id: str
    meta: ManifestMeta
    structure: List[ManifestChapterEntry] = Field(default_factory=list)
    config: ManifestConfig = Field(default_factory=ManifestConfig)

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2, exclude_defaults=True), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> BookManifest:
        if not path.exists():
            raise FileNotFoundError(f"Манифест не найден: {path}. Запустите импорт книги!")
        try:
            return cls.model_validate_json(path.read_text("utf-8"))
        except ValidationError as e:
            print(f"ОШИБКА ВАЛИДАЦИИ МАНИФЕСТА: {e}")
            raise

# --- Display/Prompt Helpers ---

class LlmRawScenarioEntry(BaseModel):
    """Используется ТОЛЬКО для генерации схемы в промпте (без UUID)."""
    type: Literal["dialogue", "narration", "thought", "image"]
    speaker: Optional[str] = None
    text: Optional[str] = None
    src: Optional[str] = Field(None, description="Если это не image, ВООБЩЕ НЕ ВЫВОДИ ключ src")

class LlmRawScenario(BaseModel):
    """Используется ТОЛЬКО для генерации схемы в промпте."""
    scenario: List[LlmRawScenarioEntry]