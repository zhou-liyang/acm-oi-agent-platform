import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


USAGE_RE = re.compile(
    r"(?:Usage|Repairer usage): "
    r"input=(\d+), cached=(\d+), miss=(\d+), "
    r"output=(\d+), reasoning=(\d+)"
)


def parse_stage(text: str, code: int) -> str:
    if "Solver reached AC." in text:
        return "solver"
    if "Direct repair #1 reached AC." in text:
        return "repair1"
    if "Direct repair #2 reached AC." in text:
        return "repair2"
    if "Flash-low repair reached AC." in text:
        return "repair_low"
    if code == 2:
        return "non_ac"
    return "error"


def parse_usage(text: str) -> dict:
    rows = [
        tuple(map(int, m.groups()))
        for m in USAGE_RE.finditer(text)
    ]

    return {
        "api_calls": len(rows),
        "input_tokens": sum(r[0] for r in rows),
        "cached_tokens": sum(r[1] for r in rows),
        "cache_miss_tokens": sum(r[2] for r in rows),
        "output_tokens": sum(r[3] for r in rows),
        "reasoning_tokens": sum(r[4] for r in rows),
    }


def load_problem_meta(problem_dir: Path) -> dict:
    meta = json.loads(
        (problem_dir / "problem.json").read_text(
            encoding="utf-8"
        )
    )

    return meta


def discover(root: Path, difficulty: str) -> list[tuple[Path, dict]]:
    items = []

    for problem_dir in sorted(root.iterdir()):
        if not problem_dir.is_dir():
            continue

        problem_json = problem_dir / "problem.json"
        statement = problem_dir / "statement.md"
        tests = problem_dir / "Tests"

        if not (
            problem_json.is_file()
            and statement.is_file()
            and tests.is_dir()
        ):
            continue

        meta = load_problem_meta(problem_dir)
        d = str(meta.get("difficulty", ""))

        if difficulty != "all" and d != difficulty:
            continue

        items.append((problem_dir, meta))

    return items


