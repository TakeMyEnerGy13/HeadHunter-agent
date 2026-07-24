"""
4-step cover letter pipeline: Parser → Matcher → Writer → Critic.

Uses the same AsyncOpenAI client pattern as existing agents in this project.
"""
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.observability import finish_run, record_step, start_run
from config import LLM_API_KEY, LLM_BASE_URL, MODEL_NAME

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_PASS_SCORE = 7
_FORBIDDEN_LETTER_PHRASES = (
    "привет",
    "здравствуйте",
    "видел вакансию",
    "увидел вакансию",
    "увидел вашу вакансию",
    "хочу попробовать себя",
    "мне интересна вакансия",
    "заинтересовала ваша компания",
    "готов развиваться",
    "готов быстро освоить",
    "вопрос пары дней",
    "пару дней практики",
    "прямо в вашем стеке",
    "командный игрок",
    "стрессоустойчив",
    "прошу рассмотреть",
    "с уважением",
)
# Single source of truth for the phrase list injected into Writer/Critic prompts.
_FORBIDDEN_LETTER_PHRASES_STR = ", ".join(f"'{p}'" for p in _FORBIDDEN_LETTER_PHRASES)


@dataclass
class CoverLetterAttempt:
    letter: str
    score: int
    issues: list[str] = field(default_factory=list)
    forbidden_phrases: list[str] = field(default_factory=list)


@dataclass
class CoverLetterPipelineResult:
    job_data: dict
    relevance_map: dict
    best_letter: str
    best_score: int
    attempts: list[CoverLetterAttempt] = field(default_factory=list)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_PARSER_SYSTEM = (
    "Ты — аналитик вакансий. Извлеки структурированную информацию из описания вакансии. "
    "Не выводи скрытые требования: seniority указывай только если он прямо написан в вакансии. "
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
  "seniority": "junior/mid/senior/lead/unknown"
}}

Если seniority не указан явно словами junior/middle/mid/senior/lead или годами опыта,
верни "seniority": "unknown".""" 

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
  "score": 68,
  "decision": "good/maybe/bad",
  "matches": [
    {{"requirement": "...", "evidence": "конкретный опыт из резюме"}}
  ],
  "gaps": ["требование, которое не закрыто резюме"],
  "key_selling_points": ["топ-3 аргумента почему кандидат подходит"]
}}

Правила score и decision:
- good: 75-100, кандидат явно подходит
- maybe: 50-74, есть полезные совпадения, но заметны gaps
- bad: 0-49, вакансия слабо подходит
- Для junior/tooling/automation ролей релевантные pet projects и self-use проекты считаются сильным
  сигналом, если вакансия не требует явно commercial/production experience или N+ лет опыта.
- Если кандидат закрывает основную работу роли теми же инструментами и задачами, ставь good
  даже без коммерческого опыта, но отметь gaps по production/commercial опыту, если они есть.
- Не выводи скрытые требования. Не добавляй gap по seniority, commercial или production опыту,
  если это прямо не указано в вакансии.
- Названия вроде Specialist/Developer/Engineer сами по себе не означают mid/senior.
  Если seniority не указан явно, считай его unknown и не штрафуй кандидата за junior level.
- Не добавляй gap про production-grade решения, если в вакансии нет прямого требования production,
  enterprise, highload, масштабирования или коммерческого опыта.
- Если требование сформулировано как альтернатива (например SQLite/Postgres), засчитывай совпадение
  по одной из технологий и не делай это сильным gap.
- Evidence должно быть прямым фактом из резюме. Не пиши "вероятно", "скорее всего",
  "как Python разработчик должен знать" и не засчитывай навык по догадке.
- key_selling_points должны быть про уже имеющийся опыт, а не про обещания "быстро освоит",
  "легко адаптируется", "готов изучить".
- Не завышай score за pet projects, если вакансия требует commercial production experience."""

