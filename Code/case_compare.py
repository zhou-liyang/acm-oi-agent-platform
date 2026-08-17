from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from Tools.compile_cpp import compile_cpp
    from Tools.run_program import run_program
    from Tools.compare_output import compare_output
except ModuleNotFoundError:
    from Code.Tools.compile_cpp import compile_cpp
    from Code.Tools.run_program import run_program
    from Code.Tools.compare_output import compare_output


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8-sig")
    )


def load_time_limit(problem_dir: Path) -> float:
    try:
        data = load_json(problem_dir / "problem.json")
    except Exception:
        return 2.0

    value = data.get("time_limit", 2.0)

    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > 0
    ):
        return float(value)

    return 2.0


def load_test_plan(problem_dir: Path) -> dict[str, str]:
    path = problem_dir / "test_plan.json"

    if not path.is_file():
        return {}

    try:
        data = load_json(path)
    except Exception:
        return {}

    result: dict[str, str] = {}

    if not isinstance(data, list):
        return result

    for item in data:
        if not isinstance(item, dict):
            continue

        case = item.get("case")
        purpose = item.get("purpose")

        if isinstance(case, (str, int)) and isinstance(purpose, str):
            result[str(case)] = purpose

    return result


def normalized(text: str) -> str:
    return " ".join(text.split())


def digest(text: str) -> str:
    return hashlib.sha256(
        normalized(text).encode("utf-8")
    ).hexdigest()[:12]


def preview(text: str, limit: int = 120) -> str:
    value = normalized(text)

    if len(value) <= limit:
        return value

    return value[: limit - 3] + "..."


def discover_sources(solve_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in solve_dir.glob("independent_*.cpp")
            if path.is_file()
        ],
        key=lambda path: path.name,
    )


def compile_sources(
    sources: list[Path],
    build_dir: Path,
) -> tuple[dict[str, Path], list[dict[str, str]]]:
    programs: dict[str, Path] = {}
    errors: list[dict[str, str]] = []

    build_dir.mkdir(parents=True, exist_ok=True)

    for source in sources:
        program = build_dir / f"{source.stem}.exe"

        compiled, message = compile_cpp(
            source,
            program,
        )

        if compiled:
            programs[source.name] = program
        else:
            errors.append(
                {
                    "source": source.name,
                    "message": message,
                }
            )

    return programs, errors


