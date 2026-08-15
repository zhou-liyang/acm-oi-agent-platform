from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

try:
    from model_client import ModelClient
except ModuleNotFoundError:
    from Code.model_client import ModelClient

try:
    from Tools.compare_output import compare_output
except ModuleNotFoundError:
    from Code.Tools.compare_output import compare_output


ORACLE_MODEL = os.getenv(
    "DEEPSEEK_CASE_ORACLE_MODEL",
    "deepseek-v4-flash",
)

ORACLE_REASONING = os.getenv(
    "DEEPSEEK_CASE_ORACLE_REASONING",
    "low",
)

ORACLE_MAX_TOKENS = int(
    os.getenv(
        "DEEPSEEK_CASE_ORACLE_MAX_TOKENS",
        "768",
    )
)

SYSTEM_PROMPT = """
You are a case oracle for ACM/OI problem verification.

You will receive:
1. the complete problem statement;
2. exactly one concrete input.

Determine the exact stdout required by the statement for that input.

Hard rules:
- Use only the statement and the supplied input.
- You are NOT given any official answer.
- Do not infer an answer from test names, test purposes, candidate programs,
  majority votes, previous attempts, or hidden judge feedback.
- Do not write a full solution program.
- Carefully resolve boundary conditions and operation order.
- Return one JSON object only.

JSON schema:
{
  "answer": "exact stdout, without Markdown fences",
  "confidence": "high|medium|low",
  "reason": "concise derivation in at most 3 sentences"
}

The answer field must contain exactly what a correct program should print.
""".strip()


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_text(path: Path) -> str:
    return path.read_text(
        encoding="utf-8-sig",
        errors="strict",
    )


def strip_fence(text: str) -> str:
    text = text.strip()

    if text.startswith("```"):
        first_newline = text.find("\n")

        if first_newline != -1:
            text = text[first_newline + 1 :]

        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]

    return text.strip()


def parse_oracle_json(text: str) -> dict[str, str]:
    cleaned = strip_fence(text)

    data = json.loads(cleaned)

    if not isinstance(data, dict):
        raise ValueError(
            "Oracle response is not one JSON object."
        )

    answer = data.get("answer")
    confidence = data.get("confidence")
    reason = data.get("reason")

    if not isinstance(answer, str):
        raise ValueError(
            "Oracle JSON requires string field 'answer'."
        )

    if confidence not in (
        "high",
        "medium",
        "low",
    ):
        raise ValueError(
            "Oracle JSON confidence must be high/medium/low."
        )

    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(
            "Oracle JSON requires non-empty string field 'reason'."
        )

    return {
        "answer": answer,
        "confidence": confidence,
        "reason": reason.strip(),
    }


def statement_path(problem_dir: Path) -> Path:
    for name in (
        "statement.md",
        "problem.md",
    ):
        path = problem_dir / name

        if path.is_file():
            return path

    raise ValueError(
        f"No statement.md/problem.md in {problem_dir}"
    )


def load_suspicious_cases(
    v3_problem_dir: Path,
) -> list[str]:
    report_file = v3_problem_dir / "report.json"

    if not report_file.is_file():
        raise ValueError(
            f"Missing V3 report: {report_file}"
        )

    data = json.loads(
        read_text(report_file)
    )

    summary = data.get("summary")

    if not isinstance(summary, dict):
        raise ValueError(
            f"Invalid V3 report summary: {report_file}"
        )

    cases = summary.get("suspicious_cases")

    if not isinstance(cases, list):
        raise ValueError(
            f"V3 report has no suspicious_cases list: {report_file}"
        )

    result = []

    for case in cases:
        if isinstance(case, (str, int)):
            result.append(str(case))

    return result


def usage_dict(result) -> dict[str, int]:
    usage = result.usage

    return {
        "input_tokens": usage.input_tokens,
        "cached_tokens": usage.cached_tokens,
        "cache_miss_tokens": getattr(
            usage,
            "cache_miss_tokens",
            max(
                0,
                usage.input_tokens
                - usage.cached_tokens,
            ),
        ),
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
    }