_WRITER_SYSTEM = (
    "Ты пишешь сопроводительное письмо для отклика на вакансию. "
    "СТРОГИЕ ПРАВИЛА: "
    "1. Пиши ТОЛЬКО в стиле tone_samples — длина предложений, лексика, структура абзацев. "
    "2. Используй ТОЛЬКО факты из relevance_map — не выдумывай опыт. "
    "3. Не пиши generic AI-slop. Запрещены шаблонные фразы и приветствия вроде: "
    f"{_FORBIDDEN_LETTER_PHRASES_STR}. "
    "4. Первое предложение должно сразу давать конкретный матч: что из опыта кандидата закрывает "
    "главное требование вакансии. "
    "5. Пиши как живой человек: коротко, спокойно, без канцелярита, самопрезентации и восторга. "
    "6. Если сильного совпадения мало, не маскируй это общими фразами — честно сделай письмо короче "
    "и опирайся только на реальные пересечения. "
    "7. Для вакансий про AI automation, LLM + API + Python, интеграции и прототипирование делай акцент "
    "не на абстрактном стеке, а на том, какие процессы кандидат реально автоматизировал end-to-end. "
    "8. Если релевантно, обязательно дай 2-3 конкретных кейса или пайплайна: что было на входе, "
    "что кандидат собрал и какой процесс закрыл. "
    "9. Не перечисляй инструменты россыпью без кейсов. Каждый важный инструмент привязывай к задаче, "
    "интеграции или автоматизации. "
    "10. Если в вакансии акцент на бизнес-процессы, явно проговори, что кандидат умеет разбирать процесс "
    "и собирать под него рабочий AI-прототип. "
    "11. Фразы про 'быстро учусь' и 'хочу развиваться' допустимы только коротким хвостом в конце, "
    "если это прямо отражено в вакансии. Не делай их основой письма. "
    "12. Не расширяй факты: SQLite не превращай в SQL/NoSQL, базовый CI/CD не превращай в опыт "
    "с CI/CD пайплайнами, LLM bot не превращай в RAG/LangGraph, если этого нет в evidence. "
    "13. Не обещай освоить инструменты за пару дней и не пиши 'готов быстро освоить'. "
    "14. Если технология из вакансии не закрыта, лучше не упоминай её в письме, чем обещай быстро добрать. "
    "15. Оптимальная длина: 5-9 коротких предложений или 2-3 компактных абзаца. "
    "16. Верни ТОЛЬКО текст письма без объяснений."
)
_WRITER_USER = """\
{feedback_block}Примеры моего стиля (изучи и точно повтори — длина фраз, лексику, структуру):
{tone_samples}

Мои предпочтения к письму:
{preferences}

Полный текст вакансии (первоисточник — сверяйся с точными формулировками, ключевыми словами
и отдельными просьбами рекрутера, например «укажите в отклике слово X»):
{job_text}

Детали вакансии (структурированная выжимка):
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

Пожелания кандидата к письму:
{preferences}

Полный текст вакансии (первоисточник):
{job_text}

Вакансия (структурированная выжимка):
{job_json}

Релевантный опыт, на который разрешено опираться:
{relevance_map}

Письмо на проверку:
{letter}

Оцени по шкале 1-10 и верни JSON:
{{
  "score": 8,
  "issues": ["конкретная проблема если есть"]
}}

Критерии оценки:
1. Отвечает на реальные требования вакансии (не generic)
2. Нет шаблонных фраз, AI-slop и unsupported claims
3. Стиль совпадает с примерами
4. Конкретность и лаконичность
5. Первое предложение не приветствует и не сообщает, что кандидат увидел вакансию, а сразу показывает
   конкретное совпадение опыта с требованием
6. Не расширяет факты из relevance_map: не превращает SQLite в SQL/NoSQL, простой LLM-бот в RAG/LangGraph,
   базовые знания в рабочий опыт и gaps в обещания "освою за пару дней"
7. Если вакансия про AI automation / LLM + API + Python / интеграции / прототипирование, письмо должно
   содержать минимум 2 конкретных кейса или end-to-end примера, а не только список инструментов
8. Если вакансия про бизнес-процессы, письмо должно явно показать, что кандидат умеет разбирать процесс
   и собирать под него рабочую автоматизацию или прототип
9. Соответствует пожеланиям кандидата к письму (длина, акценты, тон). Если пожелание нарушено — это issue.

Ставь score <= 4, если письмо содержит фразы вроде:
{forbidden_list}.

score < 7 = письмо нужно переписать."""


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

