from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from problem_package import (
        data_directory,
        discover_test_cases,
        private_assets,
        statement_path,
    )
except ModuleNotFoundError:
    from Code.problem_package import (
        data_directory,
        discover_test_cases,
        private_assets,
        statement_path,
    )


VALID_STATUS = {"PASS", "WARN", "FAIL", "N/A"}


@dataclass
class Check:
    key: str
    status: str
    message: str
    details: Any = None

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUS:
            raise ValueError(f"Invalid status: {self.status}")


def read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def add(
    checks: list[Check],
    key: str,
    status: str,
    message: str,
    details: Any = None,
) -> None:
    checks.append(Check(key, status, message, details))


def check_statement(
    problem_dir: Path,
    checks: list[Check],
) -> Path | None:
    preferred = problem_dir / "problem.md"
    legacy = problem_dir / "statement.md"

    statement = statement_path(
        problem_dir,
        allow_legacy=True,
    )

    if statement is None:
        add(
            checks,
            "statement",
            "FAIL",
            "Missing problem.md.",
        )
        return None

    try:
        text = read_utf8(statement)
    except (OSError, UnicodeError) as error:
        add(
            checks,
            "statement",
            "FAIL",
            f"Cannot read {statement.name} as UTF-8: {error}",
        )
        return statement

    if not text.strip():
        add(
            checks,
            "statement",
            "FAIL",
            f"{statement.name} is empty.",
        )
        return statement

    if preferred.is_file():
        add(
            checks,
            "statement",
            "PASS",
            "problem.md exists and is non-empty.",
        )
        if legacy.is_file():
            add(
                checks,
                "legacy_statement",
                "WARN",
                "statement.md also exists; problem.md is authoritative.",
            )
    else:
        add(
            checks,
            "statement",
            "WARN",
            "Legacy statement.md is accepted temporarily; "
            "rename it to problem.md for the current package contract.",
        )

    image_refs: list[str] = []

    md_pattern = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
    html_pattern = re.compile(
        r"<img\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"'][^>]*>",
        flags=re.IGNORECASE,
    )

    image_refs.extend(md_pattern.findall(text))
    image_refs.extend(html_pattern.findall(text))

    if image_refs:
        add(
            checks,
            "statement_images",
            "WARN",
            f"Statement contains {len(image_refs)} image reference(s).",
            image_refs[:20],
        )
    else:
        add(
            checks,
            "statement_images",
            "PASS",
            "No Markdown/HTML image references detected.",
        )

    return statement


