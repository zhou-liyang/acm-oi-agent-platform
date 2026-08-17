from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


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


def load_json_file(
    path: Path,
) -> tuple[Any | None, str | None]:
    try:
        return json.loads(read_utf8(path)), None
    except OSError as error:
        return None, f"I/O error: {error}"
    except UnicodeError as error:
        return None, f"UTF-8 decode error: {error}"
    except json.JSONDecodeError as error:
        return (
            None,
            "JSON decode error at "
            f"line {error.lineno}, column {error.colno}: "
            f"{error.msg}",
        )


def check_problem_json(
    problem_dir: Path,
    checks: list[Check],
) -> dict[str, Any] | None:
    path = problem_dir / "problem.json"

    if not path.is_file():
        add(
            checks,
            "problem_json",
            "FAIL",
            "Missing problem.json.",
        )
        return None

    data, error = load_json_file(path)

    if error is not None:
        add(
            checks,
            "problem_json",
            "FAIL",
            f"Invalid problem.json: {error}",
        )
        return None

    if not isinstance(data, dict):
        add(
            checks,
            "problem_json",
            "FAIL",
            "problem.json must contain one JSON object.",
        )
        return None

    errors: list[str] = []
    warnings: list[str] = []

    name = data.get("name")
    time_limit = data.get("time_limit")

    if not isinstance(name, str) or not name.strip():
        errors.append("'name' must be a non-empty string.")

    if (
        not isinstance(time_limit, (int, float))
        or isinstance(time_limit, bool)
        or time_limit <= 0
    ):
        errors.append("'time_limit' must be a positive number.")

    if "difficulty" in data:
        difficulty = data["difficulty"]
        if not isinstance(difficulty, str) or not difficulty.strip():
            warnings.append(
                "'difficulty' is present but is not a non-empty string."
            )

    if "source_name" in data:
        source_name = data["source_name"]
        if not isinstance(source_name, str) or not source_name.strip():
            warnings.append(
                "'source_name' is present but is not a non-empty string."
            )

    if "topics" in data:
        topics = data["topics"]
        if (
            not isinstance(topics, list)
            or any(
                not isinstance(item, str) or not item.strip()
                for item in topics
            )
        ):
            warnings.append(
                "'topics' should be a list of non-empty strings."
            )

    if errors:
        add(
            checks,
            "problem_json",
            "FAIL",
            "problem.json schema check failed.",
            errors,
        )
    elif warnings:
        add(
            checks,
            "problem_json",
            "WARN",
            "Core fields are valid; optional metadata has warnings.",
            warnings,
        )
    else:
        add(
            checks,
            "problem_json",
            "PASS",
            "problem.json parsed and core fields are valid.",
        )

    return data


