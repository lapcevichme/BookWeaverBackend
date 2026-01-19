import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()

# --- INPUT / OUTPUT ---
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
EXPORT_DIR = BASE_DIR / "export"
TEMP_DIR = BASE_DIR / "temp"
STORAGE_DIR = BASE_DIR / "storage"
BOOKS_DIR_NAME = "books"

# RAW
RAW_AUDIO_DIR = INPUT_DIR / "raw_audio"
RAW_TEXT_DIR = INPUT_DIR / "raw_text"

# --- LOGGING ---
LOGS_DIR = BASE_DIR / "logs"
LOG_FILE_NAME = "bookweaver.log"
LOG_FILE_PATH = LOGS_DIR / LOG_FILE_NAME

# --- ASSETS ---
ASSETS_DIR = BASE_DIR / "assets"
AMBIENT_DIR = ASSETS_DIR / "ambient"
PRONUNCIATION_DICT_FILE = ASSETS_DIR / "pronunciation_dictionary.json"
AMBIENT_LIBRARY_FILE = ASSETS_DIR / "ambient_library.json"
EMOTION_REFERENCE_LIBRARY_FILE = ASSETS_DIR / "emotion_reference_library.json"
SFX_LIBRARY_FILE = ASSETS_DIR / "sfx_library.json"
COMFY_WORKFLOW_FILE = ASSETS_DIR / "comfy_workflow.json"
VOICES_DIR = STORAGE_DIR / "voices"

# --- EXTERNAL SERVICES ---
SERVER_PORT = int(os.environ.get("SERVER_PORT", 8080))

# LLM Settings
LLM_PROVIDER = "openrouter"
FAST_MODEL_NAME = os.environ.get("FAST_MODEL_NAME", "gemma-3-27b-it")
POWERFUL_MODEL_NAME = os.environ.get("POWERFUL_MODEL_NAME", "gemma-3-27b-it")
SCENARIO_CHUNK_SIZE = 40_000

# Temp
ANALYZER_LLM_TEMPERATURE = 0.5
GENERATOR_LLM_TEMPERATURE = 0.5
SUMMARY_LLM_TEMPERATURE = 0.5

# ComfyUI Settings
COMFY_SERVER_ADDRESS = os.environ.get("COMFY_SERVER_ADDRESS", "127.0.0.1:8188")
COMFY_DEFAULT_WIDTH = 512
COMFY_DEFAULT_HEIGHT = 768
COMFY_NODE_MAPPING = {
    "positive_prompt_node_id": "3",
    # "negative_prompt_node_id": "4",
    # "ksampler_node_id": "6",
    # "empty_latent_node_id": "5",
}

# TTS
COSYVOICE_API_URL = os.environ.get("COSYVOICE_API_URL", "http://localhost:8188")

# Ranobelib
RANOBELIB_API_BASE_URL = "https://api.cdnlibs.org/api"
RANOBELIB_IMAGE_BASE_URL = "https://lib.social"
RANOBELIB_USER_TOKEN = os.environ.get("RANOBELIB_USER_TOKEN", "")

RANOBELIB_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
    'Referer': 'https://ranobelib.me/',
    'Origin': 'https://ranobelib.me',
    'Site-Id': '3',
    'Client-Time-Zone': 'Asia/Novosibirsk',
    'Content-Type': 'application/json',
    'sec-ch-ua-platform': '"Linux"',
    'sec-ch-ua': '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    'sec-ch-ua-mobile': '?0'
}

# ElevenLabs
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/shared-voices"
TEMP_PREVIEWS_DIR = TEMP_DIR / "voice_previews"
SELECTED_VOICES_DIR = VOICES_DIR / "selected_refs"


for path in [INPUT_DIR, OUTPUT_DIR, EXPORT_DIR, TEMP_DIR, STORAGE_DIR]:
    path.mkdir(parents=True, exist_ok=True)