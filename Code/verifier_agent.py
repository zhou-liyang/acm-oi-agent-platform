from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from verifier_v1 import verify_problem
except ModuleNotFoundError:
    from Code.verifier_v1 import verify_problem


FINAL_STATES = {
    "PACKAGE_FAIL",
    "TESTS_CORROBORATED",
    "TESTS_SUPPORTED_AFTER_ADJUDICATION",
    "REVIEW_REQUIRED",
    "INCONCLUSIVE",
    "TOOL_ERROR",
    "BLOCKED",
}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8-sig")
    )


def code_dir() -> Path:
    return Path(__file__).resolve().parent


def required_tools() -> list[Path]:
    root = code_dir()

    return [
        root / "verifier_v1.py",
        root / "verifier_v2.py",
        root / "verifier_v3.py",
        root / "case_oracle_v3_1.py",
    ]


def dependency_check() -> tuple[bool, list[str]]:
    messages: list[str] = []
    ok = True

    for path in required_tools():
        if path.is_file():
            messages.append(f"[OK] {path.name}")
        else:
            ok = False
            messages.append(f"[MISSING] {path}")

    return ok, messages


def run_process(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    log_file: Path,
) -> tuple[int, str, float]:
    started = time.perf_counter()

    process = subprocess.run(
        args,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    elapsed = time.perf_counter() - started
    text = process.stdout or ""

    log_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    log_file.write_text(
        text,
        encoding="utf-8",
    )

    return process.returncode, text, elapsed


def load_v2_problem(
    summary_file: Path,
    name: str,
) -> dict[str, Any] | None:
    if not summary_file.is_file():
        return None

    summary = read_json(summary_file)

    for item in summary.get("results", []):
        if (
            isinstance(item, dict)
            and item.get("problem") == name
        ):
            return item

    return None


def load_v3_problem(
    summary_file: Path,
    name: str,
) -> dict[str, Any] | None:
    if not summary_file.is_file():
        return None

    summary = read_json(summary_file)

    for item in summary.get("problems", []):
        if (
            isinstance(item, dict)
            and item.get("problem") == name
        ):
            return item

    return None


def load_adjudication_records(
    summary_file: Path,
    name: str,
) -> list[dict[str, Any]]:
    if not summary_file.is_file():
        return []

    summary = read_json(summary_file)

    return [
        item
        for item in summary.get("records", [])
        if (
            isinstance(item, dict)
            and item.get("problem") == name
        )
    ]


def run_v2(
    problem_root: Path,
    name: str,
    stage_dir: Path,
    attempts: int,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(code_dir() / "verifier_v2.py"),
        str(problem_root),
        "--output",
        str(stage_dir),
        "--names",
        name,
        "--attempts",
        str(attempts),
    ]

    exit_code, _, elapsed = run_process(
        command,
        log_file=stage_dir / "agent_v2.log",
    )

    item = load_v2_problem(
        stage_dir / "summary.json",
        name,
    )

    if item is None:
        return {
            "evidence": "TOOL_ERROR",
            "message": (
                "Verifier V2 did not produce a usable summary."
            ),
            "exit_code": exit_code,
            "elapsed_seconds": round(elapsed, 2),
        }

    return {
        **item,
        "agent_exit_code": exit_code,
        "agent_elapsed_seconds": round(elapsed, 2),
    }


def run_v3(
    problem_root: Path,
    v2_dir: Path,
    name: str,
    stage_dir: Path,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(code_dir() / "verifier_v3.py"),
        str(problem_root),
        str(v2_dir),
        "--output",
        str(stage_dir),
        "--names",
        name,
    ]

    exit_code, _, elapsed = run_process(
        command,
        log_file=stage_dir / "agent_v3.log",
    )

    item = load_v3_problem(
        stage_dir / "summary.json",
        name,
    )

    if item is None:
        return {
            "status": "TOOL_ERROR",
            "message": (
                "Verifier V3 did not produce a usable summary."
            ),
            "exit_code": exit_code,
            "elapsed_seconds": round(elapsed, 2),
            "suspicious_cases": [],
        }

    return {
        **item,
        "agent_exit_code": exit_code,
        "agent_elapsed_seconds": round(elapsed, 2),
    }


def run_adjudicator(
    problem_root: Path,
    v3_dir: Path,
    name: str,
    stage_dir: Path,
) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(
        {
            "DEEPSEEK_CASE_ORACLE_MODEL": "deepseek-v4-pro",
            "DEEPSEEK_CASE_ORACLE_REASONING": "high",
            "DEEPSEEK_CASE_ORACLE_MAX_TOKENS": "4096",
        }
    )

    command = [
        sys.executable,
        str(code_dir() / "case_oracle_v3_1.py"),
        str(problem_root),
        str(v3_dir),
        "--output",
        str(stage_dir),
        "--names",
        name,
    ]

    exit_code, _, elapsed = run_process(
        command,
        env=env,
        log_file=stage_dir / "agent_adjudication.log",
    )

    records = load_adjudication_records(
        stage_dir / "summary.json",
        name,
    )

    return {
        "exit_code": exit_code,
        "elapsed_seconds": round(elapsed, 2),
        "records": records,
    }


def final_from_adjudication(
    name: str,
    suspicious_cases: list[str],
    adjudication: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    records = {
        str(item.get("case")): item
        for item in adjudication.get("records", [])
        if isinstance(item, dict)
    }

    supported: list[str] = []
    contradicted: list[str] = []
    unresolved: list[str] = []
    tool_errors: list[str] = []

    case_evidence: list[dict[str, Any]] = []

    for case in suspicious_cases:
        record = records.get(case)

        if record is None:
            unresolved.append(case)
            case_evidence.append(
                {
                    "case": case,
                    "status": "MISSING",
                }
            )
            continue

        status = record.get("oracle_status")

        case_evidence.append(
            {
                "case": case,
                "status": status,
                "model": record.get("model"),
                "reasoning": record.get("reasoning"),
                "confidence": record.get("oracle_confidence"),
                "answer": record.get("oracle_answer"),
                "reason": record.get("oracle_reason"),
                "usage": record.get("usage"),
            }
        )

        if status == "SUPPORTS_EXPECTED":
            supported.append(case)
        elif status == "CONTRADICTS_EXPECTED":
            contradicted.append(case)
        elif status in ("TOOL_ERROR", "PARSE_ERROR"):
            tool_errors.append(case)
            unresolved.append(case)
        else:
            unresolved.append(case)

    evidence.append(
        {
            "stage": "ADJUDICATION",
            "model": "deepseek-v4-pro",
            "reasoning": "high",
            "max_tokens": 4096,
            "cases": case_evidence,
        }
    )

    if contradicted:
        state = "REVIEW_REQUIRED"
        message = (
            "At least one strong case adjudication independently "
            "contradicts the existing expected output. Do not auto-edit "
            "data; escalate to human or cross-provider review."
        )
    elif tool_errors:
        state = "TOOL_ERROR"
        message = (
            "Strong case adjudication did not complete normally "
            "for every shared-disagreement case."
        )
    elif unresolved:
        state = "INCONCLUSIVE"
        message = (
            "Some shared-disagreement cases remain unresolved."
        )
    else:
        state = "TESTS_SUPPORTED_AFTER_ADJUDICATION"
        message = (
            "Every shared-disagreement case was independently "
            "adjudicated in favor of the existing expected output."
        )

    return {
        "problem": name,
        "state": state,
        "message": message,
        "supported_cases": supported,
        "contradicted_cases": contradicted,
        "unresolved_cases": unresolved,
        "evidence": evidence,
    }


def verify_one(
    problem_root: Path,
    name: str,
    output_root: Path,
    attempts: int,
) -> dict[str, Any]:
    problem_dir = (
        problem_root / name
    ).resolve()
    problem_output = (
        output_root / name
    ).resolve()

    evidence: list[dict[str, Any]] = []

    v1_report = verify_problem(
        problem_dir
    )

    write_json(
        problem_output / "V1" / "report.json",
        v1_report,
    )

    evidence.append(
        {
            "stage": "V1",
            "result": v1_report["overall"],
            "counts": v1_report["counts"],
        }
    )

    if v1_report["overall"] == "FAIL":
        return {
            "problem": name,
            "state": "PACKAGE_FAIL",
            "message": (
                "Deterministic mechanical package checks failed."
            ),
            "evidence": evidence,
        }

    v2_dir = problem_output / "V2"

    v2 = run_v2(
        problem_root,
        name,
        v2_dir,
        attempts,
    )

    evidence.append(
        {
            "stage": "V2",
            "result": v2.get("evidence"),
            "attempts_run": v2.get("attempts_run"),
            "usage": v2.get("usage"),
        }
    )

    v2_evidence = v2.get("evidence")

    if v2_evidence == "CORROBORATED":
        return {
            "problem": name,
            "state": "TESTS_CORROBORATED",
            "message": (
                "A fresh whole-problem solver matched every existing test."
            ),
            "evidence": evidence,
        }

    if v2_evidence == "TOOL_ERROR":
        return {
            "problem": name,
            "state": "TOOL_ERROR",
            "message": (
                "Independent whole-problem solving failed at the tool/API layer."
            ),
            "evidence": evidence,
        }

    if v2_evidence == "BLOCKED":
        return {
            "problem": name,
            "state": "BLOCKED",
            "message": (
                "Independent solving was blocked by missing prerequisites."
            ),
            "evidence": evidence,
        }

    if v2_evidence != "INCONCLUSIVE":
        return {
            "problem": name,
            "state": "INCONCLUSIVE",
            "message": (
                "Independent solving did not produce a recognized evidence state."
            ),
            "evidence": evidence,
        }

    v3_dir = problem_output / "V3"

    v3 = run_v3(
        problem_root,
        v2_dir,
        name,
        v3_dir,
    )

    suspicious_cases = [
        str(case)
        for case in v3.get(
            "suspicious_cases",
            [],
        )
    ]

    evidence.append(
        {
            "stage": "V3",
            "result": v3.get("status"),
            "shared_disagreement_cases": suspicious_cases,
            "mixed_cases": v3.get("mixed_cases", []),
        }
    )

    if v3.get("status") == "TOOL_ERROR":
        return {
            "problem": name,
            "state": "TOOL_ERROR",
            "message": (
                "Local disagreement analysis failed."
            ),
            "evidence": evidence,
        }

    if not suspicious_cases:
        return {
            "problem": name,
            "state": "INCONCLUSIVE",
            "message": (
                "Whole-problem solvers were non-AC, but no shared "
                "candidate contradiction was found that justifies "
                "strong-model escalation."
            ),
            "evidence": evidence,
        }

    adjudication_dir = (
        problem_output / "Adjudication"
    )

    adjudication = run_adjudicator(
        problem_root,
        v3_dir,
        name,
        adjudication_dir,
    )

    return final_from_adjudication(
        name,
        suspicious_cases,
        adjudication,
        evidence,
    )


def print_result(
    result: dict[str, Any],
) -> None:
    print()
    print(
        f"Problem: {result['problem']}"
    )
    print(
        f"State  : {result['state']}"
    )
    print(
        f"Message: {result['message']}"
    )

    if result.get("supported_cases"):
        print(
            "Supported cases: "
            + ", ".join(
                result["supported_cases"]
            )
        )

    if result.get("contradicted_cases"):
        print(
            "Contradicted cases: "
            + ", ".join(
                result["contradicted_cases"]
            )
        )

    if result.get("unresolved_cases"):
        print(
            "Unresolved cases: "
            + ", ".join(
                result["unresolved_cases"]
            )
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Unified ACM/OI Verifier Agent. "
            "V1 mechanical checks -> Flash-none independent solving -> "
            "local disagreement analysis -> Pro-high case adjudication "
            "only when shared disagreement exists."
        )
    )

    parser.add_argument(
        "problem_root",
        nargs="?",
        type=Path,
    )

    parser.add_argument(
        "--names",
        nargs="+",
    )

    parser.add_argument(
        "--output",
        type=Path,
    )

    parser.add_argument(
        "--attempts",
        type=int,
        default=3,
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help="Check local dependencies only; no model API calls.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    ok, messages = dependency_check()

    if args.check:
        print()
        print("=== VERIFIER AGENT DEPENDENCY CHECK ===")

        for message in messages:
            print(message)

        print()
        print(
            "Model policy:"
        )
        print(
            "  Initial solve : deepseek-v4-flash / none"
        )
        print(
            "  Adjudication  : deepseek-v4-pro / high"
        )
        print(
            "  Flash-low case oracle: disabled"
        )
        print(
            "No model API request was made."
        )

        return 0 if ok else 1

    if not ok:
        for message in messages:
            print(message)
        return 1

    if args.problem_root is None:
        print(
            "ERROR: problem_root is required unless --check is used."
        )
        return 1

    if not args.names:
        print(
            "ERROR: --names requires at least one problem."
        )
        return 1

    if args.output is None:
        print(
            "ERROR: --output is required."
        )
        return 1

    if args.attempts < 1 or args.attempts > 3:
        print(
            "ERROR: --attempts must be between 1 and 3."
        )
        return 1

    output_root = args.output.resolve()
    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print("=== UNIFIED VERIFIER AGENT ===")
    print(
        f"Problem root : {args.problem_root.resolve()}"
    )
    print(
        f"Output       : {output_root}"
    )
    print(
        f"Problems     : {', '.join(args.names)}"
    )
    print(
        f"Flash attempts: {args.attempts}"
    )
    print(
        "Escalation   : Pro-high only on shared case disagreement"
    )

    results: list[dict[str, Any]] = []

    for index, name in enumerate(
        args.names,
        start=1,
    ):
        print()
        print(
            f"=== [{index}/{len(args.names)}] {name} ==="
        )

        result = verify_one(
            args.problem_root.resolve(),
            name,
            output_root,
            args.attempts,
        )

        results.append(result)
        print_result(result)

        write_json(
            output_root / "summary_partial.json",
            {
                "completed": len(results),
                "planned": len(args.names),
                "results": results,
            },
        )

    counts = {
        state: sum(
            item["state"] == state
            for item in results
        )
        for state in sorted(FINAL_STATES)
    }

    summary = {
        "policy": {
            "v1": "deterministic mechanical package checks",
            "v2": {
                "model": "deepseek-v4-flash",
                "reasoning": "none",
                "max_attempts": args.attempts,
                "repair": False,
            },
            "v3": (
                "local disagreement matrix; no model API"
            ),
            "adjudication": {
                "model": "deepseek-v4-pro",
                "reasoning": "high",
                "max_tokens": 4096,
                "trigger": "shared disagreement only",
            },
        },
        "counts": counts,
        "results": results,
    }

    write_json(
        output_root / "summary.json",
        summary,
    )

    print()
    print("=== FINAL SUMMARY ===")

    for state in sorted(FINAL_STATES):
        if counts[state]:
            print(
                f"{state}: {counts[state]}"
            )

    print()
    print(
        f"Report: {output_root / 'summary.json'}"
    )

    if counts["PACKAGE_FAIL"]:
        return 1

    if counts["TOOL_ERROR"]:
        return 1

    if counts["BLOCKED"]:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
