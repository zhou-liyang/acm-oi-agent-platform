import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from model_client import ModelClient
from solve_once import extract_cpp, run_judge


load_dotenv()

REPAIRER_MODEL = os.getenv(
    "DEEPSEEK_REPAIRER_MODEL",
    "deepseek-v4-flash",
)

REPAIRER_REASONING = os.getenv(
    "DEEPSEEK_REPAIRER_REASONING",
    "none",
)

REPAIR_MAX_TOKENS = int(
    os.getenv(
        "DEEPSEEK_REPAIRER_MAX_TOKENS",
        "3072",
    )
)

FAILED_CASE_LIMIT = int(
    os.getenv(
        "DEEPSEEK_FAILED_CASE_LIMIT",
        "2",
    )
)

CASE_TEXT_LIMIT = int(
    os.getenv(
        "DEEPSEEK_CASE_TEXT_LIMIT",
        "1600",
    )
)

REPAIR_PASS = int(
    os.getenv(
        "DEEPSEEK_REPAIR_PASS",
        "1",
    )
)


def read_text(path: Path) -> str:
    return path.read_text(
        encoding="utf-8-sig",
        errors="replace",
    )


def compact_text(
    text: str,
    limit: int = CASE_TEXT_LIMIT,
) -> str:
    text = " ".join(text.split())

    if len(text) <= limit:
        return text

    front = max(
        1,
        int(limit * 0.7),
    )
    back = max(
        1,
        limit - front - 16,
    )

    return (
        text[:front]
        + " ...[truncated]... "
        + text[-back:]
    )


def read_case_file(
    tests_dir: Path,
    name: str,
    suffix: str,
) -> str:
    path = tests_dir / f"{name}{suffix}"

    if not path.is_file():
        return "(missing)"

    return compact_text(
        read_text(path)
    )


def extract_actual(
    message: str,
) -> str:
    match = re.search(
        r"got '([^']*)'",
        message,
    )

    if match:
        return compact_text(
            match.group(1)
        )

    return compact_text(message)


def select_failed_cases(
    judge: dict,
) -> list[dict]:
    failed = [
        case
        for case in judge["cases"]
        if case["status"] != "AC"
    ]

    if FAILED_CASE_LIMIT <= 0:
        return []

    if len(failed) <= FAILED_CASE_LIMIT:
        return failed

    if FAILED_CASE_LIMIT == 1:
        return [failed[0]]

    indexes = {
        round(
            i * (len(failed) - 1)
            / (FAILED_CASE_LIMIT - 1)
        )
        for i in range(
            FAILED_CASE_LIMIT
        )
    }

    return [
        failed[index]
        for index in sorted(indexes)
    ]


def build_feedback(
    problem_dir: Path,
    judge: dict,
) -> str:
    tests_dir = problem_dir / "Tests"

    failed = [
        case
        for case in judge["cases"]
        if case["status"] != "AC"
    ]

    status_counts: dict[str, int] = {}

    for case in failed:
        status = str(case["status"])
        status_counts[status] = (
            status_counts.get(status, 0)
            + 1
        )

    counts = ", ".join(
        f"{key}={value}"
        for key, value
        in sorted(status_counts.items())
    )

    lines = [
        (
            f"Result: "
            f"{judge['passed']}/"
            f"{judge['total']} "
            f"{judge['verdict']}; "
            f"failures={len(failed)}"
            + (
                f" ({counts})"
                if counts
                else ""
            )
        )
    ]

    selected = select_failed_cases(
        judge
    )

    for case in selected:
        name = str(case["name"])

        input_text = read_case_file(
            tests_dir,
            name,
            ".in",
        )

        expected = read_case_file(
            tests_dir,
            name,
            ".out",
        )

        actual = extract_actual(
            str(
                case.get(
                    "message",
                    "",
                )
            )
        )

        lines.append(
            f"{name}: "
            f"status={case['status']} "
            f"input=[{input_text}] "
            f"expected=[{expected}] "
            f"actual=[{actual}]"
        )

    omitted = (
        len(failed)
        - len(selected)
    )

    if omitted > 0:
        lines.append(
            f"Omitted {omitted} additional "
            "failing cases to control "
            "prompt size."
        )

    return "\n".join(lines)