def check_tests(
    problem_dir: Path,
    checks: list[Check],
) -> list[str]:
    preferred = problem_dir / "data"
    legacy = problem_dir / "Tests"

    directory = data_directory(
        problem_dir,
        allow_legacy=True,
    )

    if directory is None:
        add(
            checks,
            "tests",
            "FAIL",
            "Missing data directory.",
        )
        return []

    if preferred.is_dir():
        add(
            checks,
            "data_directory",
            "PASS",
            "data/ directory exists.",
        )
        if legacy.is_dir():
            add(
                checks,
                "legacy_tests_directory",
                "WARN",
                "Tests/ also exists; data/ is authoritative.",
            )
    else:
        add(
            checks,
            "data_directory",
            "WARN",
            "Legacy Tests/ is accepted temporarily; "
            "rename it to data/ for the current package contract.",
        )

    inventory = discover_test_cases(
        problem_dir,
        allow_legacy=True,
    )

    if (
        not inventory.cases
        and not inventory.input_without_output
        and not inventory.output_without_input
        and not inventory.ambiguous_inputs
        and not inventory.ambiguous_outputs
    ):
        add(
            checks,
            "tests",
            "FAIL",
            "Data directory contains no .in with .out/.ans test files.",
        )
        return []

    issues = {
        "input_without_output": inventory.input_without_output,
        "output_without_input": inventory.output_without_input,
        "ambiguous_inputs": inventory.ambiguous_inputs,
        "ambiguous_outputs": inventory.ambiguous_outputs,
    }
    issues = {
        key: value
        for key, value in issues.items()
        if value
    }

    if issues:
        add(
            checks,
            "test_pairs",
            "FAIL",
            "Test data are not one-to-one by shared filename stem.",
            issues,
        )
    else:
        suffix_counts: dict[str, int] = {}
        for case in inventory.cases:
            suffix = case.expected_suffix
            suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1

        add(
            checks,
            "test_pairs",
            "PASS",
            f"All {len(inventory.cases)} test case(s) have exactly one "
            ".in and one .out/.ans file with the same stem.",
            {"expected_suffixes": suffix_counts},
        )

    if not inventory.cases:
        add(
            checks,
            "test_content",
            "FAIL",
            "No unambiguous complete test pairs are available.",
        )
        return []

    empty_inputs: list[str] = []
    empty_outputs: list[str] = []

    for case in inventory.cases:
        try:
            if case.input_path.stat().st_size == 0:
                empty_inputs.append(case.name)
        except OSError:
            empty_inputs.append(case.name)

        try:
            if case.expected_path.stat().st_size == 0:
                empty_outputs.append(case.name)
        except OSError:
            empty_outputs.append(case.name)

    if empty_inputs or empty_outputs:
        add(
            checks,
            "test_content",
            "WARN",
            "Some paired test files are empty.",
            {
                "empty_inputs": empty_inputs,
                "empty_outputs": empty_outputs,
            },
        )
    else:
        add(
            checks,
            "test_content",
            "PASS",
            "All paired test files are non-empty.",
        )

    if inventory.ignored_files:
        add(
            checks,
            "data_extra_files",
            "WARN",
            "data/ contains files that are not test inputs or expected outputs.",
            inventory.ignored_files[:50],
        )
    else:
        add(
            checks,
            "data_extra_files",
            "PASS",
            "No unrelated files detected in the data directory.",
        )

    names = [case.name for case in inventory.cases]
    add(
        checks,
        "test_count",
        "PASS",
        f"Found {len(names)} complete test pair(s).",
        {"count": len(names), "cases": names},
    )

    return names


def check_private_assets(
    problem_dir: Path,
    checks: list[Check],
) -> dict[str, object]:
    assets = private_assets(problem_dir)

    solution = assets.get("solution")
    source_dir = assets.get("source_dir")
    source_files = assets.get("source_files", [])

    if solution:
        add(
            checks,
            "private_solution",
            "PASS",
            f"Found private reference solution: {solution}",
        )
    else:
        add(
            checks,
            "private_solution",
            "N/A",
            "solution.md is not provided.",
        )

    if source_dir:
        add(
            checks,
            "private_source",
            "PASS",
            f"Found private source directory with {len(source_files)} file(s).",
            source_files[:50],
        )
    else:
        add(
            checks,
            "private_source",
            "N/A",
            "source/ is not provided.",
        )

    for key in ("std", "maker", "spj", "interactor"):
        value = assets.get(key)
        if value:
            add(
                checks,
                f"asset_{key}",
                "PASS",
                f"Detected source asset '{key}': {value}",
            )
        else:
            add(
                checks,
                f"asset_{key}",
                "N/A",
                f"Source asset '{key}' was not detected.",
            )

    return assets


def summarize(checks: list[Check]) -> dict[str, int]:
    counts = {
        "PASS": 0,
        "WARN": 0,
        "FAIL": 0,
        "N/A": 0,
    }

    for check in checks:
        counts[check.status] += 1

    return counts


def overall_status(checks: list[Check]) -> str:
    if any(check.status == "FAIL" for check in checks):
        return "FAIL"

    if any(check.status == "WARN" for check in checks):
        return "WARN"

    return "PASS"


def verify_problem(problem_dir: Path) -> dict[str, Any]:
    problem_dir = problem_dir.resolve()
    checks: list[Check] = []

    if not problem_dir.is_dir():
        add(
            checks,
            "problem_directory",
            "FAIL",
            f"Problem directory does not exist: {problem_dir}",
        )
        return {
            "problem_dir": str(problem_dir),
            "problem_name": problem_dir.name,
            "overall": "FAIL",
            "counts": summarize(checks),
            "test_cases": [],
            "assets": {},
            "checks": [asdict(item) for item in checks],
        }

    add(
        checks,
        "problem_directory",
        "PASS",
        "Problem directory exists.",
    )

    check_statement(problem_dir, checks)
    cases = check_tests(problem_dir, checks)
    assets = check_private_assets(problem_dir, checks)

    return {
        "problem_dir": str(problem_dir),
        "problem_name": problem_dir.name,
        "overall": overall_status(checks),
        "counts": summarize(checks),
        "test_cases": cases,
        "assets": assets,
        "checks": [asdict(item) for item in checks],
    }


