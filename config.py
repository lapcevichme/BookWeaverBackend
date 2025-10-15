import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения (например, GEMINI_API_KEY)
load_dotenv()

# --- 1. Базовые пути ---
# Корень проекта, от которого будут строиться все остальные пути.
BASE_DIR = Path(__file__).parent.resolve()
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"

# --- 2. Пути к ресурсам (ассетам) ---
# Эти файлы не меняются от запуска к запуску.
PROMPTS_DIR = INPUT_DIR / "prompts"
VOICES_DIR = INPUT_DIR / "voices"
EMOTION_REFERENCES_DIR = INPUT_DIR / "emotion_references"
AMBIENT_DIR = INPUT_DIR / "ambient"

# Файлы-библиотеки и словари
PRONUNCIATION_DICT_FILE = INPUT_DIR / "pronunciation_dictionary.json"
VOICE_LIBRARY_FILE = INPUT_DIR / "voice_library.json"
AMBIENT_LIBRARY_FILE = INPUT_DIR / "ambient_library.json"
EMOTION_REFERENCE_LIBRARY_FILE = EMOTION_REFERENCES_DIR / "emotion_reference_library.json"

# --- 3. Настройки моделей и API ---
# Имена моделей для LLM
FAST_MODEL_NAME = os.environ.get("FAST_MODEL_NAME", "gemini-2.0-flash")
POWERFUL_MODEL_NAME = os.environ.get("FAST_MODEL_NAME", "gemini-2.0-flash")

ANALYZER_LLM_TEMPERATURE = 0.5
GENERATOR_LLM_TEMPERATURE = 0.5

# Назначение моделей для конкретных задач
ENTITY_EXTRACTION_MODEL_NAME = FAST_MODEL_NAME
DIALOGUE_ANNOTATION_MODEL_NAME = FAST_MODEL_NAME
CHARACTER_ANALYSIS_MODEL_NAME = POWERFUL_MODEL_NAME

# Настройки TTS (Синтеза речи)
TTS_ENGINE = "xtts"  # "xtts" или "gtts"
VC_MODEL_NAME = "ennis"
TTS_MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
DEFAULT_SPEAKER_VOICE_FILENAME = "default_fallback.wav"

# --- 4. Технические параметры ---
# Настройки обработки текста по частям (чанкам).
MAIN_CHUNK_SIZE_CHARS = 15000
CONTEXT_CHUNK_SIZE_CHARS = 1000

