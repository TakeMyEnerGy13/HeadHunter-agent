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