def classify_case(
    expected: str,
    runs: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    ok_runs = [
        item
        for item in runs
        if item["run_status"] == "OK"
    ]

    if not ok_runs:
        return (
            "NO_USABLE_OUTPUT",
            {
                "agreement": 0,
                "expected_support": 0,
                "dissent_support": 0,
            },
        )

    outputs = [
        item["normalized_output"]
        for item in ok_runs
    ]
    counts = Counter(outputs)

    majority_output, majority_count = counts.most_common(1)[0]
    expected_norm = normalized(expected)
    expected_support = counts.get(expected_norm, 0)

    if len(counts) == 1:
        if majority_output == expected_norm:
            label = "UNANIMOUS_WITH_EXPECTED"
        elif len(ok_runs) >= 2:
            label = "UNANIMOUS_AGAINST_EXPECTED"
        else:
            label = "SINGLE_OUTPUT_AGAINST_EXPECTED"
    elif majority_count >= 2 and majority_output != expected_norm:
        label = "MAJORITY_AGAINST_EXPECTED"
    elif expected_support >= 2:
        label = "MAJORITY_WITH_EXPECTED"
    else:
        label = "MIXED_DISAGREEMENT"

    details = {
        "usable_outputs": len(ok_runs),
        "distinct_outputs": len(counts),
        "majority_count": majority_count,
        "expected_support": expected_support,
        "majority_matches_expected": (
            majority_output == expected_norm
        ),
        "majority_digest": digest(majority_output),
        "majority_preview": preview(majority_output),
    }

    return label, details


def analyze_problem(
    problem_dir: Path,
    solve_problem_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    problem_dir = problem_dir.resolve()
    solve_problem_dir = solve_problem_dir.resolve()
    output_dir = output_dir.resolve()

    sources = discover_sources(solve_problem_dir)
    time_limit = load_time_limit(problem_dir)
    test_plan = load_test_plan(problem_dir)

    report: dict[str, Any] = {
        "problem": problem_dir.name,
        "problem_dir": str(problem_dir),
        "solve_problem_dir": str(solve_problem_dir),
        "source_count": len(sources),
        "sources": [path.name for path in sources],
        "compile_errors": [],
        "cases": [],
        "summary": {},
    }

    if not sources:
        report["summary"] = {
            "status": "BLOCKED",
            "message": "No independent_*.cpp sources found.",
        }
        return report

    build_dir = output_dir / problem_dir.name / "Programs"

    programs, compile_errors = compile_sources(
        sources,
        build_dir,
    )

    report["compile_errors"] = compile_errors

    tests_dir = problem_dir / "Tests"
    input_files = sorted(
        tests_dir.glob("*.in"),
        key=lambda path: path.stem,
    )

    suspicious_cases: list[str] = []
    mixed_cases: list[str] = []
    supported_cases: list[str] = []

    for input_file in input_files:
        case = input_file.stem
        expected_file = input_file.with_suffix(".out")

        if not expected_file.is_file():
            continue

        input_text = input_file.read_text(
            encoding="utf-8",
            errors="replace",
        )
        expected = expected_file.read_text(
            encoding="utf-8",
            errors="replace",
        )

        runs: list[dict[str, Any]] = []

        for source_name, program in programs.items():
            run_status, stdout, stderr, return_code = run_program(
                program,
                input_text,
                time_limit,
            )

            judge_status = None
            judge_message = None

            if run_status == "OK":
                judge_status, judge_message = compare_output(
                    stdout,
                    expected,
                )

            runs.append(
                {
                    "source": source_name,
                    "run_status": run_status,
                    "return_code": return_code,
                    "judge_status": judge_status,
                    "judge_message": judge_message,
                    "output_digest": digest(stdout),
                    "output_preview": preview(stdout),
                    "normalized_output": normalized(stdout),
                    "stderr_preview": preview(stderr),
                }
            )

        label, details = classify_case(
            expected,
            runs,
        )

        if label in (
            "UNANIMOUS_AGAINST_EXPECTED",
            "MAJORITY_AGAINST_EXPECTED",
        ):
            suspicious_cases.append(case)
        elif label == "MIXED_DISAGREEMENT":
            mixed_cases.append(case)
        elif label in (
            "UNANIMOUS_WITH_EXPECTED",
            "MAJORITY_WITH_EXPECTED",
        ):
            supported_cases.append(case)

        case_report = {
            "case": case,
            "purpose": test_plan.get(case),
            "classification": label,
            "expected_digest": digest(expected),
            "expected_preview": preview(expected),
            "details": details,
            "runs": [
                {
                    key: value
                    for key, value in item.items()
                    if key != "normalized_output"
                }
                for item in runs
            ],
        }

        report["cases"].append(case_report)

    if suspicious_cases:
        status = "SUSPICIOUS"
        message = (
            "At least two independent candidate programs agree "
            "with each other against the existing expected output "
            "on one or more cases. These cases deserve case review "
            "investigation; this is not yet proof that .out is wrong."
        )
    elif mixed_cases:
        status = "MODEL_DISAGREEMENT"
        message = (
            "Candidate programs disagree with each other on some cases. "
            "The evidence currently points more toward solver uncertainty "
            "than toward a common contradiction of the expected output."
        )
    else:
        status = "NO_SHARED_CONTRADICTION"
        message = (
            "No shared contradiction of existing expected outputs "
            "was found among the available independent candidates."
        )

    report["summary"] = {
        "status": status,
        "message": message,
        "suspicious_cases": suspicious_cases,
        "mixed_cases": mixed_cases,
        "supported_cases": supported_cases,
        "case_count": len(report["cases"]),
    }

    write_json(
        output_dir / problem_dir.name / "report.json",
        report,
    )

    return report


def print_problem(report: dict[str, Any]) -> None:
    summary = report["summary"]

    print(
        f"{report['problem']:<16} "
        f"{summary['status']}"
    )

    if "suspicious_cases" in summary:
        print(
            "  suspicious: "
            + (
                ", ".join(summary["suspicious_cases"])
                if summary["suspicious_cases"]
                else "-"
            )
        )
        print(
            "  mixed     : "
            + (
                ", ".join(summary["mixed_cases"])
                if summary["mixed_cases"]
                else "-"
            )
        )

    for case in report.get("cases", []):
        if case["classification"] in (
            "UNANIMOUS_AGAINST_EXPECTED",
            "MAJORITY_AGAINST_EXPECTED",
            "MIXED_DISAGREEMENT",
        ):
            print(
                f"    case {case['case']}: "
                f"{case['classification']} "
                f"expected={case['expected_preview']!r} "
                f"majority={case['details'].get('majority_preview', '')!r}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Case Compare: local disagreement matrix. "
            "Reuses already generated independent candidate sources "
            "and makes no model API requests."
        )
    )

    parser.add_argument(
        "problem_root",
        type=Path,
    )

    parser.add_argument(
        "solve_root",
        type=Path,
    )

    parser.add_argument(
        "--output",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--names",
        nargs="+",
        required=True,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    reports: list[dict[str, Any]] = []

    for name in args.names:
        problem_dir = args.problem_root / name
        solve_problem_dir = args.solve_root / name

        report = analyze_problem(
            problem_dir,
            solve_problem_dir,
            args.output,
        )
        reports.append(report)
        print_problem(report)

    summary = {
        "problem_count": len(reports),
        "problems": [
            {
                "problem": report["problem"],
                **report["summary"],
            }
            for report in reports
        ],
    }

    write_json(
        args.output / "summary.json",
        summary,
    )

    print()
    print(
        f"Summary: {args.output / 'summary.json'}"
    )
    print(
        "No model API request was made."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
