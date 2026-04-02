import os

from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.hh.ru/vacancies"

DEFAULT_HEADERS = {
    "User-Agent": "hh-agent/0.1 (+https://api.hh.ru)",
    "Accept": "application/json",
}

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:20128/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "kr/claude-sonnet-4.5")

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")

