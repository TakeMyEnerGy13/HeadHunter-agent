import json

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.schemas.llm_schemas import CoverLetter
from config import LLM_API_KEY, LLM_BASE_URL, MODEL_NAME

SYSTEM_PROMPT = (
    "Ты — IT-специалист, который пишет сопроводительное письмо для отклика на вакансию. "
    "Твоя задача — написать живое, лаконичное и адекватное письмо (не более 3-4 небольших абзацев). "
    "СТРОГИЕ ПРАВИЛА: "
    "1. НИКОГДА не используй шаблонные фразы вроде 'Откликаюсь на позицию...', 'Прошу рассмотреть мое резюме на вакансию...' или 'С уважением, Имя'. "
    "2. Начинай сразу с сути: почему твой опыт (из резюме) решает боли компании (из вакансии). "
    "3. Пиши в инфостиле (Ильяхов), без воды и лизоблюдства. Тон спокойный, уверенный. "
    "4. Не придумывай опыт, которого нет в резюме. Выделяй то, что пересекается с требованиями. "
    "5. Верни ТОЛЬКО JSON-объект с полем 'text' (строка). Никакого лишнего текста до или после JSON."
)


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
    ) -> CoverLetter:
        user_prompt = (
            "Вакансия:\n"
            f"{vacancy_text}\n\n"
            "Мое резюме:\n"
            f"{resume_text}\n\n"
            'Напиши живое сопроводительное письмо. Верни строго JSON: {"text": "текст письма"}'
        )

        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise WriterAgentError(f"Ошибка запроса к LLM: {exc}") from exc

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise WriterAgentError("LLM не вернул текст письма")

        # ОЧИСТКА: Убираем маркдаун-кавычки
        clean_content = content.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(clean_content)
            return CoverLetter.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError):
            # Заплатка, если ИИ прислал просто текст
            return CoverLetter(text=clean_content)

