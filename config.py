import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_PATH)


def _resolve_project_path(raw_value: str, default_relative_path: str) -> str:
    value = (raw_value or "").strip()
    if value:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return str(path)
    return str(PROJECT_ROOT / default_relative_path)

BASE_URL = "https://api.hh.ru/vacancies"

DEFAULT_HEADERS = {
    "User-Agent": os.getenv("HH_USER_AGENT", "hh-agent/0.2 (+https://github.com/TakeMyEnerGy13/HeadHunter-agent)"),
    "Accept": "application/json",
}

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:20128/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "kr/claude-sonnet-4.5")

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

BOT_DB_PATH = _resolve_project_path(os.getenv("BOT_DB_PATH", ""), "bot_data.sqlite")
TRACE_DB_PATH = _resolve_project_path(os.getenv("TRACE_DB_PATH", ""), "data/traces.sqlite")

TG_API_ID = os.getenv("TG_API_ID", "")
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION_NAME = _resolve_project_path(os.getenv("TG_SESSION_NAME", ""), "job_bot_tg_source")
TG_JOB_CHANNELS = os.getenv("TG_JOB_CHANNELS", "")
TG_SOURCE_KEYWORDS = os.getenv("TG_SOURCE_KEYWORDS", "")
TG_SOURCE_NEGATIVE_KEYWORDS = os.getenv("TG_SOURCE_NEGATIVE_KEYWORDS", "")
TG_SOURCE_DB_PATH = _resolve_project_path(
    os.getenv("TG_SOURCE_DB_PATH", ""),
    "data/source_posts.sqlite",
)

SUPERJOB_API_KEY = os.getenv("SUPERJOB_API_KEY", "")
TRUDVSEM_ENABLED = os.getenv("TRUDVSEM_ENABLED", "1")
