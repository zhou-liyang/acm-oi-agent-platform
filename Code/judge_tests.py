from pathlib import Path
import sys

from Tools.compile_cpp import compile_cpp
from Tools.run_program import run_program
from Tools.compare_output import compare_output


def judge_tests(
    source: Path,
    tests_dir: Path,
    timeout: float = 2.0,
) -> tuple[str, list[tuple[str, str, str]]]:
    source = source.resolve()
    tests_dir = tests_dir.resolve()

    if not source.is_file():
        return "ERROR", [
            ("-", "ERROR", f"Source file does not exist: {source}")
        ]

    if not tests_dir.is_dir():
        return "ERROR", [
            ("-", "ERROR", f"Tests directory does not exist: {tests_dir}")
        ]

    input_files = sorted(tests_dir.glob("*.in"))

    if not input_files:
        return "ERROR", [
            ("-", "ERROR", f"No .in files found in: {tests_dir}")
        ]

    for input_file in input_files:
        expected_file = input_file.with_suffix(".out")

        if not expected_file.is_file():
            return "ERROR", [
                (
                    input_file.stem,
                    "ERROR",
                    f"Missing output file: {expected_file}",
                )
            ]

    build_dir = Path("Build").resolve()
    program = build_dir / f"{source.stem}.exe"

    compiled, compile_message = compile_cpp(source, program)

    if not compiled:
        return "CE", [
            ("-", "CE", compile_message)
        ]

    results = []

    for input_file in input_files:
        expected_file = input_file.with_suffix(".out")

        input_text = input_file.read_text(
            encoding="utf-8",
            errors="replace",
        )

        expected = expected_file.read_text(
            encoding="utf-8",
            errors="replace",
        )

        run_status, stdout, stderr, return_code = run_program(
            program,
            input_text,
            timeout,
        )

        if run_status == "TLE":
            results.append(
                (
                    input_file.stem,
                    "TLE",
                    "Time limit exceeded.",
                )
            )
            continue

        if run_status == "RE":
            message = f"Runtime error. Exit code: {return_code}"

            if stderr:
                message += f"\n{stderr}"

            results.append(
                (
                    input_file.stem,
                    "RE",
                    message,
                )
            )
            continue

        if run_status != "OK":
            results.append(
                (
                    input_file.stem,
                    "ERROR",
                    stderr or "Unknown execution error.",
                )
            )
            continue

        status, message = compare_output(stdout, expected)

        results.append(
            (
                input_file.stem,
                status,
                message,
            )
        )

    final_status = "AC"

    for _, status, _ in results:
        if status != "AC":
            final_status = status
            break

    return final_status, results


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print(
            "Usage: py Code\\judge_tests.py "
            "<source.cpp> <tests_dir> [timeout]"
        )
        raise SystemExit(1)

    source = Path(sys.argv[1])
    tests_dir = Path(sys.argv[2])
    timeout = float(sys.argv[3]) if len(sys.argv) == 4 else 2.0

    status, results = judge_tests(
        source,
        tests_dir,
        timeout,
    )

    passed = 0

    for name, case_status, message in results:
        print(f"Case {name}: {case_status}")

        if case_status == "AC":
            passed += 1
        elif message:
            print(message)

    print()
    print(f"Passed: {passed}/{len(results)}")
    print(f"Status: {status}")

    raise SystemExit(0 if status == "AC" else 1)