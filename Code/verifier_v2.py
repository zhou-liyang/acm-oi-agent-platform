from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from verifier_v1 import verify_problem
    from model_router import initial_routes
except ModuleNotFoundError:
    from Code.verifier_v1 import verify_problem
    from Code.model_router import initial_routes


USAGE_RE = re.compile(
    r"Usage:\s*"
    r"input=(\d+),\s*"
    r"cached=(\d+),\s*"
    r"(?:miss=(\d+),\s*)?"
    r"output=(\d+),\s*"
    r"reasoning=(\d+)"
)

JUDGE_RE = re.compile(
    r"Judge:\s*(\d+)/(\d+)\s+([A-Z_]+)"
)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_meta(problem_dir: Path) -> dict[str, Any]:
    path = problem_dir / "problem.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def statement_path(problem_dir: Path) -> Path | None:
    for name in ("statement.md", "problem.md"):
        path = problem_dir / name
        if path.is_file():
            return path
    return None


def parse_usage(text: str) -> dict[str, int]:
    match = USAGE_RE.search(text)
    if match is None:
        return {
            "input_tokens": 0,
            "cached_tokens": 0,
            "cache_miss_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        }

    input_tokens = int(match.group(1))
    cached_tokens = int(match.group(2))
    miss_group = match.group(3)
    output_tokens = int(match.group(4))
    reasoning_tokens = int(match.group(5))

    return {
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "cache_miss_tokens": (
            int(miss_group)
            if miss_group is not None
            else max(0, input_tokens - cached_tokens)
        ),
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
    }


def parse_judge(text: str) -> dict[str, Any] | None:
    match = JUDGE_RE.search(text)
    if match is None:
        return None
    return {
        "passed": int(match.group(1)),
        "total": int(match.group(2)),
        "verdict": match.group(3),
    }


def run_attempt(
    problem_dir: Path,
    statement: Path,
    problem_output: Path,
    attempt_number: int,
    *,
    provider: str,
    model: str,
    reasoning: str,
    max_tokens: int,
    thinking_budget: int | None,
) -> dict[str, Any]:
    code_dir = Path(__file__).resolve().parent
    solve_once = code_dir / "solve_once.py"

    safe_provider = re.sub(r"[^a-z0-9_-]+", "_", provider.lower())
    source = (
        problem_output
        / f"independent_{attempt_number:02d}_{safe_provider}.cpp"
    )
    log = (
        problem_output
        / f"solver_{attempt_number:02d}_{safe_provider}.log"
    )

    env = os.environ.copy()
    env.update(
        {
            "MODEL_PROVIDER": provider,
            "MODEL_NAME": model,
            "MODEL_REASONING": reasoning,
            "MODEL_MAX_TOKENS": str(max_tokens),
        }
    )
    if thinking_budget is None:
        env.pop("MODEL_THINKING_BUDGET", None)
    else:
        env["MODEL_THINKING_BUDGET"] = str(thinking_budget)

    started = time.perf_counter()
    process = subprocess.run(
        [
            sys.executable,
            str(solve_once),
            str(problem_dir),
            str(statement),
            str(source),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.perf_counter() - started
    text = process.stdout or ""
    log.write_text(text, encoding="utf-8")

    judge = parse_judge(text)
    usage = parse_usage(text)

    if process.returncode == 0:
        status = "AC"
    elif process.returncode == 2:
        status = "NON_AC"
    else:
        status = "TOOL_ERROR"

    return {
        "attempt": attempt_number,
        "provider": provider,
        "model": model,
        "reasoning": reasoning,
        "max_tokens": max_tokens,
        "thinking_budget": thinking_budget,
        "status": status,
        "exit_code": process.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "judge": judge,
        "usage": usage,
        "source": str(source) if source.is_file() else None,
        "log": str(log),
    }


def aggregate_usage(attempts: list[dict[str, Any]]) -> dict[str, int]:
    keys = (
        "input_tokens",
        "cached_tokens",
        "cache_miss_tokens",
        "output_tokens",
        "reasoning_tokens",
    )
    return {
        key: sum(int(item["usage"].get(key, 0)) for item in attempts)
        for key in keys
    }


def verify_independent(
    problem_dir: Path,
    output_dir: Path,
    requested_attempts: int = 1,
) -> dict[str, Any]:
    problem_dir = problem_dir.resolve()
    output_dir = output_dir.resolve()

    v1 = verify_problem(problem_dir)
    meta = load_meta(problem_dir)
    routes = initial_routes()

    result: dict[str, Any] = {
        "problem": problem_dir.name,
        "problem_dir": str(problem_dir),
        "difficulty": str(meta.get("difficulty", "")),
        "v1_overall": v1["overall"],
        "evidence": "",
        "evidence_message": "",
        "attempts_planned": len(routes),
        "attempts_run": 0,
        "attempts": [],
        "usage": {},
        "elapsed_seconds": 0.0,
        "policy": {
            "providers": [route.provider for route in routes],
            "one_vote_per_provider": True,
            "same_provider_resampling": False,
            "legacy_attempts_argument": requested_attempts,
        },
    }

    if v1["overall"] == "FAIL":
        result["evidence"] = "BLOCKED"
        result["evidence_message"] = (
            "Verifier V1 found a mechanical failure, so independent solving was skipped."
        )
        return result

    statement = statement_path(problem_dir)
    if statement is None:
        result["evidence"] = "BLOCKED"
        result["evidence_message"] = "No statement.md/problem.md is available."
        return result

    solve_once = Path(__file__).resolve().parent / "solve_once.py"
    if not solve_once.is_file():
        result["evidence"] = "TOOL_ERROR"
        result["evidence_message"] = f"Missing solver tool: {solve_once}"
        return result

    problem_output = output_dir / problem_dir.name
    if problem_output.exists():
        for path in problem_output.iterdir():
            if path.is_file():
                path.unlink()
    problem_output.mkdir(parents=True, exist_ok=True)

    attempts: list[dict[str, Any]] = []
    for attempt_number, route in enumerate(routes, start=1):
        attempts.append(
            run_attempt(
                problem_dir,
                statement,
                problem_output,
                attempt_number,
                provider=route.provider,
                model=route.model,
                reasoning=route.reasoning,
                max_tokens=route.max_tokens,
                thinking_budget=route.thinking_budget,
            )
        )

    tool_errors = [item for item in attempts if item["status"] == "TOOL_ERROR"]
    ac_attempts = [item for item in attempts if item["status"] == "AC"]
    normal_attempts = [item for item in attempts if item["status"] != "TOOL_ERROR"]

    if tool_errors:
        evidence = "TOOL_ERROR"
        evidence_message = (
            "At least one required provider failed before a normal judged result; "
            "the two-provider evidence pair is incomplete."
        )
    elif len(ac_attempts) == len(routes):
        evidence = "CORROBORATED"
        evidence_message = (
            "Both independent providers produced fresh whole-problem solvers "
            "that matched every existing test."
        )
    elif normal_attempts:
        evidence = "INCONCLUSIVE"
        evidence_message = (
            "The two independent providers did not both match every test. "
            "Proceed to deterministic case-level disagreement analysis."
        )
    else:
        evidence = "TOOL_ERROR"
        evidence_message = "No provider produced a normal judged result."

    usage = aggregate_usage(attempts)
    elapsed = round(sum(item["elapsed_seconds"] for item in attempts), 2)

    result.update(
        {
            "evidence": evidence,
            "evidence_message": evidence_message,
            "attempts_run": len(attempts),
            "attempts": attempts,
            "usage": usage,
            "elapsed_seconds": elapsed,
        }
    )
    write_json(problem_output / "report.json", result)
    return result


def discover(root: Path, difficulty: str, names: set[str] | None) -> list[Path]:
    items: list[Path] = []
    for problem_dir in sorted(root.iterdir(), key=lambda path: path.name.lower()):
        if not problem_dir.is_dir():
            continue
        if names is not None and problem_dir.name not in names:
            continue
        meta = load_meta(problem_dir)
        current = str(meta.get("difficulty", ""))
        if difficulty != "all" and current != difficulty:
            continue
        items.append(problem_dir)
    return items


def judge_text(attempt: dict[str, Any]) -> str:
    judge = attempt.get("judge")
    if not isinstance(judge, dict):
        return "-"
    return f"{judge['passed']}/{judge['total']} {judge['verdict']}"


def print_problem_result(result: dict[str, Any]) -> None:
    attempt_parts = [
        f"{item['provider']}={judge_text(item)}"
        for item in result["attempts"]
    ]
    usage = result["usage"]
    print(
        f"{result['problem']:<16} "
        f"{result['evidence']:<14} "
        f"[{'; '.join(attempt_parts)}] "
        f"tokens={usage.get('input_tokens', 0)}+{usage.get('output_tokens', 0)} "
        f"time={result['elapsed_seconds']:.2f}s"
    )


def run_batch(
    root: Path,
    output_dir: Path,
    difficulty: str,
    names: set[str] | None,
    requested_attempts: int,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    if not root.is_dir():
        raise ValueError(f"Problem root does not exist: {root}")

    problems = discover(root, difficulty, names)
    if not problems:
        raise ValueError("No matching problem directories.")

    routes = initial_routes()
    print()
    print("=== VERIFIER V2.2: TWO-PROVIDER INDEPENDENT CROSS-CHECK ===")
    print(f"Root       : {root}")
    print(f"Output     : {output_dir}")
    print(f"Difficulty : {difficulty}")
    print(f"Problems   : {len(problems)}")
    print("Initial votes:")
    for route in routes:
        print(
            f"  {route.provider:<8} {route.model} / {route.reasoning} "
            f"/ max_tokens={route.max_tokens}"
        )
    if requested_attempts != 1:
        print(
            f"NOTE: --attempts={requested_attempts} is retained only for CLI "
            "compatibility; V2.2 always uses one independent vote per provider."
        )
    print("Repair     : disabled")
    print("Feedback   : no expected output / no prior candidate code")
    print()

    results: list[dict[str, Any]] = []
    for index, problem_dir in enumerate(problems, start=1):
        print(f"[{index}/{len(problems)}] {problem_dir.name}")
        result = verify_independent(
            problem_dir,
            output_dir,
            requested_attempts,
        )
        results.append(result)
        print_problem_result(result)
        write_json(
            output_dir / "summary_partial.json",
            {
                "root": str(root),
                "difficulty": difficulty,
                "completed": len(results),
                "planned": len(problems),
                "results": results,
            },
        )

    evidence_keys = ("CORROBORATED", "INCONCLUSIVE", "TOOL_ERROR", "BLOCKED")
    counts = {
        key: sum(item["evidence"] == key for item in results)
        for key in evidence_keys
    }
    usage_keys = (
        "input_tokens",
        "cached_tokens",
        "cache_miss_tokens",
        "output_tokens",
        "reasoning_tokens",
    )
    totals = {
        key: sum(int(item["usage"].get(key, 0)) for item in results)
        for key in usage_keys
    }
    totals["elapsed_seconds"] = round(
        sum(item["elapsed_seconds"] for item in results),
        2,
    )

    summary = {
        "root": str(root),
        "difficulty": difficulty,
        "problem_count": len(results),
        "routing": [route.__dict__ for route in routes],
        "evidence_counts": counts,
        "usage_totals": totals,
        "results": results,
    }
    write_json(output_dir / "summary.json", summary)

    print()
    print("=== V2.2 SUMMARY ===")
    print(
        "Evidence: "
        f"CORROBORATED={counts['CORROBORATED']} "
        f"INCONCLUSIVE={counts['INCONCLUSIVE']} "
        f"TOOL_ERROR={counts['TOOL_ERROR']} "
        f"BLOCKED={counts['BLOCKED']}"
    )
    print(
        "Tokens  : "
        f"{totals['input_tokens']} in + {totals['output_tokens']} out "
        f"({totals['reasoning_tokens']} reasoning)"
    )
    print(f"Summary : {output_dir / 'summary.json'}")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verifier V2.2: one independent whole-problem solve from DeepSeek "
            "and one from Qwen, without repair feedback."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--difficulty",
        choices=("all", "silver", "gold-easy"),
        default="all",
    )
    parser.add_argument("--names", nargs="*")
    parser.add_argument(
        "--attempts",
        type=int,
        default=1,
        help="Deprecated compatibility option; V2.2 always uses one vote per provider.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.attempts < 1:
        print("ERROR: --attempts must be at least 1.")
        return 1

    names = set(args.names) if args.names else None
    try:
        summary = run_batch(
            args.root,
            args.output,
            args.difficulty,
            names,
            args.attempts,
        )
    except ValueError as error:
        print(f"ERROR: {error}")
        return 1

    if summary["evidence_counts"]["TOOL_ERROR"]:
        return 1
    if summary["evidence_counts"]["BLOCKED"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
