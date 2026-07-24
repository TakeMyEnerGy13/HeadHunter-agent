from openai import AsyncOpenAI

from app.agents.cover_letter_pipeline import run_cover_letter_pipeline_result
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
            result = await run_cover_letter_pipeline_result(
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

        if not result.best_letter:
            raise WriterAgentError("Пайплайн не вернул текст письма")

        # B2: carry the matcher verdict through, so the caller can show the user
        # how well the vacancy actually fits instead of just the letter text.
        relevance = result.relevance_map or {}
        try:
            match_score = int(relevance.get("score"))
        except (TypeError, ValueError):
            match_score = None

        return CoverLetter(
            text=result.best_letter,
            match_score=match_score,
            decision=relevance.get("decision"),
            gaps=[str(gap) for gap in relevance.get("gaps", [])],
            attempts=len(result.attempts),
        )

