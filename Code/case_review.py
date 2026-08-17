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


ORACLE_PROVIDER = os.getenv(
    "MODEL_PROVIDER",
    os.getenv("CASE_ORACLE_PROVIDER", "deepseek"),
)

ORACLE_MODEL = os.getenv(
    "MODEL_NAME",
    os.getenv(
        "DEEPSEEK_CASE_ORACLE_MODEL",
        "deepseek-v4-flash",
    ),
)

ORACLE_REASONING = os.getenv(
    "MODEL_REASONING",
    os.getenv(
        "DEEPSEEK_CASE_ORACLE_REASONING",
        "low",
    ),
)

ORACLE_MAX_TOKENS = int(
    os.getenv(
        "MODEL_MAX_TOKENS",
        os.getenv(
            "DEEPSEEK_CASE_ORACLE_MAX_TOKENS",
            "768",
        ),
    )
)

ORACLE_THINKING_BUDGET = (
    int(os.getenv("MODEL_THINKING_BUDGET"))
    if os.getenv("MODEL_THINKING_BUDGET")
    else None
)

SYSTEM_PROMPT = """
You are an exact-output case oracle for ACM/OI problem verification.

You will receive:
1. the complete problem statement;
2. exactly one concrete input.

Independently determine the exact stdout required by the statement for that input.

Hard rules:
- Use only the statement and supplied input.
- You are NOT given the official answer.
- Ignore test names, purposes, candidate programs, votes, and hidden judge feedback.
- Think internally before answering.
- Return ONLY the exact stdout a correct program should print.
- Do not return JSON, Markdown fences, explanations, labels, or quotations.
- Preserve multiple output lines when required.
- The output may be long: produce it completely and do not abbreviate it.
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
    compare_problem_dir: Path,
) -> list[str]:
    report_file = compare_problem_dir / "report.json"

    if not report_file.is_file():
        raise ValueError(
            f"Missing Case Compare report: {report_file}"
        )

    data = json.loads(
        read_text(report_file)
    )

    summary = data.get("summary")

    if not isinstance(summary, dict):
        raise ValueError(
            f"Invalid Case Compare report summary: {report_file}"
        )

    suspicious = summary.get("suspicious_cases", [])
    mixed = summary.get("mixed_cases", [])

    if not isinstance(suspicious, list) or not isinstance(mixed, list):
        raise ValueError(
            f"Case Compare report has invalid disagreement case lists: {report_file}"
        )

    result: list[str] = []
    seen: set[str] = set()

    for case in [*suspicious, *mixed]:
        if isinstance(case, (str, int)):
            value = str(case)
            if value not in seen:
                seen.add(value)
                result.append(value)

    return result


def normalize_oracle_stdout(text: str) -> str:
    """
    Return only the final stdout from a provider response.

    Some OpenAI-compatible thinking endpoints may leak a serialized
    thinking block into message.content even though reasoning_content is
    supposed to be separate. Keep the raw response on disk for audit,
    but if an explicit </think> delimiter is present, compare only the
    content after the final delimiter.

    This deliberately avoids broad natural-language heuristics: without
    an explicit delimiter, the response is left unchanged.
    """
    value = (text or "").strip()

    if "</think>" in value:
        value = value.rsplit("</think>", 1)[1].strip()

    return value


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
        provider=ORACLE_PROVIDER,
    )

    started = time.perf_counter()

    result = client.generate(
        instructions=SYSTEM_PROMPT,
        input_text=user_prompt,
        reasoning_effort=ORACLE_REASONING,
        max_output_tokens=ORACLE_MAX_TOKENS,
        json_output=False,
        thinking_budget=ORACLE_THINKING_BUDGET,
    )

    elapsed = time.perf_counter() - started

    record: dict[str, Any] = {
        "problem": problem_dir.name,
        "case": case,
        "provider": ORACLE_PROVIDER,
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

    answer = normalize_oracle_stdout(result.text or "")

    if not answer:
        record["oracle_status"] = "TOOL_ERROR"
        record["error_type"] = "EMPTY"
        record["error_message"] = "Case oracle returned empty stdout."
        return record

    judge_status, judge_message = compare_output(
        answer,
        expected,
    )

    record.update(
        {
            "oracle_answer": answer,
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
            "Case Review: "
            "statement + one input only, "
            "then compare with hidden expected output."
        )
    )

    parser.add_argument(
        "problem_root",
        type=Path,
    )

    parser.add_argument(
        "compare_root",
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
    compare_root = args.compare_root.resolve()
    output_dir = args.output.resolve()

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print()
    print("=== CASE REVIEW ===")
    print(f"Provider   : {ORACLE_PROVIDER}")
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
        compare_problem_dir = (
            compare_root / name
        )

        try:
            cases = load_suspicious_cases(
                compare_problem_dir
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
        "provider": ORACLE_PROVIDER,
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
    print("=== CASE REVIEW SUMMARY ===")
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
