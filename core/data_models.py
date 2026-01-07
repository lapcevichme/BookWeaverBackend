"""
Центральный модуль, определяющий все основные структуры данных проекта.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Optional, Dict, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError, model_validator

# TODO - наверное на файлы разбить все модели, их слишком много. Отдельно конфиги, отдельно пайпы


# Timeline

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
    reference_image_path: Optional[str] = Field(None,
                                                description="Путь к сгенерированному референсу (заполняется системой).")


# Ответы от LLM

class CharacterReconResult(BaseModel):
    """
    Модель для 'умной разведки'. Разделяет найденных персонажей на
    существующих (по ID) и абсолютно новых (по именам).
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
    Патч изменений для персонажа.
    Поддерживает логику переименования и обновления таймлайнов.
    """
    id: Optional[UUID] = Field(None, description="ID существующего персонажа. Если null - создается новый.")

    naming_reasoning: Optional[str] = Field(
        None,
        description="Объяснение выбора имени. Обязательно, если меняется имя."
    )
    name: Optional[str] = Field(None, description="Каноническое (удобное) имя.")

    role_tier: Optional[str] = None

    description: Optional[str] = None
    spoiler_free_description: Optional[str] = None
    aliases: Optional[List[str]] = None
    gender: Optional[str] = None

    chapter_mentions: Optional[Dict[str, str]] = None

    # Новые состояния (заполняются ТОЛЬКО при изменениях)
    timeline_voice_update: Optional[CharacterVoiceState] = Field(
        None,
        description="Заполнить, если изменился возраст или голос."
    )
    timeline_visual_update: Optional[CharacterVisualState] = Field(
        None,
        description="Заполнить, если изменилась внешность/одежда."
    )

    @model_validator(mode='before')
    def check_name_for_new_character(cls, values):
        if values.get('id') is None and not values.get('name'):
            raise ValueError("Поле 'name' является обязательным для новых персонажей.")
        return values


class CharacterPatchList(BaseModel):
    """Контейнер для списка патчей от LLM."""
    patches: List[CharacterPatch]


class RawScenarioEntry(BaseModel):
    """'Сырая' запись сценария, как ее возвращает LLM."""
    id: UUID = Field(default_factory=uuid4)
    type: Literal["dialogue", "narration"]
    speaker: str
    text: str


class RawScenario(BaseModel):
    """Контейнер для 'сырого' сценария от LLM."""
    scenario: List[RawScenarioEntry]


class AmbientTransition(BaseModel):
    """Представляет одну точку смены эмбиента в тексте."""
    entry_id: UUID = Field(description="ID записи из сценария, с которой начинается новый эмбиент.")
    ambientSoundId: str = Field(description="ID нового звука из библиотеки эмбиента.")


class AmbientTransitionList(BaseModel):
    """Контейнер для списка смен эмбиента."""
    transitions: List[AmbientTransition]


class EmotionMap(BaseModel):
    """Результат анализа эмоций."""
    emotions: Dict[UUID, str]


# --- Модели пересказов ---

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
        summaries_data = data.get("summaries", {})
        volume_data = data.get("volume_summaries", {})

        summaries_obj = {k: ChapterSummary(**v) for k, v in summaries_data.items()}
        volume_obj = {k: VolumeSummary(**v) for k, v in volume_data.items()}

        return cls(summaries=summaries_obj, volume_summaries=volume_obj)


# --- Модели Сценария ---

class ScenarioEntry(BaseModel):
    """Представляет одну запись (строку) в финальном сценарии."""
    id: UUID
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
        data_to_save = [entry.model_dump(mode='json', exclude_none=True) for entry in self.entries]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        print(f"✅ Сценарий сохранен: {path}")

    @classmethod
    def load(cls, path: Path) -> Scenario:
        if not path.exists():
            raise FileNotFoundError(f"Файл сценария не найден: {path}")
        return cls(entries=json.loads(path.read_text("utf-8")))


# --- Модели Персонажей ---

class Character(BaseModel):
    """
    Полная информация о персонаже, собранная со всей книги.
    """
    id: UUID = Field(default_factory=uuid4, description="Уникальный ID.")
    name: str = Field(description="Каноническое имя (как персонажа чаще всего называют в диалогах).")
    aliases: List[str] = Field(default_factory=list, description="Список альтернативных имен или титулов.")
    gender: Optional[str] = Field(None, description="male/female/other")
    # TODO Ссылка на другое я - на бущее!
    related_identity_id: Optional[UUID] = Field(None, description="ID другого персонажа, если это одна личность.")
    role_tier: str = Field("background", description="protagonist, major, minor, background")
    spoiler_free_description: str = Field(description="Краткое описание без спойлеров.")
    description: str = Field(description="Детальное, полное описание персонажа.")
    # Таймлайны
    voice_timeline: Dict[str, CharacterVoiceState] = Field(default_factory=dict)
    visual_timeline: Dict[str, CharacterVisualState] = Field(default_factory=dict)
    chapter_mentions: Dict[str, str] = Field(default_factory=dict, description="Сводка действий персонажа по главам.")


class CharacterArchive(BaseModel):
    """Контейнер для хранения полного списка (архива) персонажей."""
    characters: List[Character]

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        data_to_save = self.model_dump(mode='json')
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_to_save['characters'], f, ensure_ascii=False, indent=2)
        print(f"✅ Архив персонажей сохранен: {path}")

    @classmethod
    def load(cls, path: Path) -> CharacterArchive:
        if not path.exists():
            return cls(characters=[])
        data = json.loads(path.read_text("utf-8"))
        return cls(characters=data)


# --- Манифест ---

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
    cover_image: Optional[str] = Field(None, description="Имя файла обложки (например, cover.jpg)")
    language: str = Field("ru", description="Код языка книги (ru, en, jp и т.д.)")


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
    """
    Корневой манифест проекта (V2).
    """
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
            print(f"🛑 ОШИБКА ВАЛИДАЦИИ МАНИФЕСТА: {e}")
            raise


# Display Helpers

class LlmRawScenarioEntry(BaseModel):
    type: Literal["dialogue", "narration"]
    speaker: str
    text: str


class LlmRawScenario(BaseModel):
    scenario: List[LlmRawScenarioEntry]
