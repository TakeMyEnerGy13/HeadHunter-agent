import os

# openai>=2.x raises at AsyncOpenAI() construction when api_key is empty, so tests
# need a dummy key before app modules import config. load_dotenv does not override
# an already-set env var, so a real .env still wins outside tests.
os.environ.setdefault("LLM_API_KEY", "test-key")
