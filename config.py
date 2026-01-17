import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()

# INPUT
INPUT_DIR = BASE_DIR / "input"
BOOKS_DIR_NAME = "books"

# ASSETS
ASSETS_DIR = BASE_DIR / "assets"
EMOTION_REFERENCES_DIR = ASSETS_DIR / "emotion_references"
AMBIENT_DIR = ASSETS_DIR / "ambient"
# Файлы конфигураций и библиотек
PRONUNCIATION_DICT_FILE = ASSETS_DIR / "pronunciation_dictionary.json"
AMBIENT_LIBRARY_FILE = ASSETS_DIR / "ambient_library.json"
EMOTION_REFERENCE_LIBRARY_FILE = EMOTION_REFERENCES_DIR / "emotion_reference_library.json"
SFX_LIBRARY_FILE = EMOTION_REFERENCES_DIR / "sfx_library.json"
COMFY_WORKFLOW_FILE = ASSETS_DIR / "comfy_workflow.json"

# STORAGE
STORAGE_DIR = BASE_DIR / "storage"
VOICES_DIR = STORAGE_DIR / "voices"

# OUTPUT
OUTPUT_DIR = BASE_DIR / "output"
EXPORT_DIR = BASE_DIR / "export"
TEMP_DIR = BASE_DIR / "temp"


# --- Настройки внешних сервисов и API ---
SERVER_PORT = 8080

# LLM
# xiaomi/mimo-v2-flash - max out 65.5K tokens
# json где-то на 30% процентов больше делает вывод. TODO: сделать как-то автоподбор размеров или формулу на основе out токенов
LLM_PROVIDER = "openrouter"
FAST_MODEL_NAME = os.environ.get("FAST_MODEL_NAME", "gemma-3-27b-it")
POWERFUL_MODEL_NAME = os.environ.get("POWERFUL_MODEL_NAME", "gemma-3-27b-it")
SCENARIO_CHUNK_SIZE = 40_000

# Температуры
ANALYZER_LLM_TEMPERATURE = 0.5
GENERATOR_LLM_TEMPERATURE = 0.5
SUMMARY_LLM_TEMPERATURE = 0.5

# ComfyUI
COMFY_SERVER_ADDRESS = os.environ.get("COMFY_SERVER_ADDRESS", "127.0.0.1:8188")
COMFY_DEFAULT_WIDTH = 512
COMFY_DEFAULT_HEIGHT = 768
COMFY_NODE_MAPPING = {
    "positive_prompt_node_id": "3",
    # "negative_prompt_node_id": "4",
    # "ksampler_node_id": "6",
    # "empty_latent_node_id": "5",
}

# TTS / VC
VC_MODEL_NAME = "voice_conversion_models/multilingual/vctk/freevc24"
TTS_MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"


for path in [INPUT_DIR, OUTPUT_DIR, EXPORT_DIR, TEMP_DIR, STORAGE_DIR]:
    path.mkdir(parents=True, exist_ok=True)