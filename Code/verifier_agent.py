from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    from verifier_v1 import verify_problem
    from model_router import adjudication_routes, initial_routes, routing_snapshot
    from model_providers import get_provider
except ModuleNotFoundError:
    from Code.verifier_v1 import verify_problem
    from Code.model_router import adjudication_routes, initial_routes, routing_snapshot
    from Code.model_providers import get_provider


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
    return json.loads(path.read_text(encoding="utf-8-sig"))


def code_dir() -> Path:
    return Path(__file__).resolve().parent


def required_tools() -> list[Path]:
    root = code_dir()
    return [
        root / "model_client.py",
        root / "model_providers.py",
        root / "model_router.py",
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


def key_status() -> list[str]:
    load_dotenv()
    lines: list[str] = []
    for name in ("deepseek", "qwen"):
        provider = get_provider(name)
        state = "SET" if os.getenv(provider.api_key_env) else "MISSING"
        lines.append(f"  {provider.api_key_env:<20} {state}")
    return lines


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
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(text, encoding="utf-8")
    return process.returncode, text, elapsed


def load_v2_problem(summary_file: Path, name: str) -> dict[str, Any] | None:
    if not summary_file.is_file():
        return None
    summary = read_json(summary_file)
    for item in summary.get("results", []):
        if isinstance(item, dict) and item.get("problem") == name:
            return item
    return None


def load_v3_problem(summary_file: Path, name: str) -> dict[str, Any] | None:
    if not summary_file.is_file():
        return None
    summary = read_json(summary_file)
    for item in summary.get("problems", []):
        if isinstance(item, dict) and item.get("problem") == name:
            return item
    return None


def load_adjudication_records(summary_file: Path, name: str) -> list[dict[str, Any]]:
    if not summary_file.is_file():
        return []
    summary = read_json(summary_file)
    return [
        item
        for item in summary.get("records", [])
        if isinstance(item, dict) and item.get("problem") == name
    ]


def run_v2(problem_root: Path, name: str, stage_dir: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        str(code_dir() / "verifier_v2.py"),
        str(problem_root),
        "--output",
        str(stage_dir),
        "--names",
        name,
        "--attempts",
        "1",
    ]
    exit_code, _, elapsed = run_process(
        command,
        log_file=stage_dir / "agent_v2.log",
    )
    item = load_v2_problem(stage_dir / "summary.json", name)
    if item is None:
        return {
            "evidence": "TOOL_ERROR",
            "message": "Verifier V2 did not produce a usable summary.",
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
    item = load_v3_problem(stage_dir / "summary.json", name)
    if item is None:
        return {
            "status": "TOOL_ERROR",
            "message": "Verifier V3 did not produce a usable summary.",
            "exit_code": exit_code,
            "elapsed_seconds": round(elapsed, 2),
            "suspicious_cases": [],
            "mixed_cases": [],
        }
    return {
        **item,
        "agent_exit_code": exit_code,
        "agent_elapsed_seconds": round(elapsed, 2),
    }


def run_one_adjudicator(
    problem_root: Path,
    v3_dir: Path,
    name: str,
    stage_dir: Path,
    route,
) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(
        {
            "MODEL_PROVIDER": route.provider,
            "MODEL_NAME": route.model,
            "MODEL_REASONING": route.reasoning,
            "MODEL_MAX_TOKENS": str(route.max_tokens),
        }
    )
    if route.thinking_budget is None:
        env.pop("MODEL_THINKING_BUDGET", None)
    else:
        env["MODEL_THINKING_BUDGET"] = str(route.thinking_budget)

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
    records = load_adjudication_records(stage_dir / "summary.json", name)
    return {
        "provider": route.provider,
        "model": route.model,
        "reasoning": route.reasoning,
        "max_tokens": route.max_tokens,
        "thinking_budget": route.thinking_budget,
        "exit_code": exit_code,
        "elapsed_seconds": round(elapsed, 2),
        "records": records,
    }


def run_adjudicators(
    problem_root: Path,
    v3_dir: Path,
    name: str,
    stage_dir: Path,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for route in adjudication_routes():
        results.append(
            run_one_adjudicator(
                problem_root,
                v3_dir,
                name,
                stage_dir / route.provider,
                route,
            )
        )
    return results


def provider_by_source(v2: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for attempt in v2.get("attempts", []):
        if not isinstance(attempt, dict):
            continue
        source = attempt.get("source")
        if isinstance(source, str):
            result[Path(source).name] = attempt
    return result


def load_v3_report(v3_dir: Path, name: str) -> dict[str, Any] | None:
    path = v3_dir / name / "report.json"
    if not path.is_file():
        return None
    data = read_json(path)
    return data if isinstance(data, dict) else None


def initial_case_votes(
    v3_report: dict[str, Any],
    v2: dict[str, Any],
    contested_cases: list[str],
) -> dict[str, list[dict[str, Any]]]:
    source_meta = provider_by_source(v2)
    wanted = set(contested_cases)
    result = {case: [] for case in contested_cases}

    for case_report in v3_report.get("cases", []):
        if not isinstance(case_report, dict):
            continue
        case = str(case_report.get("case"))
        if case not in wanted:
            continue

        for run in case_report.get("runs", []):
            if not isinstance(run, dict):
                continue
            source_name = str(run.get("source", ""))
            meta = source_meta.get(source_name, {})
            provider = meta.get("provider", "unknown")
            model = meta.get("model")
            run_status = run.get("run_status")
            judge_status = run.get("judge_status")

            if run_status != "OK":
                vote = "UNRESOLVED"
            elif judge_status == "AC":
                vote = "SUPPORTS_EXPECTED"
            else:
                vote = "CONTRADICTS_EXPECTED"

            result[case].append(
                {
                    "tier": "initial",
                    "provider": provider,
                    "model": model,
                    "vote": vote,
                    "source": source_name,
                    "judge_status": judge_status,
                    "run_status": run_status,
                }
            )

    return result


def strong_case_votes(
    adjudications: list[dict[str, Any]],
    contested_cases: list[str],
) -> dict[str, list[dict[str, Any]]]:
    result = {case: [] for case in contested_cases}
    for adjudication in adjudications:
        provider = adjudication["provider"]
        model = adjudication["model"]
        by_case = {
            str(record.get("case")): record
            for record in adjudication.get("records", [])
            if isinstance(record, dict)
        }

        for case in contested_cases:
            record = by_case.get(case)
            if record is None:
                result[case].append(
                    {
                        "tier": "strong",
                        "provider": provider,
                        "model": model,
                        "vote": "UNRESOLVED",
                        "oracle_status": "MISSING",
                    }
                )
                continue

            status = record.get("oracle_status")
            if status in ("SUPPORTS_EXPECTED", "CONTRADICTS_EXPECTED"):
                vote = status
            else:
                vote = "UNRESOLVED"

            result[case].append(
                {
                    "tier": "strong",
                    "provider": provider,
                    "model": model,
                    "vote": vote,
                    "oracle_status": status,
                    "confidence": record.get("oracle_confidence"),
                    "answer": record.get("oracle_answer"),
                    "reason": record.get("oracle_reason"),
                    "usage": record.get("usage"),
                    "error_type": record.get("error_type"),
                    "error_message": record.get("error_message"),
                }
            )
    return result


def final_from_four_votes(
    name: str,
    contested_cases: list[str],
    initial_votes: dict[str, list[dict[str, Any]]],
    strong_votes: dict[str, list[dict[str, Any]]],
    adjudications: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    supported: list[str] = []
    contradicted: list[str] = []
    unresolved: list[str] = []
    case_evidence: list[dict[str, Any]] = []
    has_tool_error = any(item.get("exit_code") != 0 for item in adjudications)

    for case in contested_cases:
        votes = [
            *initial_votes.get(case, []),
            *strong_votes.get(case, []),
        ]
        support_count = sum(item.get("vote") == "SUPPORTS_EXPECTED" for item in votes)
        contradict_count = sum(item.get("vote") == "CONTRADICTS_EXPECTED" for item in votes)
        unresolved_count = sum(item.get("vote") == "UNRESOLVED" for item in votes)

        if len(votes) == 4 and unresolved_count == 0 and support_count >= 3:
            decision = "SUPPORTS_EXPECTED"
            supported.append(case)
        elif len(votes) == 4 and unresolved_count == 0 and contradict_count >= 3:
            decision = "CONTRADICTS_EXPECTED"
            contradicted.append(case)
        else:
            decision = "INCONCLUSIVE"
            unresolved.append(case)

        case_evidence.append(
            {
                "case": case,
                "decision": decision,
                "support_count": support_count,
                "contradict_count": contradict_count,
                "unresolved_count": unresolved_count,
                "votes": votes,
            }
        )

    evidence.append(
        {
            "stage": "DUAL_PROVIDER_ADJUDICATION",
            "rule": "four independent opinions; 3:1 or 4:0 resolves direction; 2:2 stays inconclusive",
            "automatic_test_output_edit": False,
            "cases": case_evidence,
        }
    )

    if has_tool_error:
        state = "TOOL_ERROR"
        message = (
            "At least one strong-provider adjudication failed, so the required four-opinion "
            "evidence set is incomplete."
        )
    elif contradicted:
        state = "REVIEW_REQUIRED"
        message = (
            "At least one contested case has a 3:1 or 4:0 evidence majority against the "
            "existing expected output. The Agent does not auto-edit .out files."
        )
    elif unresolved:
        state = "INCONCLUSIVE"
        message = (
            "At least one contested case remained 2:2 or otherwise lacked a complete "
            "four-opinion majority. Human review is required before changing data."
        )
    else:
        state = "TESTS_SUPPORTED_AFTER_ADJUDICATION"
        message = (
            "Every contested case reached a 3:1 or 4:0 evidence majority supporting the "
            "existing expected output."
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


def verify_one(problem_root: Path, name: str, output_root: Path) -> dict[str, Any]:
    problem_dir = (problem_root / name).resolve()
    problem_output = (output_root / name).resolve()
    evidence: list[dict[str, Any]] = []

    v1_report = verify_problem(problem_dir)
    write_json(problem_output / "V1" / "report.json", v1_report)
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
            "message": "Deterministic mechanical package checks failed.",
            "evidence": evidence,
        }

    v2_dir = problem_output / "V2"
    v2 = run_v2(problem_root, name, v2_dir)
    evidence.append(
        {
            "stage": "V2",
            "result": v2.get("evidence"),
            "attempts_run": v2.get("attempts_run"),
            "providers": [
                {
                    "provider": item.get("provider"),
                    "model": item.get("model"),
                    "status": item.get("status"),
                    "judge": item.get("judge"),
                    "usage": item.get("usage"),
                }
                for item in v2.get("attempts", [])
                if isinstance(item, dict)
            ],
        }
    )

    v2_evidence = v2.get("evidence")
    if v2_evidence == "CORROBORATED":
        return {
            "problem": name,
            "state": "TESTS_CORROBORATED",
            "message": "Both initial providers independently matched every existing test.",
            "evidence": evidence,
        }
    if v2_evidence == "TOOL_ERROR":
        return {
            "problem": name,
            "state": "TOOL_ERROR",
            "message": "The required two-provider initial evidence pair did not complete.",
            "evidence": evidence,
        }
    if v2_evidence == "BLOCKED":
        return {
            "problem": name,
            "state": "BLOCKED",
            "message": "Independent solving was blocked by missing prerequisites.",
            "evidence": evidence,
        }
    if v2_evidence != "INCONCLUSIVE":
        return {
            "problem": name,
            "state": "INCONCLUSIVE",
            "message": "Initial solving did not produce a recognized evidence state.",
            "evidence": evidence,
        }

    v3_dir = problem_output / "V3"
    v3 = run_v3(problem_root, v2_dir, name, v3_dir)
    suspicious = [str(case) for case in v3.get("suspicious_cases", [])]
    mixed = [str(case) for case in v3.get("mixed_cases", [])]
    contested_cases = list(dict.fromkeys([*suspicious, *mixed]))

    evidence.append(
        {
            "stage": "V3",
            "result": v3.get("status"),
            "shared_contradiction_cases": suspicious,
            "mixed_provider_cases": mixed,
            "escalation_cases": contested_cases,
        }
    )

    if v3.get("status") == "TOOL_ERROR":
        return {
            "problem": name,
            "state": "TOOL_ERROR",
            "message": "Local disagreement analysis failed.",
            "evidence": evidence,
        }
    if not contested_cases:
        return {
            "problem": name,
            "state": "INCONCLUSIVE",
            "message": (
                "At least one whole-problem solver was non-AC, but deterministic replay found "
                "no case-level contradiction or provider disagreement that justifies escalation."
            ),
            "evidence": evidence,
        }

    v3_report = load_v3_report(v3_dir, name)
    if v3_report is None:
        return {
            "problem": name,
            "state": "TOOL_ERROR",
            "message": "Detailed V3 report is missing.",
            "evidence": evidence,
        }

    initial_votes = initial_case_votes(v3_report, v2, contested_cases)
    adjudication_dir = problem_output / "Adjudication"
    adjudications = run_adjudicators(
        problem_root,
        v3_dir,
        name,
        adjudication_dir,
    )
    strong_votes = strong_case_votes(adjudications, contested_cases)

    return final_from_four_votes(
        name,
        contested_cases,
        initial_votes,
        strong_votes,
        adjudications,
        evidence,
    )


def print_result(result: dict[str, Any]) -> None:
    print()
    print(f"Problem: {result['problem']}")
    print(f"State  : {result['state']}")
    print(f"Message: {result['message']}")
    if result.get("supported_cases"):
        print("Supported cases: " + ", ".join(result["supported_cases"]))
    if result.get("contradicted_cases"):
        print("Contradicted cases: " + ", ".join(result["contradicted_cases"]))
    if result.get("unresolved_cases"):
        print("Unresolved cases: " + ", ".join(result["unresolved_cases"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Unified ACM/OI Verifier Agent. Deterministic V1 -> two-provider Flash "
            "whole-problem solves -> local disagreement replay -> dual strong-model "
            "case adjudication only for substantive disagreement."
        )
    )
    parser.add_argument("problem_root", nargs="?", type=Path)
    parser.add_argument("--names", nargs="+")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--attempts",
        type=int,
        default=1,
        help="Deprecated compatibility option; one vote per provider is always used.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check dependencies, routing and API-key presence; no model API calls.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ok, messages = dependency_check()

    if args.check:
        print()
        print("=== VERIFIER AGENT CHECK ===")
        for message in messages:
            print(message)
        print()
        print("API keys:")
        for line in key_status():
            print(line)
        print()
        print("Model policy:")
        for route in initial_routes():
            print(
                f"  Initial      : {route.provider:<8} {route.model} / {route.reasoning} "
                f"/ max_tokens={route.max_tokens}"
            )
        for route in adjudication_routes():
            extra = (
                f" / thinking_budget={route.thinking_budget}"
                if route.thinking_budget is not None
                else ""
            )
            print(
                f"  Adjudication : {route.provider:<8} {route.model} / {route.reasoning} "
                f"/ max_tokens={route.max_tokens}{extra}"
            )
        print("  Same-provider resampling: disabled")
        print("  Escalation: case-level substantive disagreement only")
        print("  Four-vote rule: 3:1 or 4:0 resolves direction; 2:2 stays inconclusive")
        print("  Automatic .out edit: disabled")
        print("No model API request was made.")
        return 0 if ok else 1

    if not ok:
        for message in messages:
            print(message)
        return 1
    if args.problem_root is None:
        print("ERROR: problem_root is required unless --check is used.")
        return 1
    if not args.names:
        print("ERROR: --names requires at least one problem.")
        return 1
    if args.output is None:
        print("ERROR: --output is required.")
        return 1
    if args.attempts != 1:
        print(
            f"NOTE: --attempts={args.attempts} is ignored by the dual-provider V1 policy; "
            "one initial vote per provider will be used."
        )

    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    print()
    print("=== UNIFIED TWO-PROVIDER VERIFIER AGENT ===")
    print(f"Problem root : {args.problem_root.resolve()}")
    print(f"Output       : {output_root}")
    print(f"Problems     : {', '.join(args.names)}")
    print("Initial      : DeepSeek Flash + Qwen Flash, one independent solve each")
    print("Escalation   : DeepSeek Pro + Qwen Plus only on case-level disagreement")
    print("Decision     : 3:1/4:0 evidence majority; 2:2 remains inconclusive")

    results: list[dict[str, Any]] = []
    for index, name in enumerate(args.names, start=1):
        print()
        print(f"=== [{index}/{len(args.names)}] {name} ===")
        result = verify_one(
            args.problem_root.resolve(),
            name,
            output_root,
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
        state: sum(item["state"] == state for item in results)
        for state in sorted(FINAL_STATES)
    }
    summary = {
        "routing": routing_snapshot(),
        "counts": counts,
        "results": results,
    }
    write_json(output_root / "summary.json", summary)

    print()
    print("=== FINAL SUMMARY ===")
    for state in sorted(FINAL_STATES):
        if counts[state]:
            print(f"{state}: {counts[state]}")
    print()
    print(f"Report: {output_root / 'summary.json'}")

    if counts["PACKAGE_FAIL"] or counts["TOOL_ERROR"] or counts["BLOCKED"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
