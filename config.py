import os
from pathlib import Path

from dotenv import load_dotenv

# Загружаем переменные окружения (например, GEMINI_API_KEY)
load_dotenv()

SERVER_PORT = 8080

# --- 1. Базовые пути ---
# Корень проекта, от которого будут строиться все остальные пути.
BASE_DIR = Path(__file__).parent.resolve()
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
EXPORT_DIR = BASE_DIR / "export"
TEMP_DIR = BASE_DIR / "temp"

# --- 2. Пути к ресурсам (ассетам) ---
# Эти файлы не меняются от запуска к запуску.
VOICES_DIR = INPUT_DIR / "voices"
EMOTION_REFERENCES_DIR = INPUT_DIR / "emotion_references"
AMBIENT_DIR = INPUT_DIR / "ambient"
BOOKS_DIR_NAME = "books"

# Файлы-библиотеки и словари
PRONUNCIATION_DICT_FILE = INPUT_DIR / "pronunciation_dictionary.json"
AMBIENT_LIBRARY_FILE = INPUT_DIR / "ambient_library.json"
EMOTION_REFERENCE_LIBRARY_FILE = EMOTION_REFERENCES_DIR / "emotion_reference_library.json"

# --- 3. Настройки моделей и API ---
# Имена моделей для LLM
FAST_MODEL_NAME = os.environ.get("FAST_MODEL_NAME", "gemini-2.0-flash")
POWERFUL_MODEL_NAME = os.environ.get("FAST_MODEL_NAME", "gemini-2.5-flash")

ANALYZER_LLM_TEMPERATURE = 0.5
GENERATOR_LLM_TEMPERATURE = 0.5
SUMMARY_LLM_TEMPERATURE = 0.5

# Настройки TTS (Синтеза речи)
VC_MODEL_NAME = "ennis"
TTS_MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"

# --- 4. Создание служебных директорий ---
# Убедимся, что основные папки существуют
OUTPUT_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)
