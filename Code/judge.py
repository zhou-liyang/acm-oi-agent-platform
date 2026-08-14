from pathlib import Path
import sys

from Tools.compile_cpp import compile_cpp
from Tools.run_program import run_program
from Tools.compare_output import compare_output


def judge(
    source: Path,
    input_file: Path,
    expected_file: Path,
    timeout: float = 2.0,
) -> tuple[str, str]:
    source = source.resolve()
    input_file = input_file.resolve()
    expected_file = expected_file.resolve()

    if not source.is_file():
        return "ERROR", f"Source file does not exist: {source}"

    if not input_file.is_file():
        return "ERROR", f"Input file does not exist: {input_file}"

    if not expected_file.is_file():
        return "ERROR", f"Expected output does not exist: {expected_file}"

    build_dir = Path("Build").resolve()
    program = build_dir / f"{source.stem}.exe"

    compiled, compile_message = compile_cpp(source, program)

    if not compiled:
        return "CE", compile_message

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
        return "TLE", "Time limit exceeded."

    if run_status == "RE":
        message = f"Runtime error. Exit code: {return_code}"

        if stderr:
            message += f"\n{stderr}"

        return "RE", message

    if run_status != "OK":
        return "ERROR", stderr or "Unknown execution error."

    result, message = compare_output(stdout, expected)

    return result, message


if __name__ == "__main__":
    if len(sys.argv) not in (4, 5):
        print(
            "Usage: py Code\\judge.py "
            "<source.cpp> <input.txt> <expected.txt> [timeout]"
        )
        raise SystemExit(1)

    source = Path(sys.argv[1])
    input_file = Path(sys.argv[2])
    expected_file = Path(sys.argv[3])
    timeout = float(sys.argv[4]) if len(sys.argv) == 5 else 2.0

    status, message = judge(
        source,
        input_file,
        expected_file,
        timeout,
    )

    print(f"Status: {status}")

    if message:
        print(message)

    raise SystemExit(0 if status == "AC" else 1)