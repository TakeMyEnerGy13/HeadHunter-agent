import asyncio

import pytest

from app.agents import writer as writer_module
from app.agents.cover_letter_pipeline import CoverLetterAttempt, CoverLetterPipelineResult
from app.agents.writer import WriterAgent, WriterAgentError


def _result(**overrides) -> CoverLetterPipelineResult:
    kwargs = {
        "job_data": {},
        "relevance_map": {"score": 82, "decision": "good", "gaps": []},
        "best_letter": "Письмо.",
        "best_score": 9,
        "attempts": [CoverLetterAttempt(letter="Письмо.", score=9)],
    }
    kwargs.update(overrides)
    return CoverLetterPipelineResult(**kwargs)


def _patch(monkeypatch, result=None, exc=None):
    async def fake(**kwargs):
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(writer_module, "run_cover_letter_pipeline_result", fake)


def _generate() -> object:
    return asyncio.run(WriterAgent().generate_letter("вакансия", "резюме"))


def test_letter_carries_score_decision_and_gaps(monkeypatch):
    _patch(
        monkeypatch,
        _result(relevance_map={"score": 15, "decision": "bad", "gaps": ["Kubernetes", "Terraform"]}),
    )
    letter = _generate()
    assert letter.text == "Письмо."
    assert letter.match_score == 15
    assert letter.decision == "bad"
    assert letter.gaps == ["Kubernetes", "Terraform"]
    assert letter.attempts == 1


def test_attempts_count_reflects_retries(monkeypatch):
    attempts = [CoverLetterAttempt(letter="a", score=4), CoverLetterAttempt(letter="b", score=8)]
    _patch(monkeypatch, _result(attempts=attempts))
    assert _generate().attempts == 2


def test_non_integer_score_becomes_none(monkeypatch):
    _patch(monkeypatch, _result(relevance_map={"score": "нет данных", "decision": "maybe"}))
    letter = _generate()
    assert letter.match_score is None
    assert letter.decision == "maybe"


def test_empty_relevance_map_does_not_break(monkeypatch):
    _patch(monkeypatch, _result(relevance_map={}))
    letter = _generate()
    assert letter.match_score is None
    assert letter.decision is None
    assert letter.gaps == []


def test_empty_letter_raises(monkeypatch):
    _patch(monkeypatch, _result(best_letter=""))
    with pytest.raises(WriterAgentError):
        _generate()


def test_pipeline_failure_is_wrapped(monkeypatch):
    _patch(monkeypatch, exc=RuntimeError("502"))
    with pytest.raises(WriterAgentError):
        _generate()