def check_statement(
    problem_dir: Path,
    checks: list[Check],
) -> Path | None:
    candidates = [
        problem_dir / "statement.md",
        problem_dir / "problem.md",
    ]
    existing = [path for path in candidates if path.is_file()]

    if not existing:
        add(
            checks,
            "statement",
            "FAIL",
            "Missing statement.md/problem.md.",
        )
        return None

    statement = existing[0]

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

    if len(existing) > 1:
        add(
            checks,
            "statement",
            "WARN",
            "Both statement.md and problem.md exist; "
            "Verifier uses statement.md first.",
            [path.name for path in existing],
        )
    else:
        add(
            checks,
            "statement",
            "PASS",
            f"{statement.name} exists and is non-empty.",
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


def case_sort_key(name: str) -> tuple[int, int | str]:
    if name.isdigit():
        return (0, int(name))
    return (1, name)


def check_tests(
    problem_dir: Path,
    checks: list[Check],
) -> list[str]:
    tests_dir = problem_dir / "Tests"

    if not tests_dir.is_dir():
        add(
            checks,
            "tests",
            "FAIL",
            "Missing Tests directory.",
        )
        return []

    input_files = {
        path.stem: path
        for path in tests_dir.glob("*.in")
        if path.is_file()
    }
    output_files = {
        path.stem: path
        for path in tests_dir.glob("*.out")
        if path.is_file()
    }

    if not input_files and not output_files:
        add(
            checks,
            "tests",
            "FAIL",
            "Tests directory contains no .in/.out files.",
        )
        return []

    input_only = sorted(
        set(input_files) - set(output_files),
        key=case_sort_key,
    )
    output_only = sorted(
        set(output_files) - set(input_files),
        key=case_sort_key,
    )
    paired = sorted(
        set(input_files) & set(output_files),
        key=case_sort_key,
    )

    if input_only or output_only:
        add(
            checks,
            "test_pairs",
            "FAIL",
            "Input/output files are not one-to-one.",
            {
                "input_without_output": input_only,
                "output_without_input": output_only,
            },
        )
    else:
        add(
            checks,
            "test_pairs",
            "PASS",
            f"All {len(paired)} test case(s) have matching .in/.out files.",
        )

    if not paired:
        add(
            checks,
            "test_content",
            "FAIL",
            "No complete test pairs are available.",
        )
        return []

    empty_inputs: list[str] = []
    empty_outputs: list[str] = []

    for case in paired:
        try:
            if input_files[case].stat().st_size == 0:
                empty_inputs.append(case)
        except OSError:
            empty_inputs.append(case)

        try:
            if output_files[case].stat().st_size == 0:
                empty_outputs.append(case)
        except OSError:
            empty_outputs.append(case)

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

    numeric_cases = [case for case in paired if case.isdigit()]
    non_numeric = [case for case in paired if not case.isdigit()]

    if non_numeric:
        add(
            checks,
            "test_numbering",
            "WARN",
            "Non-numeric test case names detected; "
            "continuity check is skipped for them.",
            non_numeric,
        )
    elif numeric_cases:
        values = sorted(int(case) for case in numeric_cases)
        expected = list(range(values[0], values[-1] + 1))

        if values != expected:
            missing = sorted(set(expected) - set(values))
            add(
                checks,
                "test_numbering",
                "WARN",
                "Numeric test case numbering has gaps.",
                {"missing_numbers": missing},
            )
        else:
            add(
                checks,
                "test_numbering",
                "PASS",
                "Numeric test case numbering is continuous.",
            )
    else:
        add(
            checks,
            "test_numbering",
            "N/A",
            "No numeric test case names to check.",
        )

    add(
        checks,
        "test_count",
        "PASS",
        f"Found {len(paired)} complete test pair(s).",
        {"count": len(paired), "cases": paired},
    )

    return paired


def check_test_plan(
    problem_dir: Path,
    cases: list[str],
    checks: list[Check],
) -> None:
    path = problem_dir / "test_plan.json"

    if not path.is_file():
        add(
            checks,
            "test_plan",
            "N/A",
            "test_plan.json is not provided.",
        )
        return

    data, error = load_json_file(path)

    if error is not None:
        add(
            checks,
            "test_plan",
            "WARN",
            f"test_plan.json exists but is invalid: {error}",
        )
        return

    if not isinstance(data, list):
        add(
            checks,
            "test_plan",
            "WARN",
            "test_plan.json should contain a list.",
        )
        return

    plan_cases: list[str] = []
    malformed_entries: list[int] = []

    for index, item in enumerate(data):
        if not isinstance(item, dict):
            malformed_entries.append(index)
            continue

        case = item.get("case")
        if isinstance(case, (str, int)):
            plan_cases.append(str(case))
        else:
            malformed_entries.append(index)

    actual = set(cases)
    planned = set(plan_cases)

    missing_in_plan = sorted(
        actual - planned,
        key=case_sort_key,
    )
    extra_in_plan = sorted(
        planned - actual,
        key=case_sort_key,
    )

    issues: dict[str, Any] = {}

    if malformed_entries:
        issues["malformed_entries"] = malformed_entries

    if missing_in_plan:
        issues["tests_without_plan_entry"] = missing_in_plan

    if extra_in_plan:
        issues["plan_entries_without_test"] = extra_in_plan

    duplicates = sorted(
        {
            case
            for case in plan_cases
            if plan_cases.count(case) > 1
        },
        key=case_sort_key,
    )

    if duplicates:
        issues["duplicate_plan_cases"] = duplicates

    if issues:
        add(
            checks,
            "test_plan",
            "WARN",
            "test_plan.json does not perfectly match Tests.",
            issues,
        )
    else:
        add(
            checks,
            "test_plan",
            "PASS",
            f"test_plan.json matches all {len(cases)} test case(s).",
        )


def find_first(
    problem_dir: Path,
    relative_candidates: list[str],
) -> Path | None:
    for relative in relative_candidates:
        path = problem_dir / relative
        if path.is_file():
            return path
    return None


def check_optional_assets(
    problem_dir: Path,
    checks: list[Check],
) -> dict[str, str | None]:
    definitions = {
        "solution": [
            "solution.md",
            "Solution.md",
        ],
        "std": [
            "src/std.cpp",
            "Src/std.cpp",
            "std.cpp",
            "source/std.cpp",
        ],
        "brute": [
            "src/brute.cpp",
            "Src/brute.cpp",
            "brute.cpp",
            "source/brute.cpp",
        ],
        "gen": [
            "src/gen.cpp",
            "Src/gen.cpp",
            "gen.cpp",
            "source/gen.cpp",
        ],
        "checker": [
            "tools/checker.cpp",
            "Tools/checker.cpp",
            "checker.cpp",
            "tools/checker.py",
            "Tools/checker.py",
            "checker.py",
        ],
        "spj": [
            "tools/spj.cpp",
            "Tools/spj.cpp",
            "spj.cpp",
            "tools/spj.py",
            "Tools/spj.py",
            "spj.py",
        ],
    }

    found: dict[str, str | None] = {}

    for key, candidates in definitions.items():
        path = find_first(problem_dir, candidates)
        found[key] = (
            str(path.relative_to(problem_dir))
            if path is not None
            else None
        )

        if path is None:
            add(
                checks,
                f"asset_{key}",
                "N/A",
                f"Optional asset '{key}' is not provided.",
            )
        else:
            add(
                checks,
                f"asset_{key}",
                "PASS",
                f"Found optional asset '{key}': "
                f"{path.relative_to(problem_dir)}",
            )

    return found


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
            "checks": [asdict(item) for item in checks],
        }

    add(
        checks,
        "problem_directory",
        "PASS",
        "Problem directory exists.",
    )

    config = check_problem_json(
        problem_dir,
        checks,
    )

    check_statement(
        problem_dir,
        checks,
    )

    cases = check_tests(
        problem_dir,
        checks,
    )

    check_test_plan(
        problem_dir,
        cases,
        checks,
    )

    assets = check_optional_assets(
        problem_dir,
        checks,
    )

    problem_name = problem_dir.name

    if (
        isinstance(config, dict)
        and isinstance(config.get("name"), str)
        and config["name"].strip()
    ):
        problem_name = config["name"].strip()

    report = {
        "problem_dir": str(problem_dir),
        "problem_name": problem_name,
        "overall": overall_status(checks),
        "counts": summarize(checks),
        "test_cases": cases,
        "assets": assets,
        "checks": [asdict(item) for item in checks],
    }

    return report


