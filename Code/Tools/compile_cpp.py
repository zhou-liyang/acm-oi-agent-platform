from pathlib import Path
import shutil
import subprocess
import sys


def compile_cpp(source: Path, output: Path) -> tuple[bool, str]:
    compiler = shutil.which("g++")
    if compiler is None:
        return False, "g++ was not found."

    source = source.resolve()
    output = output.resolve()

    if not source.is_file():
        return False, f"Source file does not exist: {source}"

    output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        compiler,
        str(source),
        "-std=c++17",
        "-O2",
        "-Wall",
        "-Wextra",
        "-o",
        str(output),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    message = result.stdout + result.stderr

    if result.returncode != 0:
        return False, message

    return True, message or f"Compiled successfully: {output}"


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: py compile_cpp.py <source.cpp> <output.exe>")
        raise SystemExit(1)

    ok, message = compile_cpp(
        Path(sys.argv[1]),
        Path(sys.argv[2]),
    )

    print(message)
    raise SystemExit(0 if ok else 1)