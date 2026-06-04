import argparse
import sqlite3
from pathlib import Path

from app.observability import TRACE_DB_NAME


def _format_ms(value: int | None) -> str:
    return "-" if value is None else f"{value}ms"


def print_recent_runs(limit: int) -> int:
    db_path = Path(TRACE_DB_NAME)
    if not db_path.exists():
        print(f"Trace DB not found: {db_path}")
        return 1

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        runs = conn.execute(
            """
            SELECT run_id, created_at, model, status, final_score, total_latency_ms, error
            FROM llm_runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        if not runs:
            print("No trace runs found.")
            return 0

        for run in runs:
            print(
                f"{run['created_at']}  {run['status']}  "
                f"score={run['final_score']}  latency={_format_ms(run['total_latency_ms'])}"
            )
            print(f"run_id={run['run_id']}")
            print(f"model={run['model']}")
            if run["error"]:
                print(f"error={run['error']}")

            steps = conn.execute(
                """
                SELECT step_name, status, latency_ms, input_tokens, output_tokens, error
                FROM llm_steps
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run["run_id"],),
            ).fetchall()

            for step in steps:
                tokens = "-"
                if step["input_tokens"] is not None or step["output_tokens"] is not None:
                    tokens = f"{step['input_tokens'] or 0}/{step['output_tokens'] or 0}"
                line = (
                    f"  - {step['step_name']}: {step['status']}, "
                    f"latency={_format_ms(step['latency_ms'])}, tokens={tokens}"
                )
                if step["error"]:
                    line += f", error={step['error']}"
                print(line)

            input_tokens = sum(step["input_tokens"] or 0 for step in steps)
            output_tokens = sum(step["output_tokens"] or 0 for step in steps)
            if input_tokens or output_tokens:
                print(f"  total_tokens={input_tokens}/{output_tokens}")
            print()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Print recent LLM trace runs.")
    parser.add_argument("--last", type=int, default=5, help="Number of recent runs to show.")
    args = parser.parse_args()

    if args.last < 1:
        print("--last must be >= 1")
        return 1

    return print_recent_runs(args.last)


if __name__ == "__main__":
    raise SystemExit(main())
