from openai import AsyncOpenAI

from app.agents.cover_letter_pipeline import run_cover_letter_pipeline
from app.schemas.llm_schemas import CoverLetter
from config import LLM_API_KEY, LLM_BASE_URL, MODEL_NAME


class WriterAgentError(Exception):
    """Ошибка работы WriterAgent."""


class WriterAgent:
    def __init__(
        self,
        base_url: str = LLM_BASE_URL,
        api_key: str = LLM_API_KEY,
        model_name: str = MODEL_NAME,
    ) -> None:
        self.model_name = model_name
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    async def generate_letter(
        self,
        vacancy_text: str,
        resume_text: str,
        tone_samples: str = "",
        preferences: str = "",
    ) -> CoverLetter:
        try:
            text = await run_cover_letter_pipeline(
                job_text=vacancy_text,
                resume_text=resume_text,
                tone_samples=tone_samples,
                preferences=preferences,
                base_url=str(self.client.base_url),
                api_key=self.client.api_key,
                model=self.model_name,
            )
        except Exception as exc:
            raise WriterAgentError(f"Ошибка пайплайна генерации письма: {exc}") from exc

        if not text:
            raise WriterAgentError("Пайплайн не вернул текст письма")

        return CoverLetter(text=text)