def run_case(
    problem_dir: Path,
    case: str,
    output_dir: Path,
) -> dict[str, Any]:
    statement_file = statement_path(
        problem_dir
    )

    input_file = (
        problem_dir
        / "Tests"
        / f"{case}.in"
    )

    expected_file = (
        problem_dir
        / "Tests"
        / f"{case}.out"
    )

    if not input_file.is_file():
        raise ValueError(
            f"Missing input file: {input_file}"
        )

    if not expected_file.is_file():
        raise ValueError(
            f"Missing expected output file: {expected_file}"
        )

    statement = read_text(
        statement_file
    )
    input_text = read_text(
        input_file
    )
    expected = read_text(
        expected_file
    )

    user_prompt = (
        "=== PROBLEM STATEMENT ===\n"
        + statement
        + "\n\n=== SINGLE INPUT ===\n"
        + input_text
    )

    client = ModelClient(
        model=ORACLE_MODEL,
    )

    started = time.perf_counter()

    result = client.generate(
        instructions=SYSTEM_PROMPT,
        input_text=user_prompt,
        reasoning_effort=ORACLE_REASONING,
        max_output_tokens=ORACLE_MAX_TOKENS,
        json_output=True,
    )

    elapsed = time.perf_counter() - started

    record: dict[str, Any] = {
        "problem": problem_dir.name,
        "case": case,
        "model": ORACLE_MODEL,
        "reasoning": ORACLE_REASONING,
        "max_tokens": ORACLE_MAX_TOKENS,
        "elapsed_seconds": round(
            elapsed,
            2,
        ),
        "usage": usage_dict(result),
        "oracle_status": "",
        "oracle_answer": None,
        "oracle_confidence": None,
        "oracle_reason": None,
        "comparison": None,
        "error_type": "",
        "error_message": "",
    }

    raw_file = (
        output_dir
        / problem_dir.name
        / f"case_{case}_raw.txt"
    )

    raw_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw_file.write_text(
        result.text or "",
        encoding="utf-8",
    )

    if not result.ok:
        record["oracle_status"] = "TOOL_ERROR"
        record["error_type"] = result.error_type
        record["error_message"] = result.error_message
        return record

    try:
        parsed = parse_oracle_json(
            result.text
        )

    except (
        ValueError,
        json.JSONDecodeError,
    ) as error:
        record["oracle_status"] = "PARSE_ERROR"
        record["error_type"] = "PARSE"
        record["error_message"] = str(error)
        return record

    answer = parsed["answer"]

    judge_status, judge_message = compare_output(
        answer,
        expected,
    )

    record.update(
        {
            "oracle_answer": answer,
            "oracle_confidence": parsed["confidence"],
            "oracle_reason": parsed["reason"],
            "comparison": {
                "status": judge_status,
                "message": judge_message,
            },
        }
    )

    if judge_status == "AC":
        record["oracle_status"] = "SUPPORTS_EXPECTED"
    else:
        record["oracle_status"] = "CONTRADICTS_EXPECTED"

    return record


def print_case(record: dict[str, Any]) -> None:
    usage = record["usage"]

    print(
        f"{record['problem']:<12} "
        f"case={record['case']:<3} "
        f"{record['oracle_status']:<22} "
        f"confidence={str(record['oracle_confidence']):<6} "
        f"tokens={usage['input_tokens']}+"
        f"{usage['output_tokens']} "
        f"reasoning={usage['reasoning_tokens']} "
        f"time={record['elapsed_seconds']:.2f}s"
    )

    if record["oracle_answer"] is not None:
        print(
            f"  answer: {record['oracle_answer']!r}"
        )

    if record["oracle_reason"]:
        print(
            f"  reason: {record['oracle_reason']}"
        )

    if record["error_message"]:
        print(
            f"  error : {record['error_message']}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verifier V3.1 case oracle: "
            "statement + one input only, "
            "then compare with hidden expected output."
        )
    )

    parser.add_argument(
        "problem_root",
        type=Path,
    )

    parser.add_argument(
        "v3_root",
        type=Path,
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--names",
        nargs="+",
        required=True,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    problem_root = args.problem_root.resolve()
    v3_root = args.v3_root.resolve()
    output_dir = args.output.resolve()

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print("=== VERIFIER V3.1: CASE ORACLE ===")
    print(f"Model      : {ORACLE_MODEL}")
    print(f"Reasoning  : {ORACLE_REASONING}")
    print(f"Max tokens : {ORACLE_MAX_TOKENS}")
    print(
        "Model sees : statement + single input only"
    )
    print(
        "Hidden     : .out, test purpose, candidate code, votes"
    )
    print()

    records: list[dict[str, Any]] = []

    for name in args.names:
        problem_dir = (
            problem_root / name
        )
        v3_problem_dir = (
            v3_root / name
        )

        try:
            cases = load_suspicious_cases(
                v3_problem_dir
            )

        except ValueError as error:
            print(
                f"{name}: BLOCKED: {error}"
            )
            return 1

        for case in cases:
            try:
                record = run_case(
                    problem_dir,
                    case,
                    output_dir,
                )

            except ValueError as error:
                print(
                    f"{name} case {case}: "
                    f"BLOCKED: {error}"
                )
                return 1

            records.append(record)
            print_case(record)

            write_json(
                output_dir
                / name
                / f"case_{case}.json",
                record,
            )

    counts = {
        status: sum(
            item["oracle_status"] == status
            for item in records
        )
        for status in (
            "SUPPORTS_EXPECTED",
            "CONTRADICTS_EXPECTED",
            "TOOL_ERROR",
            "PARSE_ERROR",
        )
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
            for item in records
        )
        for key in usage_keys
    }

    summary = {
        "model": ORACLE_MODEL,
        "reasoning": ORACLE_REASONING,
        "max_tokens": ORACLE_MAX_TOKENS,
        "case_count": len(records),
        "counts": counts,
        "usage_totals": totals,
        "records": records,
    }

    write_json(
        output_dir / "summary.json",
        summary,
    )

    print()
    print("=== V3.1 SUMMARY ===")
    print(
        "Oracle: "
        f"SUPPORTS_EXPECTED={counts['SUPPORTS_EXPECTED']} "
        f"CONTRADICTS_EXPECTED={counts['CONTRADICTS_EXPECTED']} "
        f"TOOL_ERROR={counts['TOOL_ERROR']} "
        f"PARSE_ERROR={counts['PARSE_ERROR']}"
    )
    print(
        "Tokens: "
        f"{totals['input_tokens']} in + "
        f"{totals['output_tokens']} out "
        f"({totals['reasoning_tokens']} reasoning)"
    )
    print(
        f"Summary: {output_dir / 'summary.json'}"
    )

    if counts["TOOL_ERROR"] or counts["PARSE_ERROR"]:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
