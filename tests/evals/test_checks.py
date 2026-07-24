from dataclasses import dataclass, field

from app.evals.checks import evaluate_pipeline_result, validate_case_schema


@dataclass
class _FakeResult:
    best_letter: str = ""
    relevance_map: dict = field(default_factory=dict)


def _base_case(**overrides) -> dict:
    case = {
        "schema_version": 1,
        "id": "t1",
        "resume": "r",
        "vacancy": "v",
        "expected_decision": "good",
        "expected_score_min": 70,
        "expected_score_max": 90,
    }
    case.update(overrides)
    return case


def _clean_map() -> dict:
    return {"score": 80, "decision": "good", "gaps": []}


# --- A4: word-boundary matching replaces substring `in` ---

def test_forbidden_phrase_substring_does_not_false_positive():
    # "привет" must NOT match inside "приветствовать".
    case = _base_case(forbidden_letter_phrases=["привет"])
    result = _FakeResult(best_letter="Готов приветствовать новые задачи.", relevance_map=_clean_map())
    assert evaluate_pipeline_result(case, result) == []


def test_forbidden_phrase_whole_word_is_caught():
    case = _base_case(forbidden_letter_phrases=["привет"])
    result = _FakeResult(best_letter="Привет, меня зовут Тёма.", relevance_map=_clean_map())
    errors = evaluate_pipeline_result(case, result)
    assert any("forbidden phrase" in e for e in errors)


def test_signoff_special_case_is_caught():
    case = _base_case(forbidden_letter_phrases=["с уважением"])
    result = _FakeResult(best_letter="Закрываю задачу.\nС уважением, Тёма", relevance_map=_clean_map())
    errors = evaluate_pipeline_result(case, result)
    assert any("forbidden phrase" in e for e in errors)


# --- must_not_claim: phrases must be claim-shaped, not bare vacancy terms ---

def test_must_not_claim_ignores_honest_denial():
    # An honest letter naming the missing skill must not trip the check.
    case = _base_case(must_not_claim=["опыт работы с kubernetes"])
    result = _FakeResult(
        best_letter="По Kubernetes и Terraform опыта нет.", relevance_map=_clean_map()
    )
    assert evaluate_pipeline_result(case, result) == []


def test_must_not_claim_catches_overclaim():
    case = _base_case(must_not_claim=["опыт работы с kubernetes"])
    result = _FakeResult(
        best_letter="Есть опыт работы с Kubernetes в проде.", relevance_map=_clean_map()
    )
    errors = evaluate_pipeline_result(case, result)
    assert any("forbidden claim" in e for e in errors)


# --- B5: must_mention ---

def test_must_mention_present_passes():
    case = _base_case(must_mention=["Python", "OpenAI"])
    result = _FakeResult(
        best_letter="Собирал ботов на Python с OpenAI API.", relevance_map=_clean_map()
    )
    assert evaluate_pipeline_result(case, result) == []


def test_must_mention_missing_fails():
    case = _base_case(must_mention=["SQLite"])
    result = _FakeResult(best_letter="Писал ботов на Python.", relevance_map=_clean_map())
    errors = evaluate_pipeline_result(case, result)
    assert any("missing required mention: SQLite" in e for e in errors)


def test_must_mention_partial_word_does_not_count():
    # "API" required, but only "APIшка" present → not a word-boundary match → fails.
    case = _base_case(must_mention=["API"])
    result = _FakeResult(best_letter="Дёргал APIшку каждый день.", relevance_map=_clean_map())
    errors = evaluate_pipeline_result(case, result)
    assert any("missing required mention: API" in e for e in errors)


# --- B5: length guard ---

def test_letter_too_short_fails():
    case = _base_case(letter_min_chars=150)
    result = _FakeResult(best_letter="Коротко.", relevance_map=_clean_map())
    errors = evaluate_pipeline_result(case, result)
    assert any("too short" in e for e in errors)


def test_letter_too_long_fails():
    case = _base_case(letter_max_chars=50)
    result = _FakeResult(best_letter="ю" * 100, relevance_map=_clean_map())
    errors = evaluate_pipeline_result(case, result)
    assert any("too long" in e for e in errors)


def test_letter_length_within_bounds_passes():
    case = _base_case(letter_min_chars=10, letter_max_chars=100)
    result = _FakeResult(best_letter="ю" * 50, relevance_map=_clean_map())
    assert evaluate_pipeline_result(case, result) == []


# --- B5: schema validation of new fields ---

def test_schema_rejects_non_list_must_mention():
    case = _base_case(must_mention="Python")
    errors = validate_case_schema(case)
    assert any("must_mention must be a list of strings" in e for e in errors)


def test_schema_rejects_min_greater_than_max():
    case = _base_case(letter_min_chars=500, letter_max_chars=100)
    errors = validate_case_schema(case)
    assert any("letter_min_chars must be <= letter_max_chars" in e for e in errors)


def test_schema_rejects_non_int_length():
    case = _base_case(letter_min_chars="150")
    errors = validate_case_schema(case)
    assert any("letter_min_chars must be a non-negative integer" in e for e in errors)


def test_schema_rejects_bool_length():
    # bool is an int subclass — must be rejected explicitly.
    case = _base_case(letter_max_chars=True)
    errors = validate_case_schema(case)
    assert any("letter_max_chars must be a non-negative integer" in e for e in errors)


def test_schema_accepts_valid_new_fields():
    case = _base_case(must_mention=["Python"], letter_min_chars=150, letter_max_chars=1600)
    assert validate_case_schema(case) == []