async def _call_json(
    client: AsyncOpenAI,
    model: str,
    system: str,
    user: str,
    step_name: str,
    run_id: str,
) -> dict:
    """Call LLM expecting a JSON response."""
    started_at = time.perf_counter()
    input_text = f"{system}\n\n{user}"
    response = None
    content = ""
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = response.choices[0].message.content or "{}"
        clean = content.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)
        await record_step(
            run_id=run_id,
            step_name=step_name,
            model=model,
            input_text=input_text,
            output_text=content,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            usage=getattr(response, "usage", None),
        )
        return result
    except Exception as exc:
        await record_step(
            run_id=run_id,
            step_name=step_name,
            model=model,
            input_text=input_text,
            output_text=content,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            usage=getattr(response, "usage", None) if response else None,
            status="error",
            error=str(exc),
        )
        raise


async def _call_text(
    client: AsyncOpenAI,
    model: str,
    system: str,
    user: str,
    step_name: str,
    run_id: str,
) -> str:
    """Call LLM expecting a plain text response."""
    started_at = time.perf_counter()
    input_text = f"{system}\n\n{user}"
    response = None
    content = ""
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or ""
        await record_step(
            run_id=run_id,
            step_name=step_name,
            model=model,
            input_text=input_text,
            output_text=content,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            usage=getattr(response, "usage", None),
        )
        return content.strip()
    except Exception as exc:
        await record_step(
            run_id=run_id,
            step_name=step_name,
            model=model,
            input_text=input_text,
            output_text=content,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            usage=getattr(response, "usage", None) if response else None,
            status="error",
            error=str(exc),
        )
        raise


async def _parse_job(job_text: str, client: AsyncOpenAI, model: str, run_id: str) -> dict:
    logger.info("Pipeline step 1: parsing job posting")
    return await _call_json(
        client, model, _PARSER_SYSTEM,
        _PARSER_USER.format(job_text=job_text),
        step_name="parse_job",
        run_id=run_id,
    )


async def _match_profile(
    job_data: dict,
    resume_text: str,
    client: AsyncOpenAI,
    model: str,
    run_id: str,
) -> dict:
    logger.info("Pipeline step 2: matching profile to job")
    return await _call_json(
        client, model, _MATCHER_SYSTEM,
        _MATCHER_USER.format(
            job_json=json.dumps(job_data, ensure_ascii=False, indent=2),
            resume_text=resume_text,
        ),
        step_name="match_profile",
        run_id=run_id,
    )


async def _write_letter(
    relevance_map: dict,
    job_data: dict,
    job_text: str,
    tone_samples: str,
    preferences: str,
    client: AsyncOpenAI,
    model: str,
    run_id: str,
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
            job_text=job_text[:4000],
            job_json=json.dumps(job_data, ensure_ascii=False, indent=2),
            relevance_map=json.dumps(relevance_map, ensure_ascii=False, indent=2),
        ),
        step_name="write_letter",
        run_id=run_id,
    )


async def _critique_letter(
    letter: str,
    job_data: dict,
    job_text: str,
    relevance_map: dict,
    tone_samples: str,
    preferences: str,
    client: AsyncOpenAI,
    model: str,
    run_id: str,
) -> dict:
    logger.info("Pipeline step 4: critiquing letter")
    return await _call_json(
        client, model, _CRITIC_SYSTEM,
        _CRITIC_USER.format(
            tone_samples=tone_samples or "Стиль не задан.",
            preferences=preferences or "Без особых предпочтений.",
            job_text=job_text[:4000],
            job_json=json.dumps(job_data, ensure_ascii=False, indent=2),
            relevance_map=json.dumps(relevance_map, ensure_ascii=False, indent=2),
            letter=letter,
            forbidden_list=_FORBIDDEN_LETTER_PHRASES_STR,
        ),
        step_name="critique_letter",
        run_id=run_id,
    )