def print_problem_report(report: dict[str, Any]) -> None:
    print(
        f"Problem: {report['problem_name']}"
    )
    print(
        f"Overall: {report['overall']}"
    )

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
        status = item["status"]
        key = item["key"]
        message = item["message"]

        print(
            f"[{status:<4}] {key}: {message}"
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


def write_json(
    path: Path,
    data: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
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
        [
            path
            for path in root.iterdir()
            if path.is_dir()
        ],
        key=lambda path: path.name.lower(),
    )

    reports: list[dict[str, Any]] = []

    for problem_dir in problem_dirs:
        report = verify_problem(problem_dir)
        reports.append(report)

        write_json(
            output_dir
            / f"{problem_dir.name}.json",
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
                "folder": Path(
                    report["problem_dir"]
                ).name,
                "overall": report["overall"],
                "counts": report["counts"],
                "test_count": len(
                    report["test_cases"]
                ),
            }
            for report in reports
        ],
    }

    write_json(
        output_dir / "summary.json",
        summary,
    )

    return summary


def print_batch_summary(
    summary: dict[str, Any],
) -> None:
    print(
        f"Root: {summary['root']}"
    )
    print(
        f"Problems: {summary['problem_count']}"
    )

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
        report = verify_problem(
            args.problem_dir,
        )

        print_problem_report(report)

        if args.json_path is not None:
            write_json(
                args.json_path,
                report,
            )

        return 1 if report["overall"] == "FAIL" else 0

    if args.command == "batch":
        try:
            summary = verify_batch(
                args.root,
                args.output,
            )
        except ValueError as error:
            print(
                f"ERROR: {error}"
            )
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
