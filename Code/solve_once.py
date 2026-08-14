import json
import re
import subprocess
import sys
from pathlib import Path

from model_client import ModelClient


def extract_cpp(text: str) -> str:
    text = text.strip()

    fenced = re.search(
        r"```(?:cpp|c\+\+|cc)?\s*\n(.*?)```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if fenced:
        text = fenced.group(1).strip()

    if "#include" not in text and "int main" not in text:
        raise ValueError(
            "Model response does not look like C++ source code."
        )

    return text.rstrip() + "\n"


def run_judge(
    problem_dir: Path,
    source: Path,
) -> dict:
    tool = Path(__file__).resolve().parent / "agent_tool.py"

    process = subprocess.run(
        [
            sys.executable,
            str(tool),
            "judge",
            str(problem_dir),
            str(source),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if not process.stdout.strip():
        raise RuntimeError(
            process.stderr.strip()
            or "Judge tool returned no output."
        )

    try:
        return json.loads(process.stdout)

    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Judge tool returned invalid JSON:\n"
            f"{process.stdout}"
        ) from error


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "Usage: py Code\\solve_once.py "
            "<problem_dir> <statement.md> <output.cpp>"
        )
        return 1

    problem_dir = Path(sys.argv[1]).resolve()
    statement_file = Path(sys.argv[2]).resolve()
    output_file = Path(sys.argv[3]).resolve()

    if not statement_file.is_file():
        print(
            "ERROR: Statement file does not exist: "
            f"{statement_file}"
        )
        return 1

    statement = statement_file.read_text(
        encoding="utf-8-sig",
    )

    try:
        client = ModelClient()

    except ValueError as error:
        print(f"ERROR: {error}")
        return 1

    result = client.generate(
        instructions=(
            "You are solving a simple ACM programming problem. "
            "Return only one complete C++17 source file. "
            "Do not explain the solution. "
            "Do not include Markdown unless unavoidable. "
            "Read input from standard input and write output "
            "to standard output."
        ),
        input_text=statement,
        reasoning_effort="none",
        max_output_tokens=1024,
    )

    if not result.ok:
        print(f"MODEL ERROR: {result.error_type}")

        if result.status_code is not None:
            print(f"HTTP STATUS: {result.status_code}")

        print(result.error_message)
        return 1

    try:
        source = extract_cpp(result.text)

    except ValueError as error:
        print(f"ERROR: {error}")
        print()
        print("Raw model output:")
        print(result.text)
        return 1

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file.write_text(
        source,
        encoding="utf-8",
    )

    print(f"Model: {result.model}")
    print(
        "Usage: "
        f"input={result.usage.input_tokens}, "
        f"cached={result.usage.cached_tokens}, "
        f"output={result.usage.output_tokens}, "
        f"reasoning={result.usage.reasoning_tokens}"
    )
    print(f"Source: {output_file}")
    print()

    try:
        judge = run_judge(
            problem_dir,
            output_file,
        )

    except RuntimeError as error:
        print(f"ERROR: {error}")
        return 1

    print(
        f"Judge: {judge['passed']}/"
        f"{judge['total']} "
        f"{judge['verdict']}"
    )

    for case in judge["cases"]:
        if case["status"] != "AC":
            print(
                f"Case {case['name']}: "
                f"{case['status']}"
            )

            if case["message"]:
                print(case["message"])

    return 0 if judge["verdict"] == "AC" else 2


if __name__ == "__main__":
    raise SystemExit(main())