def _coerce_score(raw) -> int:
    """Tolerant score parsing: '8/10', '7.5', 8 → int; anything unparseable → 0 (rewrite)."""
    try:
        return int(float(str(raw).split("/")[0].strip()))
    except (ValueError, TypeError):
        return 0


def _find_forbidden_phrases(letter: str) -> list[str]:
    normalized = letter.lower().replace("ё", "е")
    return [phrase for phrase in _FORBIDDEN_LETTER_PHRASES if _has_forbidden_phrase(normalized, phrase)]


def _has_forbidden_phrase(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = phrase.lower().replace("ё", "е")
    if normalized_phrase == "с уважением":
        # Catches a standalone sign-off AND "с уважением, Имя" (letters after comma).
        return any(
            re.match(r"^\s*с уважением\b", line)
            for line in normalized_text.splitlines()
        )

    pattern = rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)"
    return re.search(pattern, normalized_text) is not None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

async def run_cover_letter_pipeline_result(
    job_text: str,
    resume_text: str,
    tone_samples: str = "",
    preferences: str = "",
    base_url: str = LLM_BASE_URL,
    api_key: str = LLM_API_KEY,
    model: str = MODEL_NAME,
) -> CoverLetterPipelineResult:
    """
    Run the full pipeline and return structured data for evals and diagnostics.
    """
    run_id = str(uuid.uuid4())
    started_at = time.perf_counter()
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    await start_run(run_id, model)

    try:
        job_data = await _parse_job(job_text, client, model, run_id)
        relevance_map = await _match_profile(job_data, resume_text, client, model, run_id)

        best_letter: str = ""
        best_score: int = 0
        best_has_forbidden_phrases = True
        attempts: list[CoverLetterAttempt] = []
        feedback: list[str] | None = None

        for attempt in range(_MAX_RETRIES + 1):
            letter = await _write_letter(
                relevance_map, job_data, job_text, tone_samples, preferences,
                client, model, run_id, feedback=feedback,
            )
            critique = await _critique_letter(
                letter, job_data, job_text, relevance_map, tone_samples, preferences,
                client, model, run_id,
            )

            score = _coerce_score(critique.get("score", 0))
            forbidden_phrases = _find_forbidden_phrases(letter)
            has_forbidden_phrases = bool(forbidden_phrases)
            if forbidden_phrases:
                score = min(score, 4)
                critique["issues"] = (critique.get("issues") or []) + [
                    "Убери шаблонные фразы: " + ", ".join(forbidden_phrases),
                    "Начни с конкретного совпадения опыта кандидата с требованием вакансии.",
                ]
            issues = critique.get("issues") or []
            attempts.append(
                CoverLetterAttempt(
                    letter=letter,
                    score=score,
                    issues=issues,
                    forbidden_phrases=forbidden_phrases,
                )
            )

            if (
                (best_has_forbidden_phrases and not has_forbidden_phrases)
                or (has_forbidden_phrases == best_has_forbidden_phrases and score > best_score)
            ):
                best_score = score
                best_letter = letter
                best_has_forbidden_phrases = has_forbidden_phrases

            logger.info("Critic score: %d/%d (attempt %d)", score, _PASS_SCORE, attempt + 1)

            if score >= _PASS_SCORE:
                break

            # Critic can drop the score without naming issues — give the retry
            # something to act on instead of re-running the identical prompt.
            feedback = issues or [
                "Критик снизил балл, но не назвал причину. Усиль конкретику первого "
                "предложения и привяжи каждый инструмент к реальному кейсу из relevance_map.",
            ]

        await finish_run(
            run_id=run_id,
            status="ok",
            final_score=best_score,
            total_latency_ms=int((time.perf_counter() - started_at) * 1000),
        )
        return CoverLetterPipelineResult(
            job_data=job_data,
            relevance_map=relevance_map,
            best_letter=best_letter,
            best_score=best_score,
            attempts=attempts,
        )
    except Exception as exc:
        await finish_run(
            run_id=run_id,
            status="error",
            total_latency_ms=int((time.perf_counter() - started_at) * 1000),
            error=str(exc),
        )
        raise
