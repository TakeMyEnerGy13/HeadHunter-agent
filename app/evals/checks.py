from typing import Any

# A4: single source of truth for phrase matching. The pipeline uses word-boundary
# matching (with a "с уважением" sign-off special case); evals must match the same
# way so an eval phrase can't false-positive on a substring (e.g. "привет" in
# "приветствовать").
from app.agents.cover_letter_pipeline import _has_forbidden_phrase

REQUIRED_FIELDS = (
    "schema_version",
    "id",
    "resume",
    "vacancy",
    "expected_decision",
    "expected_score_min",
    "expected_score_max",
)

VALID_DECISIONS = {"good", "maybe", "bad"}


def _normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def validate_case_schema(case: dict[str, Any]) -> list[str]:
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in case:
            errors.append(f"missing field: {field}")

    decision = case.get("expected_decision")
    if decision is not None and decision not in VALID_DECISIONS:
        errors.append(f"invalid expected_decision: {decision}")

    score_min = case.get("expected_score_min")
    score_max = case.get("expected_score_max")
    if not isinstance(score_min, int) or not isinstance(score_max, int):
        errors.append("expected_score_min/max must be integers")
    elif score_min < 0 or score_max > 100 or score_min > score_max:
        errors.append("invalid expected score range")

    for list_field in (
        "forbidden_letter_phrases",
        "must_not_claim",
        "forbidden_gap_phrases",
        "forbidden_relevance_phrases",
        "must_mention",
    ):
        value = case.get(list_field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append(f"{list_field} must be a list of strings")

    # B5: optional length guard. Present values must be non-negative ints with min <= max.
    letter_min = case.get("letter_min_chars")
    letter_max = case.get("letter_max_chars")
    for field_name, value in (("letter_min_chars", letter_min), ("letter_max_chars", letter_max)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            errors.append(f"{field_name} must be a non-negative integer")
    if (
        isinstance(letter_min, int)
        and not isinstance(letter_min, bool)
        and isinstance(letter_max, int)
        and not isinstance(letter_max, bool)
        and letter_min > letter_max
    ):
        errors.append("letter_min_chars must be <= letter_max_chars")

    return errors


def evaluate_pipeline_result(case: dict[str, Any], result: Any) -> list[str]:
    errors = []
    relevance_map = result.relevance_map or {}
    score = relevance_map.get("score")
    decision = relevance_map.get("decision")

    try:
        score = int(score)
    except (TypeError, ValueError):
        errors.append("matcher did not return integer score")
        score = None

    if score is not None:
        expected_min = case["expected_score_min"]
        expected_max = case["expected_score_max"]
        if not expected_min <= score <= expected_max:
            errors.append(f"score {score} outside expected range {expected_min}-{expected_max}")

    if decision != case["expected_decision"]:
        errors.append(f"decision {decision!r} != expected {case['expected_decision']!r}")

    letter = result.best_letter or ""
    normalized_letter = _normalize(letter)

    for phrase in case.get("forbidden_letter_phrases", []):
        if _has_forbidden_phrase(normalized_letter, phrase):
            errors.append(f"letter contains forbidden phrase: {phrase}")

    for claim in case.get("must_not_claim", []):
        if _has_forbidden_phrase(normalized_letter, claim):
            errors.append(f"letter contains forbidden claim: {claim}")

    # B5: positive check — the letter must actually mention these facts (word-boundary).
    for phrase in case.get("must_mention", []):
        if not _has_forbidden_phrase(normalized_letter, phrase):
            errors.append(f"letter missing required mention: {phrase}")

    # B5: length guard against degenerate output (truncated stub or wall of text).
    letter_length = len(letter.strip())
    letter_min = case.get("letter_min_chars")
    letter_max = case.get("letter_max_chars")
    if isinstance(letter_min, int) and not isinstance(letter_min, bool) and letter_length < letter_min:
        errors.append(f"letter too short: {letter_length} chars < {letter_min}")
    if isinstance(letter_max, int) and not isinstance(letter_max, bool) and letter_length > letter_max:
        errors.append(f"letter too long: {letter_length} chars > {letter_max}")

    gaps_text = " ".join(str(gap) for gap in relevance_map.get("gaps", []))
    normalized_gaps = _normalize(gaps_text)
    for phrase in case.get("forbidden_gap_phrases", []):
        if _has_forbidden_phrase(normalized_gaps, phrase):
            errors.append(f"gaps contain forbidden phrase: {phrase}")

    relevance_text = str(relevance_map)
    normalized_relevance = _normalize(relevance_text)
    for phrase in case.get("forbidden_relevance_phrases", []):
        if _has_forbidden_phrase(normalized_relevance, phrase):
            errors.append(f"relevance_map contains forbidden phrase: {phrase}")

    return errors
