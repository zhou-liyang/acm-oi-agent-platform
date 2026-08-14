from pathlib import Path
import ctypes
import os
import subprocess
import sys


SEM_FAILCRITICALERRORS = 0x0001
SEM_NOGPFAULTERRORBOX = 0x0002
SEM_NOOPENFILEERRORBOX = 0x8000


def run_program(
    program: Path,
    input_text: str = "",
    timeout: float = 2.0,
) -> tuple[str, str, str, int | None]:
    program = program.resolve()

    if not program.is_file():
        return "ERROR", "", f"Program does not exist: {program}", None

    old_error_mode = None
    kernel32 = None

    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        old_error_mode = kernel32.SetErrorMode(
            SEM_FAILCRITICALERRORS
            | SEM_NOGPFAULTERRORBOX
            | SEM_NOOPENFILEERRORBOX
        )

    try:
        result = subprocess.run(
            [str(program)],
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

        status = "OK" if result.returncode == 0 else "RE"

        return status, result.stdout, result.stderr, result.returncode

    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")

        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")

        return "TLE", stdout, stderr, None

    finally:
        if kernel32 is not None and old_error_mode is not None:
            kernel32.SetErrorMode(old_error_mode)


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("Usage: py run_program.py <program.exe> [timeout]")
        raise SystemExit(1)

    program = Path(sys.argv[1])
    timeout = float(sys.argv[2]) if len(sys.argv) == 3 else 2.0

    input_text = "" if sys.stdin.isatty() else sys.stdin.read()

    status, stdout, stderr, return_code = run_program(
        program,
        input_text,
        timeout,
    )

    print(f"Status: {status}")

    if stdout:
        print(stdout, end="")

    if stderr:
        print(stderr, end="", file=sys.stderr)

    if return_code is not None:
        print(f"Exit code: {return_code}")

    raise SystemExit(0 if status == "OK" else 1)