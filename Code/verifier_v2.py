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
except ModuleNotFoundError:
    from Code.verifier_v1 import verify_problem


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

ATTEMPT_PREFIXES = (
    "",
    (
        "Internal verifier instruction: solve the following problem "
        "independently from first principles. Avoid relying on a guessed "
        "template; derive the mathematical condition carefully. "
        "The actual problem statement follows.\n\n"
    ),
    (
        "Internal verifier instruction: perform an independent verification "
        "solve. Pay special attention to boundary cases, integer arithmetic, "
        "and whether an apparently obvious greedy or formula has exceptions. "
        "The actual problem statement follows.\n\n"
    ),
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
        data = json.loads(
            path.read_text(encoding="utf-8-sig")
        )
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

    cache_miss_tokens = (
        int(miss_group)
        if miss_group is not None
        else max(0, input_tokens - cached_tokens)
    )

    return {
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "cache_miss_tokens": cache_miss_tokens,
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


def make_statement_variant(
    original: Path,
    target: Path,
    attempt_index: int,
) -> Path:
    if attempt_index == 0:
        return original

    text = original.read_text(
        encoding="utf-8-sig",
    )

    prefix = ATTEMPT_PREFIXES[
        min(attempt_index, len(ATTEMPT_PREFIXES) - 1)
    ]

    target.write_text(
        prefix + text,
        encoding="utf-8",
    )

    return target


def run_attempt(
    problem_dir: Path,
    statement: Path,
    problem_output: Path,
    attempt_number: int,
) -> dict[str, Any]:
    code_dir = Path(__file__).resolve().parent
    solve_once = code_dir / "solve_once.py"

    source = (
        problem_output
        / f"independent_{attempt_number:02d}.cpp"
    )
    log = (
        problem_output
        / f"solver_{attempt_number:02d}.log"
    )
    variant_statement = (
        problem_output
        / f"statement_attempt_{attempt_number:02d}.md"
    )

    used_statement = make_statement_variant(
        statement,
        variant_statement,
        attempt_number - 1,
    )

    env = os.environ.copy()
    env.update(
        {
            "DEEPSEEK_SOLVER_MODEL": "deepseek-v4-flash",
            "DEEPSEEK_SOLVER_REASONING": "none",
            "DEEPSEEK_SOLVER_MAX_TOKENS": "3072",
        }
    )

    started = time.perf_counter()

    process = subprocess.run(
        [
            sys.executable,
            str(solve_once),
            str(problem_dir),
            str(used_statement),
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
        "status": status,
        "exit_code": process.returncode,
        "elapsed_seconds": round(elapsed, 2),
        "judge": judge,
        "usage": usage,
        "source": str(source) if source.is_file() else None,
        "log": str(log),
        "statement_variant": (
            str(used_statement)
            if used_statement != statement
            else None
        ),
    }


def aggregate_usage(
    attempts: list[dict[str, Any]],
) -> dict[str, int]:
    keys = (
        "input_tokens",
        "cached_tokens",
        "cache_miss_tokens",
        "output_tokens",
        "reasoning_tokens",
    )

    return {
        key: sum(
            int(item["usage"].get(key, 0))
            for item in attempts
        )
        for key in keys
    }


def verify_independent(
    problem_dir: Path,
    output_dir: Path,
    max_attempts: int,
) -> dict[str, Any]:
    problem_dir = problem_dir.resolve()
    output_dir = output_dir.resolve()

    v1 = verify_problem(problem_dir)
    meta = load_meta(problem_dir)

    result: dict[str, Any] = {
        "problem": problem_dir.name,
        "problem_dir": str(problem_dir),
        "difficulty": str(meta.get("difficulty", "")),
        "v1_overall": v1["overall"],
        "evidence": "",
        "evidence_message": "",
        "attempts_planned": max_attempts,
        "attempts_run": 0,
        "attempts": [],
        "usage": {},
        "elapsed_seconds": 0.0,
    }

    if v1["overall"] == "FAIL":
        result["evidence"] = "BLOCKED"
        result["evidence_message"] = (
            "Verifier V1 found a mechanical failure, "
            "so independent solving was skipped."
        )
        return result

    statement = statement_path(problem_dir)

    if statement is None:
        result["evidence"] = "BLOCKED"
        result["evidence_message"] = (
            "No statement.md/problem.md is available."
        )
        return result

    code_dir = Path(__file__).resolve().parent
    solve_once = code_dir / "solve_once.py"

    if not solve_once.is_file():
        result["evidence"] = "TOOL_ERROR"
        result["evidence_message"] = (
            f"Missing solver tool: {solve_once}"
        )
        return result

    problem_output = output_dir / problem_dir.name

    if problem_output.exists():
        for path in problem_output.iterdir():
            if path.is_file():
                path.unlink()

    problem_output.mkdir(parents=True, exist_ok=True)

    attempts: list[dict[str, Any]] = []

    for attempt_number in range(1, max_attempts + 1):
        attempt = run_attempt(
            problem_dir,
            statement,
            problem_output,
            attempt_number,
        )
        attempts.append(attempt)

        if attempt["status"] == "AC":
            break

    normal_attempts = [
        item
        for item in attempts
        if item["status"] != "TOOL_ERROR"
    ]
    ac_attempts = [
        item
        for item in attempts
        if item["status"] == "AC"
    ]

    if ac_attempts:
        evidence = "CORROBORATED"
        evidence_message = (
            "At least one fresh independent solver, without "
            "seeing expected outputs or prior candidate code, "
            "matched every existing test."
        )
    elif normal_attempts:
        evidence = "INCONCLUSIVE"
        evidence_message = (
            "Independent solvers did not match every test. "
            "This is not evidence that the problem package is wrong."
        )
    else:
        evidence = "TOOL_ERROR"
        evidence_message = (
            "Every independent attempt failed before a normal judged result."
        )

    usage = aggregate_usage(attempts)
    elapsed = round(
        sum(
            item["elapsed_seconds"]
            for item in attempts
        ),
        2,
    )

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

    write_json(
        problem_output / "report.json",
        result,
    )

    return result


def discover(
    root: Path,
    difficulty: str,
    names: set[str] | None,
) -> list[Path]:
    items: list[Path] = []

    for problem_dir in sorted(
        root.iterdir(),
        key=lambda path: path.name.lower(),
    ):
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


def judge_text(
    attempt: dict[str, Any],
) -> str:
    judge = attempt.get("judge")

    if not isinstance(judge, dict):
        return "-"

    return (
        f"{judge['passed']}/{judge['total']} "
        f"{judge['verdict']}"
    )


def print_problem_result(
    result: dict[str, Any],
) -> None:
    attempt_parts = [
        judge_text(item)
        for item in result["attempts"]
    ]

    usage = result["usage"]

    print(
        f"{result['problem']:<16} "
        f"{result['evidence']:<14} "
        f"attempts={result['attempts_run']} "
        f"[{'; '.join(attempt_parts)}] "
        f"tokens={usage.get('input_tokens', 0)}+"
        f"{usage.get('output_tokens', 0)} "
        f"time={result['elapsed_seconds']:.2f}s"
    )


def run_batch(
    root: Path,
    output_dir: Path,
    difficulty: str,
    names: set[str] | None,
    max_attempts: int,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = output_dir.resolve()

    if not root.is_dir():
        raise ValueError(
            f"Problem root does not exist: {root}"
        )

    problems = discover(
        root,
        difficulty,
        names,
    )

    if not problems:
        raise ValueError(
            "No matching problem directories."
        )

    print()
    print("=== VERIFIER V2.1: INDEPENDENT CROSS-CHECK ===")
    print(f"Root         : {root}")
    print(f"Output       : {output_dir}")
    print(f"Difficulty   : {difficulty}")
    print(f"Problems     : {len(problems)}")
    print(f"Max attempts : {max_attempts}")
    print("Model        : deepseek-v4-flash")
    print("Reasoning    : none")
    print("Repair       : disabled")
    print("Feedback     : no expected output / no prior code")
    print(
        "Semantics    : non-AC means INCONCLUSIVE, "
        "never problem FAIL"
    )
    print()

    results: list[dict[str, Any]] = []

    for index, problem_dir in enumerate(
        problems,
        start=1,
    ):
        print(
            f"[{index}/{len(problems)}] "
            f"{problem_dir.name}"
        )

        result = verify_independent(
            problem_dir,
            output_dir,
            max_attempts,
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

    evidence_keys = (
        "CORROBORATED",
        "INCONCLUSIVE",
        "TOOL_ERROR",
        "BLOCKED",
    )

    counts = {
        key: sum(
            item["evidence"] == key
            for item in results
        )
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
        key: sum(
            int(item["usage"].get(key, 0))
            for item in results
        )
        for key in usage_keys
    }

    totals["elapsed_seconds"] = round(
        sum(
            item["elapsed_seconds"]
            for item in results
        ),
        2,
    )

    summary = {
        "root": str(root),
        "difficulty": difficulty,
        "max_attempts": max_attempts,
        "problem_count": len(results),
        "evidence_counts": counts,
        "usage_totals": totals,
        "results": results,
    }

    write_json(
        output_dir / "summary.json",
        summary,
    )

    print()
    print("=== V2.1 SUMMARY ===")
    print(
        "Evidence: "
        f"CORROBORATED={counts['CORROBORATED']} "
        f"INCONCLUSIVE={counts['INCONCLUSIVE']} "
        f"TOOL_ERROR={counts['TOOL_ERROR']} "
        f"BLOCKED={counts['BLOCKED']}"
    )
    print(
        "Tokens  : "
        f"{totals['input_tokens']} in + "
        f"{totals['output_tokens']} out "
        f"({totals['reasoning_tokens']} reasoning)"
    )
    print(
        f"Summary : {output_dir / 'summary.json'}"
    )

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verifier V2.1: bounded independent solver quorum "
            "without repair feedback."
        )
    )

    parser.add_argument(
        "root",
        type=Path,
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--difficulty",
        choices=(
            "all",
            "silver",
            "gold-easy",
        ),
        default="all",
    )

    parser.add_argument(
        "--names",
        nargs="*",
    )

    parser.add_argument(
        "--attempts",
        type=int,
        default=1,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.attempts < 1 or args.attempts > 3:
        print("ERROR: --attempts must be between 1 and 3.")
        return 1

    names = (
        set(args.names)
        if args.names
        else None
    )

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
