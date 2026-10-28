"""
Configuration module for MCP Data Assistant.
Loads settings from .env file with safe defaults.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# --- Mode & Database Type ---
MCP_MODE = os.getenv("MCP_MODE", "demo").lower()
DATABASE_TYPE = os.getenv("DATABASE_TYPE", "sqlite").lower()

# --- Paths ---
# --- Paths ---
if MCP_MODE == "real":
    # Use SQLITE_DB_PATH or DB_PATH if set.
    # If not set, look for any database in data/real_db/, otherwise default to data/real_db/real.db.
    env_path = os.getenv("SQLITE_DB_PATH") or os.getenv("DB_PATH")
    db_path_env = env_path
    
    if not db_path_env:
        # scan data/real_db/ for sqlite/db files
        real_db_dir = BASE_DIR / "data" / "real_db"
        db_files = []
        if real_db_dir.exists():
            db_files = [f for f in list(real_db_dir.glob("*.db")) + list(real_db_dir.glob("*.sqlite")) if "sample.db" not in f.name]
        if db_files:
            db_path_env = str(db_files[0].relative_to(BASE_DIR))
        else:
            db_path_env = "data/real_db/real.db"
else:
    # demo mode fallback to sample.db
    db_path_env = os.getenv("SQLITE_DB_PATH") or os.getenv("DB_PATH") or "data/sample.db"

raw_db_path = Path(db_path_env)
if not raw_db_path.is_absolute():
    DB_PATH = (BASE_DIR / raw_db_path).resolve()
else:
    DB_PATH = raw_db_path.resolve()

# Restrict/block DB path outside D:\MCP PROJECT\data
DATA_LIMIT_DIR = (BASE_DIR / "data").resolve()
try:
    DB_PATH.relative_to(DATA_LIMIT_DIR)
except ValueError:
    raise ValueError(f"Security block: Database path '{DB_PATH}' must be located within '{DATA_LIMIT_DIR}'")

# Show only DB file name in UI/API
DB_NAME = DB_PATH.name
DB_FILE_NAME = DB_NAME
CONNECTED = DB_PATH.exists() and DB_PATH.is_file() and "sample.db" not in DB_NAME if MCP_MODE == "real" else (DB_PATH.exists() and DB_PATH.is_file())
DEMO_DATA_ACTIVE = (MCP_MODE == "demo")

DATASET_ENV_DIR = os.getenv("DATASET_DIR") or os.getenv("DATASETS_DIR")
if MCP_MODE == "real":
    raw_dataset_dir = DATASET_ENV_DIR or "data/real_datasets"
else:
    raw_dataset_dir = DATASET_ENV_DIR or "data/datasets"

DATASETS_DIR = (BASE_DIR / raw_dataset_dir).resolve()

# --- Server ---
BACKEND_HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8200"))
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "3200"))

# --- MCP Server ---
MCP_SERVER_HOST = os.getenv("MCP_SERVER_HOST", "127.0.0.1")
MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8020"))
MCP_SERVER_PATH = os.getenv("MCP_SERVER_PATH", "/mcp")
MCP_SERVER_URL = os.getenv(
    "MCP_SERVER_URL",
    f"http://{MCP_SERVER_HOST}:{MCP_SERVER_PORT}{MCP_SERVER_PATH}",
)
MCP_HTTP_TIMEOUT_SECONDS = float(os.getenv("MCP_HTTP_TIMEOUT_SECONDS", "1.0"))

# --- Ollama ---
OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "false").lower() == "true"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

# --- Safety ---
READ_ONLY_MODE = os.getenv("READ_ONLY_MODE", "true").lower() == "true"
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "100"))
MAX_TABLES_SCAN = int(os.getenv("MAX_TABLES_SCAN", "20"))  # perf guard: cap tables scanned per generic search
QUERY_TIMEOUT_SECONDS = int(os.getenv("QUERY_TIMEOUT_SECONDS", "10"))  # abort a single SQLite query if it runs longer than this

# Blocked SQL keywords (case-insensitive)
BLOCKED_SQL_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
    "CREATE", "REPLACE", "TRUNCATE", "ATTACH", "DETACH",
    "PRAGMA", "VACUUM", "REINDEX",
]

# Ensure directories exist on startup
(BASE_DIR / "data" / "real_db").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "data" / "real_datasets").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "data" / "imports" / "inbox").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "data" / "imports" / "processed").mkdir(parents=True, exist_ok=True)
(BASE_DIR / "data" / "registry").mkdir(parents=True, exist_ok=True)

# --- Central logging setup (request/search-plan logs already go to logs/audit.log
# via main.py's log_audit(); this handles Python-level error/debug logs from all
# modules, e.g. logger.error(...) calls in db_reader.py). No secrets are logged.
import logging as _logging
_LOG_DIR = BASE_DIR / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
if not _logging.getLogger().handlers:
    _handlers = [_logging.StreamHandler()]
    try:
        _handlers.insert(0, _logging.FileHandler(_LOG_DIR / "errors.log", encoding="utf-8"))
    except OSError:
        pass
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=_handlers,
    )