def print_judge(
    judge: dict,
    label: str,
) -> None:
    print(
        f"{label}: "
        f"{judge['passed']}/"
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

        message = case.get("message")

        if message:
            print(message)

        shown += 1

        if shown >= 5:
            break


def strip_fence(text: str) -> str:
    text = text.strip()

    if text.startswith("```"):
        first_newline = text.find("\n")

        if first_newline != -1:
            text = text[
                first_newline + 1:
            ]

        if text.rstrip().endswith(
            "```"
        ):
            text = text.rstrip()[:-3]

    return text.strip()


def extract_cpp_safe(
    text: str,
) -> str:
    text = strip_fence(text)

    if not text:
        raise ValueError(
            "Model returned empty source."
        )

    if (
        "#include" not in text
        or "int main" not in text
    ):
        raise ValueError(
            "Repairer output does not "
            "look like complete "
            "C++ source."
        )

    return text.rstrip() + "\n"


def main() -> int:
    if len(sys.argv) != 5:
        print(
            "Usage: py Code\\repair_once.py "
            "<problem_dir> "
            "<statement.md> "
            "<source.cpp> "
            "<output.cpp>"
        )
        return 1

    problem_dir = Path(
        sys.argv[1]
    ).resolve()

    statement_file = Path(
        sys.argv[2]
    ).resolve()

    source_file = Path(
        sys.argv[3]
    ).resolve()

    output_file = Path(
        sys.argv[4]
    ).resolve()

    if not problem_dir.is_dir():
        print(
            "ERROR: Missing problem "
            f"directory: {problem_dir}"
        )
        return 1

    if not statement_file.is_file():
        print(
            "ERROR: Missing statement: "
            f"{statement_file}"
        )
        return 1

    if not source_file.is_file():
        print(
            "ERROR: Missing source: "
            f"{source_file}"
        )
        return 1

    statement = read_text(
        statement_file
    )

    source = read_text(
        source_file
    )

    try:
        before = run_judge(
            problem_dir,
            source_file,
        )

    except RuntimeError as error:
        print(f"ERROR: {error}")
        return 1

    print_judge(
        before,
        "Before direct repair",
    )

    if before["verdict"] == "AC":
        print()
        print(
            "Source is already AC. "
            "No repair needed."
        )
        return 0

    feedback = build_feedback(
        problem_dir,
        before,
    )

    try:
        client = ModelClient(
            model=REPAIRER_MODEL
        )

    except ValueError as error:
        print(f"ERROR: {error}")
        return 1

    if REPAIR_PASS >= 2:
        pass_focus = (
            "This is a later repair pass. "
            "A previous repair already failed, "
            "so do not merely preserve its "
            "interpretation and tweak nearby "
            "expressions. Re-derive the problem "
            "model from the statement. Compare "
            "the current source against the "
            "statement fact by fact, especially "
            "fixed sets, masks, literal arrays, "
            "constants, direction conventions, "
            "index bases, and modulo signs. "
            "Treat comments as untrusted: if a "
            "comment describes the right data "
            "but the initializer differs, fix "
            "the initializer. "
        )
    else:
        pass_focus = (
            "Audit statement-defined fixed "
            "sets, masks, literal arrays, "
            "constants, direction conventions, "
            "index bases, and modulo signs while "
            "repairing the main root cause. "
        )

    repair_input = (
        "PROBLEM\n"
        "=======\n"
        f"{statement}\n\n"
        "CURRENT SOURCE\n"
        "==============\n"
        f"{source}\n\n"
        "JUDGE EVIDENCE\n"
        "==============\n"
        f"{feedback}\n\n"
        "TASK\n"
        "====\n"
        "Repair the solution for all valid "
        "inputs. Before writing code, reason "
        "internally through at least the "
        "first supplied failing case: trace "
        "the current source far enough to "
        "explain its actual output, identify "
        "a valid solution strategy/state "
        "that produces the expected output, "
        "and locate the exact condition, "
        "transition, formula, boundary, or "
        "missing state that excludes it. "
        "Cross-check that root cause against "
        "the other supplied failure. "
        "Do not assume a decimal mismatch is "
        "a floating-point or formatting bug "
        "unless tracing the source proves it. "
        "Do not trust source comments over "
        "the problem statement. "
        "Re-derive every hard-coded loop "
        "bound and search limit directly "
        "from the statement constraints. "
        "Do not inherit a numeric bound "
        "merely because the current source "
        "or its comments claim it is safe. "
        "After finding one root cause, also "
        "scan for independent boundary or "
        "state-space errors that could remain "
        "on larger tests. "
        f"{pass_focus}"
        "Then return exactly one complete "
        "C++17 source file and nothing else. "
        "Do not emit analysis, Markdown, or "
        "comments explaining the repair. "
        "Prefer the smallest correct repair "
        "and preserve valid parts of the "
        "current program instead of expanding "
        "it into a larger framework. If a "
        "rewrite is necessary, prioritize a "
        "complete compiling program over "
        "verbosity. Do not hard-code tests. "
        "Keep the program concise and check "
        "integer range and complexity."
    )

    print()
    print(
        "Direct repair config: "
        f"model={REPAIRER_MODEL}, "
        f"reasoning={REPAIRER_REASONING}, "
        f"max_tokens={REPAIR_MAX_TOKENS}, "
        f"failed_cases={FAILED_CASE_LIMIT}, "
        f"pass={REPAIR_PASS}"
    )

    result = client.generate(
        instructions=(
            "You are the direct Repairer in "
            "an ACM/OI solver pipeline. "
            "Judge evidence is debugging "
            "evidence, not a replacement "
            "for the statement. Find the "
            "smallest semantic or algorithmic "
            "root cause that explains the "
            "failures, then repair it. "
            "Output C++17 source only."
        ),
        input_text=repair_input,
        reasoning_effort=(
            REPAIRER_REASONING
        ),
        max_output_tokens=(
            REPAIR_MAX_TOKENS
        ),
    )

    if not result.ok:
        print()
        print(
            "REPAIRER ERROR: "
            f"{result.error_type}"
        )
        print(result.error_message)
        print(
            "Repairer usage before failure: "
            f"input={result.usage.input_tokens}, "
            f"cached={result.usage.cached_tokens}, "
            f"miss={result.usage.cache_miss_tokens}, "
            f"output={result.usage.output_tokens}, "
            f"reasoning={result.usage.reasoning_tokens}"
        )

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
                "Raw repairer output: "
                f"{raw_file}"
            )

        if (
            result.error_type
            != "OUTPUT_INCOMPLETE"
            or not result.text
        ):
            return 1

        print()
        print(
            "OUTPUT_INCOMPLETE: attempting "
            "a conservative partial-source "
            "salvage."
        )

        partial_file = output_file.with_name(
            output_file.name
            + ".partial.cpp"
        )

        partial_source = None

        try:
            partial_source = extract_cpp(
                result.text
            )

        except ValueError as error:
            print(
                "Partial source extraction "
                f"failed: {error}"
            )

        if partial_source is not None:
            partial_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            partial_file.write_text(
                partial_source,
                encoding="utf-8",
            )

            print(
                "Partial source: "
                f"{partial_file}"
            )

            try:
                partial_judge = run_judge(
                    problem_dir,
                    partial_file,
                )

            except RuntimeError as error:
                print(
                    "Partial source judge "
                    f"failed: {error}"
                )

            else:
                print_judge(
                    partial_judge,
                    "Partial repair",
                )

                if (
                    partial_judge["verdict"]
                    == "AC"
                ):
                    output_file.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    output_file.write_text(
                        partial_source,
                        encoding="utf-8",
                    )

                    print(
                        "Accepted salvaged "
                        "partial repair: "
                        f"{output_file}"
                    )

                    return 0

        output_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_file.write_text(
            source,
            encoding="utf-8",
        )

        print()
        print(
            "Partial repair was not safely "
            "usable. Carrying forward the "
            "previous complete source so the "
            "next repair pass can re-derive "
            "the fix."
        )
        print(
            "Fallback source: "
            f"{output_file}"
        )

        return 2

    try:
        repaired_source = extract_cpp(
            result.text
        )

    except ValueError as error:
        print()
        print(f"ERROR: {error}")
        return 1

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file.write_text(
        repaired_source,
        encoding="utf-8",
    )

    print()
    print(
        "Repairer usage: "
        f"input={result.usage.input_tokens}, "
        f"cached={result.usage.cached_tokens}, "
        f"miss={result.usage.cache_miss_tokens}, "
        f"output={result.usage.output_tokens}, "
        f"reasoning={result.usage.reasoning_tokens}"
    )
    print(
        f"Repaired source: "
        f"{output_file}"
    )
    print()

    try:
        after = run_judge(
            problem_dir,
            output_file,
        )

    except RuntimeError as error:
        print(f"ERROR: {error}")
        return 1

    print_judge(
        after,
        "After direct repair",
    )

    return (
        0
        if after["verdict"] == "AC"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
