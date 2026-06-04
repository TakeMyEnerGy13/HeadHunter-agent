import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.cover_letter_pipeline import run_cover_letter_pipeline_result
from app.evals.checks import evaluate_pipeline_result, validate_case_schema

DEFAULT_DATASET = Path("evals") / "dataset.jsonl"


def load_cases(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    cases = []
    errors = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                case = json.loads(stripped)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: invalid JSON: {exc}")
                continue

            schema_errors = validate_case_schema(case)
            if schema_errors:
                errors.extend(f"{case.get('id', f'line {line_number}')}: {error}" for error in schema_errors)
            else:
                cases.append(case)
    return cases, errors


async def run_evals(
    cases: list[dict[str, Any]],
    limit: int | None = None,
    case_ids: set[str] | None = None,
    output_path: Path | None = None,
) -> int:
    if case_ids:
        available_ids = {case["id"] for case in cases}
        missing_ids = sorted(case_ids - available_ids)
        if missing_ids:
            print("Unknown case id(s):")
            for case_id in missing_ids:
                print(f"- {case_id}")
            return 1

    selected_cases = [case for case in cases if not case_ids or case["id"] in case_ids]
    selected_cases = selected_cases[:limit] if limit else selected_cases
    if not selected_cases:
        print("No eval cases selected.")
        return 1

    failed = {}
    results = []

    for index, case in enumerate(selected_cases, start=1):
        case_id = case["id"]
        print(f"[{index}/{len(selected_cases)}] {case_id}")
        try:
            result = await run_cover_letter_pipeline_result(
                job_text=case["vacancy"],
                resume_text=case["resume"],
                tone_samples=case.get("tone_samples", ""),
                preferences=case.get("preferences", ""),
            )
        except Exception as exc:
            errors = [f"pipeline error: {exc}"]
            failed[case_id] = errors
            results.append({"id": case_id, "passed": False, "errors": errors})
            continue

        errors = evaluate_pipeline_result(case, result)
        results.append(
            {
                "id": case_id,
                "passed": not errors,
                "errors": errors,
                "expected_decision": case["expected_decision"],
                "actual_decision": result.relevance_map.get("decision"),
                "expected_score_min": case["expected_score_min"],
                "expected_score_max": case["expected_score_max"],
                "actual_score": result.relevance_map.get("score"),
                "critic_score": result.best_score,
                "matches": result.relevance_map.get("matches", []),
                "gaps": result.relevance_map.get("gaps", []),
                "key_selling_points": result.relevance_map.get("key_selling_points", []),
            }
        )
        if errors:
            failed[case_id] = errors

    passed = len(selected_cases) - len(failed)
    print()
    print(f"Cases: {len(selected_cases)}")
    print(f"Passed: {passed}")
    print(f"Failed: {len(failed)}")

    if failed:
        print()
        print("Failed cases:")
        for case_id, errors in failed.items():
            print(f"- {case_id}")
            for error in errors:
                print(f"  - {error}")

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cases": len(selected_cases),
            "passed": passed,
            "failed": len(failed),
            "results": results,
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print()
        print(f"Saved report: {output_path}")

    if failed:
        return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LLM evals for the cover letter pipeline.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Path to JSONL eval dataset.")
    parser.add_argument("--limit", type=int, default=None, help="Run only first N cases.")
    parser.add_argument("--case-id", action="append", default=None, help="Run a specific case id. Can be used multiple times.")
    parser.add_argument("--dry-run", action="store_true", help="Validate dataset without calling LLM.")
    parser.add_argument("--output", default=None, help="Optional path for JSON eval report.")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"Dataset not found: {dataset_path}", file=sys.stderr)
        return 1

    cases, errors = load_cases(dataset_path)
    if errors:
        print("Dataset validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    if args.dry_run:
        print(f"Dataset OK: {len(cases)} cases")
        return 0

    output_path = Path(args.output) if args.output else None
    case_ids = set(args.case_id) if args.case_id else None
    return asyncio.run(run_evals(cases, limit=args.limit, case_ids=case_ids, output_path=output_path))


if __name__ == "__main__":
    raise SystemExit(main())
