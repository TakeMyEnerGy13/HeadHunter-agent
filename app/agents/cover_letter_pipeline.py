"""
4-step cover letter pipeline: Parser → Matcher → Writer → Critic.

Uses the same AsyncOpenAI client pattern as existing agents in this project.
"""
import json
import logging

from openai import AsyncOpenAI

from config import LLM_API_KEY, LLM_BASE_URL, MODEL_NAME

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_PASS_SCORE = 7

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_PARSER_SYSTEM = (
    "Ты — аналитик вакансий. Извлеки структурированную информацию из описания вакансии. "
    "Верни ТОЛЬКО валидный JSON без лишнего текста."
)
_PARSER_USER = """\
Вакансия:
{job_text}

Верни JSON строго в таком формате:
{{
  "role": "название должности",
  "company": "название компании или Unknown",
  "stack": ["технология1", "технология2"],
  "hard_skills": ["навык1"],
  "soft_skills": ["навык1"],
  "responsibilities": ["обязанность1"],
  "company_culture": "краткое описание культуры",
  "seniority": "junior/mid/senior/lead"
}}"""

_MATCHER_SYSTEM = (
    "Ты — карьерный коуч. Сопоставь требования вакансии с профилем кандидата. "
    "Верни ТОЛЬКО валидный JSON без лишнего текста."
)
_MATCHER_USER = """\
Требования вакансии:
{job_json}

Резюме кандидата:
{resume_text}

Верни JSON строго в таком формате:
{{
  "matches": [
    {{"requirement": "...", "evidence": "конкретный опыт из резюме"}}
  ],
  "gaps": ["требование, которое не закрыто резюме"],
  "key_selling_points": ["топ-3 аргумента почему кандидат подходит"]
}}"""

_WRITER_SYSTEM = (
    "Ты пишешь сопроводительное письмо для отклика на вакансию. "
    "СТРОГИЕ ПРАВИЛА: "
    "1. Пиши ТОЛЬКО в стиле tone_samples — длина предложений, лексика, структура абзацев. "
    "2. Используй ТОЛЬКО факты из relevance_map — не выдумывай опыт. "
    "3. Никаких шаблонных фраз: 'командный игрок', 'стрессоустойчив', 'Прошу рассмотреть', 'С уважением'. "
    "4. Начинай сразу с сути. Лаконично, уверенно, без воды. "
    "5. Верни ТОЛЬКО текст письма без объяснений."
)
_WRITER_USER = """\
{feedback_block}Примеры моего стиля (изучи и точно повтори — длина фраз, лексику, структуру):
{tone_samples}

Мои предпочтения к письму:
{preferences}

Детали вакансии:
{job_json}

Релевантный опыт (используй ТОЛЬКО это, не выдумывай):
{relevance_map}

Напиши сопроводительное письмо."""

_WRITER_FEEDBACK_BLOCK = """\
Предыдущая версия письма имела проблемы — ОБЯЗАТЕЛЬНО исправь их:
{issues}

"""

_CRITIC_SYSTEM = (
    "Ты рецензируешь сопроводительное письмо. "
    "Верни ТОЛЬКО валидный JSON без лишнего текста."
)
_CRITIC_USER = """\
Примеры стиля (эталон):
{tone_samples}

Вакансия:
{job_json}

Письмо на проверку:
{letter}

Оцени по шкале 1-10 и верни JSON:
{{
  "score": 8,
  "issues": ["конкретная проблема если есть"],
  "revised_letter": "улучшенная версия письма или оригинал если score >= 7"
}}

Критерии оценки:
1. Отвечает на реальные требования вакансии (не generic)
2. Нет шаблонных фраз
3. Стиль совпадает с примерами
4. Конкретность и лаконичность

score < 7 = письмо нужно переписать."""


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

async def _call_json(
    client: AsyncOpenAI,
    model: str,
    system: str,
    user: str,
) -> dict:
    """Call LLM expecting a JSON response."""
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    clean = content.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


async def _call_text(
    client: AsyncOpenAI,
    model: str,
    system: str,
    user: str,
) -> str:
    """Call LLM expecting a plain text response."""
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (response.choices[0].message.content or "").strip()


async def _parse_job(job_text: str, client: AsyncOpenAI, model: str) -> dict:
    logger.info("Pipeline step 1: parsing job posting")
    return await _call_json(
        client, model, _PARSER_SYSTEM,
        _PARSER_USER.format(job_text=job_text),
    )


async def _match_profile(
    job_data: dict,
    resume_text: str,
    client: AsyncOpenAI,
    model: str,
) -> dict:
    logger.info("Pipeline step 2: matching profile to job")
    return await _call_json(
        client, model, _MATCHER_SYSTEM,
        _MATCHER_USER.format(
            job_json=json.dumps(job_data, ensure_ascii=False, indent=2),
            resume_text=resume_text,
        ),
    )


async def _write_letter(
    relevance_map: dict,
    job_data: dict,
    tone_samples: str,
    preferences: str,
    client: AsyncOpenAI,
    model: str,
    feedback: list[str] | None = None,
) -> str:
    logger.info("Pipeline step 3: writing letter (feedback=%s)", bool(feedback))
    feedback_block = ""
    if feedback:
        issues = "\n".join(f"- {i}" for i in feedback)
        feedback_block = _WRITER_FEEDBACK_BLOCK.format(issues=issues)

    return await _call_text(
        client, model, _WRITER_SYSTEM,
        _WRITER_USER.format(
            feedback_block=feedback_block,
            tone_samples=tone_samples or "Стиль не задан — пиши лаконично и по делу.",
            preferences=preferences or "Без особых предпочтений.",
            job_json=json.dumps(job_data, ensure_ascii=False, indent=2),
            relevance_map=json.dumps(relevance_map, ensure_ascii=False, indent=2),
        ),
    )


async def _critique_letter(
    letter: str,
    job_data: dict,
    tone_samples: str,
    client: AsyncOpenAI,
    model: str,
) -> dict:
    logger.info("Pipeline step 4: critiquing letter")
    return await _call_json(
        client, model, _CRITIC_SYSTEM,
        _CRITIC_USER.format(
            tone_samples=tone_samples or "Стиль не задан.",
            job_json=json.dumps(job_data, ensure_ascii=False, indent=2),
            letter=letter,
        ),
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

async def run_cover_letter_pipeline(
    job_text: str,
    resume_text: str,
    tone_samples: str = "",
    preferences: str = "",
    base_url: str = LLM_BASE_URL,
    api_key: str = LLM_API_KEY,
    model: str = MODEL_NAME,
) -> str:
    """
    Run the full 4-step cover letter pipeline.

    Returns the best generated cover letter text.
    """
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    job_data = await _parse_job(job_text, client, model)
    relevance_map = await _match_profile(job_data, resume_text, client, model)

    best_letter: str = ""
    best_score: int = 0
    feedback: list[str] | None = None

    for attempt in range(_MAX_RETRIES + 1):
        letter = await _write_letter(
            relevance_map, job_data, tone_samples, preferences,
            client, model, feedback=feedback,
        )
        critique = await _critique_letter(letter, job_data, tone_samples, client, model)

        score = int(critique.get("score", 0))
        revised = critique.get("revised_letter") or letter

        if score > best_score:
            best_score = score
            best_letter = revised

        logger.info("Critic score: %d/%d (attempt %d)", score, _PASS_SCORE, attempt + 1)

        if score >= _PASS_SCORE:
            break

        feedback = critique.get("issues") or []

    return best_letter
