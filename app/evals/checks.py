from typing import Any

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
    ):
        value = case.get(list_field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append(f"{list_field} must be a list of strings")

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
        if _normalize(phrase) in normalized_letter:
            errors.append(f"letter contains forbidden phrase: {phrase}")

    for claim in case.get("must_not_claim", []):
        if _normalize(claim) in normalized_letter:
            errors.append(f"letter contains forbidden claim: {claim}")

    gaps_text = " ".join(str(gap) for gap in relevance_map.get("gaps", []))
    normalized_gaps = _normalize(gaps_text)
    for phrase in case.get("forbidden_gap_phrases", []):
        if _normalize(phrase) in normalized_gaps:
            errors.append(f"gaps contain forbidden phrase: {phrase}")

    relevance_text = str(relevance_map)
    normalized_relevance = _normalize(relevance_text)
    for phrase in case.get("forbidden_relevance_phrases", []):
        if _normalize(phrase) in normalized_relevance:
            errors.append(f"relevance_map contains forbidden phrase: {phrase}")

    return errors