def write_csv(path: Path, results: list[dict]) -> None:
    fields = [
        "name",
        "title",
        "difficulty",
        "status",
        "stage",
        "exit_code",
        "elapsed_seconds",
        "api_calls",
        "input_tokens",
        "cached_tokens",
        "cache_miss_tokens",
        "output_tokens",
        "reasoning_tokens",
        "final_source",
        "log_file",
    ]

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )
        writer.writeheader()

        for row in results:
            writer.writerow({
                key: row.get(key, "")
                for key in fields
            })


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "benchmark_root",
        type=Path,
    )

    parser.add_argument(
        "build_root",
        type=Path,
    )

    parser.add_argument(
        "--difficulty",
        choices=[
            "all",
            "silver",
            "gold-easy",
        ],
        default="all",
    )

    args = parser.parse_args()

    repo = Path.cwd().resolve()
    benchmark_root = args.benchmark_root.resolve()
    build_root = args.build_root.resolve()

    solve_agent = (
        repo / "Code" / "solve_agent.py"
    )

    if not benchmark_root.is_dir():
        print(
            "ERROR: benchmark root not found: "
            f"{benchmark_root}"
        )
        return 1

    if not solve_agent.is_file():
        print(
            "ERROR: solve_agent.py not found: "
            f"{solve_agent}"
        )
        return 1

    problems = discover(
        benchmark_root,
        args.difficulty,
    )

    if not problems:
        print("ERROR: no matching problems.")
        return 1

    build_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    logs_dir = build_root / "Logs"
    logs_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    results = []
    started_all = time.perf_counter()

    env = os.environ.copy()

    # Formal V6 baseline:
    # no low-thinking escalation.
    env["DEEPSEEK_AGENT_LOW_PASS"] = "0"

    print()
    print("=== BENCHMARK RUN ===")
    print(f"Root       : {benchmark_root}")
    print(f"Build      : {build_root}")
    print(f"Difficulty : {args.difficulty}")
    print(f"Problems   : {len(problems)}")
    print("Low pass   : disabled")
    print("Pro        : never automatic")
    print()

    for index, (problem_dir, meta) in enumerate(
        problems,
        start=1,
    ):
        name = problem_dir.name
        title = str(
            meta.get("title", name)
        )
        difficulty = str(
            meta.get("difficulty", "")
        )

        print()
        print("=" * 72)
        print(
            f"[{index}/{len(problems)}] "
            f"{name} | {title} | {difficulty}"
        )
        print("=" * 72)

        output_cpp = (
            build_root / f"{name}.cpp"
        )

        log_file = (
            logs_dir / f"{name}.log"
        )

        started = time.perf_counter()

        process = subprocess.run(
            [
                sys.executable,
                str(solve_agent),
                str(problem_dir),
                str(
                    problem_dir
                    / "statement.md"
                ),
                str(output_cpp),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        elapsed = (
            time.perf_counter()
            - started
        )

        text = process.stdout or ""

        print(text, end="")

        log_file.write_text(
            text,
            encoding="utf-8",
        )

        usage = parse_usage(text)
        stage = parse_stage(
            text,
            process.returncode,
        )

        status = (
            "AC"
            if process.returncode == 0
            else (
                "NON_AC"
                if process.returncode == 2
                else "ERROR"
            )
        )

        final_source = (
            output_cpp.with_name(
                output_cpp.stem
                + "_final.cpp"
            )
        )

        result = {
            "name": name,
            "title": title,
            "difficulty": difficulty,
            "status": status,
            "stage": stage,
            "exit_code": process.returncode,
            "elapsed_seconds": round(
                elapsed,
                2,
            ),
            **usage,
            "final_source": str(
                final_source
            ),
            "log_file": str(
                log_file
            ),
        }

        results.append(result)

        print()
        print(
            "RESULT: "
            f"{status} | stage={stage} | "
            f"calls={usage['api_calls']} | "
            f"tokens="
            f"{usage['input_tokens']} in + "
            f"{usage['output_tokens']} out "
            f"({usage['reasoning_tokens']} reasoning) | "
            f"{elapsed:.2f}s"
        )

        # Persist after every problem, so an interrupted run
        # still leaves usable partial data.
        partial = {
            "difficulty_filter":
                args.difficulty,
            "completed":
                len(results),
            "planned":
                len(problems),
            "results":
                results,
        }

        (
            build_root / "summary_partial.json"
        ).write_text(
            json.dumps(
                partial,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        write_csv(
            build_root / "summary_partial.csv",
            results,
        )

    elapsed_all = (
        time.perf_counter()
        - started_all
    )

    stage_counts = {
        key: sum(
            row["stage"] == key
            for row in results
        )
        for key in [
            "solver",
            "repair1",
            "repair2",
            "repair_low",
            "non_ac",
            "error",
        ]
    }

    totals = {
        "problems": len(results),
        "ac": sum(
            r["status"] == "AC"
            for r in results
        ),
        "non_ac": sum(
            r["status"] == "NON_AC"
            for r in results
        ),
        "error": sum(
            r["status"] == "ERROR"
            for r in results
        ),
        "elapsed_seconds":
            round(elapsed_all, 2),
        "api_calls": sum(
            r["api_calls"]
            for r in results
        ),
        "input_tokens": sum(
            r["input_tokens"]
            for r in results
        ),
        "cached_tokens": sum(
            r["cached_tokens"]
            for r in results
        ),
        "cache_miss_tokens": sum(
            r["cache_miss_tokens"]
            for r in results
        ),
        "output_tokens": sum(
            r["output_tokens"]
            for r in results
        ),
        "reasoning_tokens": sum(
            r["reasoning_tokens"]
            for r in results
        ),
        "stage_counts": stage_counts,
    }

    summary = {
        "benchmark_root":
            str(benchmark_root),
        "build_root":
            str(build_root),
        "difficulty_filter":
            args.difficulty,
        "totals":
            totals,
        "results":
            results,
    }

    summary_json = (
        build_root / "summary.json"
    )

    summary_csv = (
        build_root / "summary.csv"
    )

    summary_json.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    write_csv(
        summary_csv,
        results,
    )

    print()
    print("=" * 72)
    print("BENCHMARK SUMMARY")
    print("=" * 72)
    print(
        f"Problems      : "
        f"{totals['problems']}"
    )
    print(
        f"AC            : "
        f"{totals['ac']}"
    )
    print(
        f"Non-AC        : "
        f"{totals['non_ac']}"
    )
    print(
        f"Error         : "
        f"{totals['error']}"
    )
    print(
        f"Solver AC     : "
        f"{stage_counts['solver']}"
    )
    print(
        f"Repair #1 AC  : "
        f"{stage_counts['repair1']}"
    )
    print(
        f"Repair #2 AC  : "
        f"{stage_counts['repair2']}"
    )
    print(
        f"API calls     : "
        f"{totals['api_calls']}"
    )
    print(
        f"Input tokens  : "
        f"{totals['input_tokens']}"
    )
    print(
        f"Output tokens : "
        f"{totals['output_tokens']}"
    )
    print(
        f"Reasoning     : "
        f"{totals['reasoning_tokens']}"
    )
    print(
        f"Elapsed       : "
        f"{totals['elapsed_seconds']:.2f}s"
    )
    print(
        f"JSON          : "
        f"{summary_json}"
    )
    print(
        f"CSV           : "
        f"{summary_csv}"
    )

    if totals["error"]:
        return 1

    if totals["non_ac"]:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
