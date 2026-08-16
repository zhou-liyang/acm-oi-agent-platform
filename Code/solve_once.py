import json
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from model_client import ModelClient


load_dotenv()

SOLVER_PROVIDER = os.getenv(
    "MODEL_PROVIDER",
    "deepseek",
)

SOLVER_MODEL = os.getenv(
    "MODEL_NAME",
    os.getenv(
        "DEEPSEEK_SOLVER_MODEL",
        "deepseek-v4-flash",
    ),
)

SOLVER_REASONING = os.getenv(
    "MODEL_REASONING",
    os.getenv(
        "DEEPSEEK_SOLVER_REASONING",
        "none",
    ),
)

SOLVER_MAX_TOKENS = int(
    os.getenv(
        "MODEL_MAX_TOKENS",
        os.getenv(
            "DEEPSEEK_SOLVER_MAX_TOKENS",
            "3072",
        ),
    )
)

SOLVER_THINKING_BUDGET = (
    int(os.getenv("MODEL_THINKING_BUDGET"))
    if os.getenv("MODEL_THINKING_BUDGET")
    else None
)


def extract_cpp(text: str) -> str:
    text = text.strip()

    if not text:
        raise ValueError(
            "Model returned empty output."
        )

    fenced = re.search(
        r"```(?:cpp|c\+\+|cc)?\s*\n"
        r"(.*?)```",
        text,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    if fenced:
        text = fenced.group(1).strip()

    else:
        open_fenced = re.search(
            r"```(?:cpp|c\+\+|cc)?\s*\n"
            r"(.*)\Z",
            text,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        if open_fenced:
            text = (
                open_fenced
                .group(1)
                .strip()
            )

    if text.startswith("```"):
        first_newline = text.find("\n")

        if first_newline == -1:
            raise ValueError(
                "Model returned only a "
                "Markdown fence."
            )

        text = text[
            first_newline + 1:
        ].strip()

        if text.endswith("```"):
            text = text[:-3].rstrip()

    if (
        "#include" not in text
        or "int main" not in text
    ):
        raise ValueError(
            "Model response does not "
            "look like a complete "
            "C++ source file."
        )

    return text.rstrip() + "\n"


def run_judge(
    problem_dir: Path,
    source: Path,
) -> dict:
    tool = (
        Path(__file__).resolve().parent
        / "agent_tool.py"
    )

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
            or (
                "Judge tool returned "
                "no output."
            )
        )

    try:
        return json.loads(process.stdout)

    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Judge tool returned "
            "invalid JSON:\n"
            f"{process.stdout}"
        ) from error


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "Usage: py Code\\solve_once.py "
            "<problem_dir> "
            "<statement.md> "
            "<output.cpp>"
        )
        return 1

    problem_dir = Path(
        sys.argv[1]
    ).resolve()

    statement_file = Path(
        sys.argv[2]
    ).resolve()

    output_file = Path(
        sys.argv[3]
    ).resolve()

    if not problem_dir.is_dir():
        print(
            "ERROR: Problem directory "
            "does not exist: "
            f"{problem_dir}"
        )
        return 1

    if not statement_file.is_file():
        print(
            "ERROR: Statement file "
            "does not exist: "
            f"{statement_file}"
        )
        return 1

    statement = statement_file.read_text(
        encoding="utf-8-sig",
    )

    try:
        client = ModelClient(
            model=SOLVER_MODEL,
            provider=SOLVER_PROVIDER,
        )

    except ValueError as error:
        print(f"ERROR: {error}")
        return 1

    print(
        "Solver config: "
        f"provider={SOLVER_PROVIDER}, "
        f"model={SOLVER_MODEL}, "
        f"reasoning={SOLVER_REASONING}, "
        f"max_tokens={SOLVER_MAX_TOKENS}"
    )

    result = client.generate(
        instructions=(
            "Solve the ACM/OI programming "
            "problem for all valid inputs. "
            "Return exactly one complete "
            "C++17 source file and nothing "
            "else. Prefer plain source with "
            "no Markdown fences. Do not "
            "explain the solution and do not "
            "write long comments. Check the "
            "constraints, edge cases, integer "
            "range and complexity before "
            "answering. Read standard input "
            "and write standard output."
        ),
        input_text=statement,
        reasoning_effort=SOLVER_REASONING,
        max_output_tokens=SOLVER_MAX_TOKENS,
        thinking_budget=SOLVER_THINKING_BUDGET,
    )

    print(f"Provider: {result.provider}")
    print(f"Model: {result.model}")
    print(
        "Usage: "
        f"input={result.usage.input_tokens}, "
        f"cached={result.usage.cached_tokens}, "
        f"miss={result.usage.cache_miss_tokens}, "
        f"output={result.usage.output_tokens}, "
        f"reasoning={result.usage.reasoning_tokens}"
    )

    if not result.ok:
        print(
            "MODEL ERROR: "
            f"{result.error_type}"
        )

        if result.status_code is not None:
            print(
                "HTTP STATUS: "
                f"{result.status_code}"
            )

        print(result.error_message)

        if result.text:
            raw_file = output_file.with_name(
                output_file.name
                + ".raw.txt"
            )

            raw_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            raw_file.write_text(
                result.text,
                encoding="utf-8",
            )

            print(
                "Raw model output: "
                f"{raw_file}"
            )

        if (
            result.error_type
            != "OUTPUT_INCOMPLETE"
            or not result.text
        ):
            return 1

        print(
            "OUTPUT_INCOMPLETE: "
            "salvaging partial C++ and "
            "continuing to local judge."
        )

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

    shown = 0

    for case in judge["cases"]:
        if case["status"] == "AC":
            continue

        print(
            f"Case {case['name']}: "
            f"{case['status']}"
        )

        if case.get("message"):
            print(case["message"])

        shown += 1

        if shown >= 5:
            break

    return (
        0
        if judge["verdict"] == "AC"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
