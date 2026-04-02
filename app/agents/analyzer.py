import json

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.schemas.llm_schemas import VacancyAnalysis
from config import LLM_API_KEY, LLM_BASE_URL, MODEL_NAME

SYSTEM_PROMPT = (
    "Ты HR-аналитик. Оцени соответствие кандидата вакансии и верни только JSON-объект "
    'с полями: "match_score" (int 0..100) и "brief_reason" (str). Без лишнего текста.'
)


class AnalyzerAgentError(Exception):
    """Ошибка работы AnalyzerAgent."""


class AnalyzerAgent:
    def __init__(
        self,
        base_url: str = LLM_BASE_URL,
        api_key: str = LLM_API_KEY,
        model_name: str = MODEL_NAME,
    ) -> None:
        self.model_name = model_name
        # Сразу сохраняем клиент в self.client с правильными отступами
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url
        )
        print(f"\n[DEBUG] Агент стучится сюда: {self.client.base_url}")

    async def analyze_vacancy(
        self,
        vacancy_text: str,
        resume_text: str,
    ) -> VacancyAnalysis:
        user_prompt = (
            "Вакансия:\n"
            f"{vacancy_text}\n\n"
            "Резюме:\n"
            f"{resume_text}\n\n"
            "Сравни и верни JSON строго заданного формата."
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
            raise AnalyzerAgentError(f"Ошибка запроса к LLM: {exc}") from exc

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise AnalyzerAgentError("LLM не вернул содержимое ответа")

        # --- ДЕБАГ: Смотрим, что реально ответила нейросеть ---
        print(f"\n[DEBUG] Сырой ответ ИИ:\n{content}\n")

        # --- ОЧИСТКА: Убираем маркдаун-кавычки, если ИИ их добавил ---
        clean_content = content.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(clean_content)
            return VacancyAnalysis.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise AnalyzerAgentError(f"Некорректный JSON от LLM: {exc}") from exc