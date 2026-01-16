import os
from pathlib import Path

from dotenv import load_dotenv

# Загружаем переменные окружения (например, GEMINI_API_KEY)
load_dotenv()

SERVER_PORT = 8080

# --- Базовые пути ---
# Корень проекта, от которого будут строиться все остальные пути.
BASE_DIR = Path(__file__).parent.resolve()
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
EXPORT_DIR = BASE_DIR / "export"
TEMP_DIR = BASE_DIR / "temp"

# --- Пути к ассетам ---
# Эти файлы не меняются от запуска к запуску.
VOICES_DIR = INPUT_DIR / "voices"
EMOTION_REFERENCES_DIR = INPUT_DIR / "emotion_references"
AMBIENT_DIR = INPUT_DIR / "ambient"
BOOKS_DIR_NAME = "books"

# Файлы-библиотеки и словари
# TODO: input это довольно странное место для static файлов, нужно будет поменять пути. Просто static нужно сделать и не париться
PRONUNCIATION_DICT_FILE = INPUT_DIR / "pronunciation_dictionary.json"
AMBIENT_LIBRARY_FILE = INPUT_DIR / "ambient_library.json"
EMOTION_REFERENCE_LIBRARY_FILE = EMOTION_REFERENCES_DIR / "emotion_reference_library.json"
SFX_LIBRARY_FILE = EMOTION_REFERENCES_DIR / "sfx_library.json"

# --- Настройки моделей и API ---
# Имена моделей для LLM
# TODO: нахуя я выносил в env название моделей?? Грохнуть кстати надо google api, 2.5-flash слишком медленный стал
# UPD: сука хуесосы убили лимиты!!! Какие 20 запросов в день але???? И даже на нищую гемму лимит 15к токенов!!!!!!!
# UPD2: ай сасать, переход!!!
LLM_PROVIDER = "openrouter"
FAST_MODEL_NAME = os.environ.get("FAST_MODEL_NAME", "gemma-3-27b-it")
POWERFUL_MODEL_NAME = os.environ.get("POWERFUL_MODEL_NAME", "gemma-3-27b-it")
# xiaomi/mimo-v2-flash - max out 65.5K tokens
# json где-то на 30% процентов больше делает вывод. TODO: сделать как-то автоподбор размеров или формулу на основе out токенов
SCENARIO_CHUNK_SIZE = 40_000

ANALYZER_LLM_TEMPERATURE = 0.5
GENERATOR_LLM_TEMPERATURE = 0.5
SUMMARY_LLM_TEMPERATURE = 0.5

# Настройки TTS (Синтеза речи)
# TODO: пересмотреть в целом работу с VC, так как все сломалось <3333
VC_MODEL_NAME = "voice_conversion_models/multilingual/vctk/freevc24"
TTS_MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"

# --- Настройки ComfyUI ---
COMFY_SERVER_ADDRESS = os.environ.get("COMFY_SERVER_ADDRESS", "127.0.0.1:8188")
COMFY_WORKFLOW_FILE = INPUT_DIR / "comfy_workflow.json"

# Эти параметры используются как fallback, но если в маппинге ниже
# ключи закомментированы, то размеры берутся прямо из JSON файла.
COMFY_DEFAULT_WIDTH = 512
COMFY_DEFAULT_HEIGHT = 768

# === МАППИНГ НОД (ГИБКАЯ НАСТРОЙКА) ===
# Укажите ID ноды, если хотите перезаписывать её значение из Python.
COMFY_NODE_MAPPING = {
    "positive_prompt_node_id": "3",
    # "negative_prompt_node_id": "4",
    # "ksampler_node_id": "6",
    # "empty_latent_node_id": "5",
}

for path in [OUTPUT_DIR, EXPORT_DIR, TEMP_DIR]:
    path.mkdir(parents=True, exist_ok=True)