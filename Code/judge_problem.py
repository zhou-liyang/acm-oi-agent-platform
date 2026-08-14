import json
from pathlib import Path
import sys

from judge_tests import judge_tests


def load_problem(
    problem_dir: Path,
) -> tuple[str, float, Path]:
    problem_dir = problem_dir.resolve()

    if not problem_dir.is_dir():
        raise ValueError(
            f"Problem directory does not exist: {problem_dir}"
        )

    config_file = problem_dir / "problem.json"

    if not config_file.is_file():
        raise ValueError(
            f"Problem config does not exist: {config_file}"
        )

    try:
        config = json.loads(
            config_file.read_text(
                encoding="utf-8-sig",
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Invalid problem config: {error}"
        ) from error

    name = config.get("name")
    time_limit = config.get("time_limit")

    if not isinstance(name, str) or not name.strip():
        raise ValueError(
            "Problem config requires a non-empty 'name'."
        )

    if (
        not isinstance(time_limit, (int, float))
        or isinstance(time_limit, bool)
        or time_limit <= 0
    ):
        raise ValueError(
            "Problem config requires a positive 'time_limit'."
        )

    tests_dir = problem_dir / "Tests"

    if not tests_dir.is_dir():
        raise ValueError(
            f"Tests directory does not exist: {tests_dir}"
        )

    return name.strip(), float(time_limit), tests_dir


def judge_problem(
    problem_dir: Path,
    source: Path,
) -> tuple[str, str, list[tuple[str, str, str]]]:
    try:
        name, time_limit, tests_dir = load_problem(problem_dir)
    except ValueError as error:
        return "ERROR", "", [
            ("-", "ERROR", str(error))
        ]

    status, results = judge_tests(
        source,
        tests_dir,
        time_limit,
    )

    return status, name, results


def print_results(
    status: str,
    name: str,
    results: list[tuple[str, str, str]],
) -> None:
    if name:
        print(f"Problem: {name}")
        print()

    passed = 0

    for case_name, case_status, message in results:
        print(f"Case {case_name}: {case_status}")

        if case_status == "AC":
            passed += 1
        elif message:
            print(message)

    print()
    print(f"Passed: {passed}/{len(results)}")
    print(f"Status: {status}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "Usage: py Code\\judge_problem.py "
            "<problem_dir> <source.cpp>"
        )
        raise SystemExit(1)

    status, name, results = judge_problem(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
    )

    print_results(status, name, results)

    raise SystemExit(0 if status == "AC" else 1)