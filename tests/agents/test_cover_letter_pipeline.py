import asyncio

import pytest

from app.agents import cover_letter_pipeline as pipeline


async def _noop(*args, **kwargs):
    return None


@pytest.fixture(autouse=True)
def no_observability(monkeypatch):
    monkeypatch.setattr(pipeline, "start_run", _noop)
    monkeypatch.setattr(pipeline, "record_step", _noop)
    monkeypatch.setattr(pipeline, "finish_run", _noop)


def _patch_steps(monkeypatch, write, critique):
    async def fake_parse(*args, **kwargs):
        return {"role": "разработчик"}

    async def fake_match(*args, **kwargs):
        return {"score": 80, "decision": "good", "gaps": []}

    monkeypatch.setattr(pipeline, "_parse_job", fake_parse)
    monkeypatch.setattr(pipeline, "_match_profile", fake_match)
    monkeypatch.setattr(pipeline, "_write_letter", write)
    monkeypatch.setattr(pipeline, "_critique_letter", critique)


def _run():
    return asyncio.run(
        pipeline.run_cover_letter_pipeline_result("вакансия", "резюме")
    )


def test_critic_failure_on_retry_keeps_best_letter(monkeypatch):
    calls = {"critic": 0}

    async def fake_write(*args, **kwargs):
        return "Письмо A"

    async def fake_critique(*args, **kwargs):
        calls["critic"] += 1
        if calls["critic"] == 1:
            return {"score": 6, "issues": ["слабое начало"]}
        raise RuntimeError("critic returned malformed JSON")

    _patch_steps(monkeypatch, fake_write, fake_critique)
    result = _run()
    assert result.best_letter == "Письмо A"
    assert result.best_score == 6
    assert len(result.attempts) == 1


def test_writer_failure_on_retry_keeps_best_letter(monkeypatch):
    calls = {"write": 0}

    async def fake_write(*args, **kwargs):
        calls["write"] += 1
        if calls["write"] == 1:
            return "Письмо A"
        raise RuntimeError("api down")

    async def fake_critique(*args, **kwargs):
        return {"score": 5, "issues": ["мало конкретики"]}

    _patch_steps(monkeypatch, fake_write, fake_critique)
    result = _run()
    assert result.best_letter == "Письмо A"
    assert result.best_score == 5


def test_first_attempt_failure_still_raises(monkeypatch):
    async def fake_write(*args, **kwargs):
        raise RuntimeError("api down")

    async def fake_critique(*args, **kwargs):
        return {"score": 9, "issues": []}

    _patch_steps(monkeypatch, fake_write, fake_critique)
    with pytest.raises(RuntimeError):
        _run()


@pytest.mark.parametrize(
    "letter",
    [
        "Опыта продаж нет, но в мире AI это менее болезненно.",
        "RAG и LangChain не использовал в продакшене, но собирал кастомную оркестрацию.",
        "Векторных баз в продакшене не было, но с RAG работал.",
        "С CI/CD опыта нет, зато API-интеграции делал руками.",
        "Kafka не трогал, однако очереди понимаю.",
    ],
)
def test_hedging_detected(letter):
    assert pipeline._find_hedging_sentences(letter)


@pytest.mark.parametrize(
    "letter",
    [
        "Собрал пайплайн из четырёх агентов, но главное — он измерим.",
        "Не останавливаюсь на «модель отвечает», довожу до метрик.",
        "Диагностировал исчерпание пула соединений PostgreSQL и закрыл его.",
        "Держу в продакшене пять ботов с живыми пользователями.",
        # The one allowed shape: a bare fact about a mandatory unmet requirement,
        # with no contrastive clause attached. Must never be penalised.
        "На .NET не писал.",
        "Kafka не использовал. Держу в продакшене пять ботов и свои evals.",
    ],
)
def test_hedging_not_flagged_for_clean_letters(letter):
    assert pipeline._find_hedging_sentences(letter) == []


def test_hedging_caps_score_and_adds_issue(monkeypatch):
    async def fake_write(*args, **kwargs):
        return "Опыта с Kafka нет, но брокеры я понимаю."

    async def fake_critique(*args, **kwargs):
        return {"score": 9, "issues": []}

    _patch_steps(monkeypatch, fake_write, fake_critique)
    result = _run()

    assert result.best_score <= 4
    assert result.attempts[0].hedging_sentences
    assert any("оправд" in issue.lower() for issue in result.attempts[0].issues)


def test_clean_letter_preferred_over_hedging_letter(monkeypatch):
    letters = iter(
        [
            "Опыта с Kafka нет, но брокеры я понимаю.",
            "Держу в продакшене пять ботов и свои evals.",
        ]
    )
    scores = iter([9, 7])

    async def fake_write(*args, **kwargs):
        return next(letters)

    async def fake_critique(*args, **kwargs):
        return {"score": next(scores), "issues": []}

    _patch_steps(monkeypatch, fake_write, fake_critique)
    result = _run()

    # The hedging letter scored higher before the penalty; the clean one must win.
    assert result.best_letter == "Держу в продакшене пять ботов и свои evals."
