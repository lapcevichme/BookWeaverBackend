import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()

# Input / Output
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
EXPORT_DIR = BASE_DIR / "export"
TEMP_DIR = BASE_DIR / "temp"
STORAGE_DIR = BASE_DIR / "storage"
BOOKS_DIR_NAME = "books"

# RAW
RAW_AUDIO_DIR = INPUT_DIR / "raw_audio"
RAW_TEXT_DIR = INPUT_DIR / "raw_text"

# Logging
LOGS_DIR = BASE_DIR / "logs"
LOG_APP_FILE = LOGS_DIR / "app.log"
LOG_DEBUG_FILE = LOGS_DIR / "debug.log"

# Settings
SETTINGS_FILE = BASE_DIR / "settings.json"

# Assets
ASSETS_DIR = BASE_DIR / "assets"
AMBIENT_DIR = ASSETS_DIR / "ambient"
SFX_DIR = ASSETS_DIR / "sfx"
PRONUNCIATION_DICT_FILE = ASSETS_DIR / "pronunciation_dictionary.json"
AMBIENT_LIBRARY_FILE = ASSETS_DIR / "ambient_library.json"
EMOTION_REFERENCE_LIBRARY_FILE = ASSETS_DIR / "emotion_reference_library.json"
SFX_LIBRARY_FILE = ASSETS_DIR / "sfx_library.json"
COMFY_WORKFLOW_FAST = Path("workflow_fast.json")
COMFY_WORKFLOW_HQ = Path("workflow_hq.json")
VOICES_DIR = STORAGE_DIR / "voices"

# Api (Deprecated)
SERVER_PORT = int(os.environ.get("SERVER_PORT", 8080))

# LLM Settings Defaults
_LLM_PROVIDER_DEFAULT = os.environ.get("LLM_PROVIDER", "google") # openrouter / google
_FAST_MODEL_NAME_DEFAULT = os.environ.get("FAST_MODEL_NAME", "gemma-3-27b-it")
_POWERFUL_MODEL_NAME_DEFAULT = os.environ.get("POWERFUL_MODEL_NAME", "gemma-3-27b-it")
_SCENARIO_CHUNK_SIZE_DEFAULT = 40_000

# Temp Defaults
_ANALYZER_LLM_TEMPERATURE_DEFAULT = 0.5
_GENERATOR_LLM_TEMPERATURE_DEFAULT = 0.5
_SUMMARY_LLM_TEMPERATURE_DEFAULT = 0.5

# ComfyUI Settings Defaults
_COMFY_SERVER_ADDRESS_DEFAULT = os.environ.get("COMFY_SERVER_ADDRESS", "127.0.0.1:8188")
COMFY_DEFAULT_WIDTH = 512
COMFY_DEFAULT_HEIGHT = 768
COMFY_NODE_MAPPING = {
    "positive_prompt_node_id": "3",
    "negative_prompt_node_id": "4",
    "empty_latent_node_id": "5",
    "ksampler_node_id": "6"
}

# TTS Defaults
_COSYVOICE_API_URL_DEFAULT = os.environ.get("COSYVOICE_API_URL", "http://localhost:9233")

# Ranobelib Defaults
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

# ElevenLabs Defaults
_ELEVENLABS_API_KEY_DEFAULT = os.environ.get("ELEVENLABS_API_KEY", "")
_GOOGLE_API_KEY_DEFAULT = os.environ.get("GOOGLE_API_KEY", "")
_OPENROUTER_API_KEY_DEFAULT = os.environ.get("OPENROUTER_API_KEY", "")
ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/shared-voices"
TEMP_PREVIEWS_DIR = TEMP_DIR / "voice_previews"
SELECTED_VOICES_DIR = VOICES_DIR / "selected_refs"

def _get_db_setting(key: str, default):
    db_path = OUTPUT_DIR / "system.db"
    if not db_path.exists():
        return default
    import sqlite3
    import json
    conn = None
    try:
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        cursor = conn.cursor()
        cursor.execute("SELECT value_json FROM systemsetting WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row:
            return json.loads(row[0])
    except (sqlite3.OperationalError, sqlite3.DatabaseError, json.JSONDecodeError):
        pass
    finally:
        if conn:
            conn.close()
    return default

def __getattr__(name: str):
    if name == "LLM_PROVIDER":
        return _get_db_setting("llm_provider", _LLM_PROVIDER_DEFAULT)
    elif name == "FAST_MODEL_NAME":
        return _get_db_setting("fast_model", _FAST_MODEL_NAME_DEFAULT)
    elif name == "POWERFUL_MODEL_NAME":
        return _get_db_setting("powerful_model", _POWERFUL_MODEL_NAME_DEFAULT)
    elif name == "SCENARIO_CHUNK_SIZE":
        return int(_get_db_setting("chunk_size", _SCENARIO_CHUNK_SIZE_DEFAULT))
    elif name == "ANALYZER_LLM_TEMPERATURE":
        return float(_get_db_setting("analyzer_temp", _ANALYZER_LLM_TEMPERATURE_DEFAULT))
    elif name == "GENERATOR_LLM_TEMPERATURE":
        return float(_get_db_setting("generator_temp", _GENERATOR_LLM_TEMPERATURE_DEFAULT))
    elif name == "SUMMARY_LLM_TEMPERATURE":
        return float(_get_db_setting("summary_temp", _SUMMARY_LLM_TEMPERATURE_DEFAULT))
    elif name == "COMFY_SERVER_ADDRESS":
        return _get_db_setting("comfy_server_address", _COMFY_SERVER_ADDRESS_DEFAULT)
    elif name == "COSYVOICE_API_URL":
        return _get_db_setting("cosyvoice_url", _COSYVOICE_API_URL_DEFAULT)
    elif name == "ELEVENLABS_API_KEY":
        return _get_db_setting("elevenlabs_key", _ELEVENLABS_API_KEY_DEFAULT)
    elif name == "GOOGLE_API_KEY":
        return _get_db_setting("google_api_key", _GOOGLE_API_KEY_DEFAULT)
    elif name == "OPENROUTER_API_KEY":
        return _get_db_setting("openrouter_api_key", _OPENROUTER_API_KEY_DEFAULT)
        
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


for path in [INPUT_DIR, OUTPUT_DIR, EXPORT_DIR, TEMP_DIR, STORAGE_DIR]:
    path.mkdir(parents=True, exist_ok=True)