def print_problem_report(report: dict[str, Any]) -> None:
    print(f"Problem: {report['problem_name']}")
    print(f"Overall: {report['overall']}")

    counts = report["counts"]
    print(
        "Checks: "
        f"PASS={counts['PASS']} "
        f"WARN={counts['WARN']} "
        f"FAIL={counts['FAIL']} "
        f"N/A={counts['N/A']}"
    )
    print()

    for item in report["checks"]:
        print(
            f"[{item['status']:<4}] "
            f"{item['key']}: {item['message']}"
        )

        details = item.get("details")
        if details not in (None, [], {}):
            rendered = json.dumps(
                details,
                ensure_ascii=False,
                indent=2,
            )
            for line in rendered.splitlines():
                print(f"       {line}")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def verify_batch(
    root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = output_dir.resolve()

    if not root.is_dir():
        raise ValueError(
            f"Benchmark root does not exist: {root}"
        )

    problem_dirs = sorted(
        [path for path in root.iterdir() if path.is_dir()],
        key=lambda path: path.name.lower(),
    )

    reports: list[dict[str, Any]] = []

    for problem_dir in problem_dirs:
        report = verify_problem(problem_dir)
        reports.append(report)

        write_json(
            output_dir / f"{problem_dir.name}.json",
            report,
        )

    totals = {
        "PASS": 0,
        "WARN": 0,
        "FAIL": 0,
    }

    for report in reports:
        totals[report["overall"]] += 1

    summary = {
        "root": str(root),
        "problem_count": len(reports),
        "overall_counts": totals,
        "problems": [
            {
                "name": report["problem_name"],
                "folder": Path(report["problem_dir"]).name,
                "overall": report["overall"],
                "counts": report["counts"],
                "test_count": len(report["test_cases"]),
            }
            for report in reports
        ],
    }

    write_json(
        output_dir / "summary.json",
        summary,
    )

    return summary


def print_batch_summary(summary: dict[str, Any]) -> None:
    print(f"Root: {summary['root']}")
    print(f"Problems: {summary['problem_count']}")

    totals = summary["overall_counts"]
    print(
        "Overall: "
        f"PASS={totals['PASS']} "
        f"WARN={totals['WARN']} "
        f"FAIL={totals['FAIL']}"
    )
    print()

    for item in summary["problems"]:
        print(
            f"{item['folder']:<16} "
            f"{item['overall']:<4} "
            f"tests={item['test_count']:<3} "
            f"checks="
            f"{item['counts']['PASS']}/"
            f"{item['counts']['WARN']}/"
            f"{item['counts']['FAIL']}/"
            f"{item['counts']['N/A']}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Package Check: deterministic mechanical "
            "consistency checks for ACM/OI problem packages."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    problem_parser = subparsers.add_parser(
        "problem",
        help="Verify one problem directory.",
    )
    problem_parser.add_argument(
        "problem_dir",
        type=Path,
    )
    problem_parser.add_argument(
        "--json",
        type=Path,
        dest="json_path",
    )

    batch_parser = subparsers.add_parser(
        "batch",
        help="Verify every child directory under a benchmark root.",
    )
    batch_parser.add_argument(
        "root",
        type=Path,
    )
    batch_parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.command == "problem":
        report = verify_problem(args.problem_dir)
        print_problem_report(report)

        if args.json_path is not None:
            write_json(args.json_path, report)

        return 1 if report["overall"] == "FAIL" else 0

    if args.command == "batch":
        try:
            summary = verify_batch(
                args.root,
                args.output,
            )
        except ValueError as error:
            print(f"ERROR: {error}")
            return 1

        print_batch_summary(summary)
        return (
            1
            if summary["overall_counts"]["FAIL"] > 0
            else 0
        )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
