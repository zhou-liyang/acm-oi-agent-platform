from pathlib import Path
import sys

try:
    from problem_package import data_directory, statement_path
except ModuleNotFoundError:
    from Code.problem_package import data_directory, statement_path

from judge_tests import judge_tests


DEFAULT_TIME_LIMIT_SECONDS = 2.0


def load_problem(
    problem_dir: Path,
) -> tuple[str, float, Path]:
    problem_dir = problem_dir.resolve()

    if not problem_dir.is_dir():
        raise ValueError(
            f"Problem directory does not exist: {problem_dir}"
        )

    statement = statement_path(
        problem_dir,
        allow_legacy=True,
    )
    if statement is None:
        raise ValueError(
            f"Problem statement does not exist: {problem_dir / 'problem.md'}"
        )

    tests_dir = data_directory(
        problem_dir,
        allow_legacy=True,
    )
    if tests_dir is None:
        raise ValueError(
            f"Data directory does not exist: {problem_dir / 'data'}"
        )

    # Temporary deterministic fallback.
    # problem_profile.py will replace this in the next input-contract phase.
    time_limit = DEFAULT_TIME_LIMIT_SECONDS

    return problem_dir.name, time_limit, tests_dir


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
