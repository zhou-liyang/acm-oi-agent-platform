import json
import subprocess
import sys
import time
from pathlib import Path


def run_problem(
    solve_agent: Path,
    problem_dir: Path,
    build_dir: Path,
) -> dict:
    name = problem_dir.name
    statement = problem_dir / "statement.md"
    initial = build_dir / f"{name}.cpp"
    final = initial.with_name(initial.stem + "_final.cpp")
    repair1 = initial.with_name(initial.stem + "_repair1.cpp")
    repair2 = initial.with_name(initial.stem + "_repair2.cpp")
    low = initial.with_name(initial.stem + "_repair_low.cpp")

    print()
    print("=" * 72)
    print(f"PRIVATE PROBLEM: {name}")
    print("=" * 72)

    if not statement.is_file():
        return {
            "name": name,
            "exit_code": 1,
            "status": "MISSING_STATEMENT",
        }

    started = time.perf_counter()

    process = subprocess.run(
        [
            sys.executable,
            str(solve_agent),
            str(problem_dir),
            str(statement),
            str(initial),
        ]
    )

    elapsed = time.perf_counter() - started

    status = (
        "AC"
        if process.returncode == 0
        else (
            "NON_AC"
            if process.returncode == 2
            else "ERROR"
        )
    )

    return {
        "name": name,
        "exit_code": process.returncode,
        "status": status,
        "elapsed_seconds": round(elapsed, 2),
        "initial_source": str(initial),
        "repair1_source": str(repair1),
        "repair2_source": str(repair2),
        "low_source": str(low),
        "final_source": str(final),
    }


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(
            "Usage: py Code\\batch_private.py "
            "<private_problem_root> [build_dir]"
        )
        return 1

    root = Path(sys.argv[1]).resolve()

    if len(sys.argv) == 3:
        build_dir = Path(sys.argv[2]).resolve()
    else:
        build_dir = (Path("Build") / "Private").resolve()

    if not root.is_dir():
        print(f"ERROR: Private problem root not found: {root}")
        return 1

    code_dir = Path(__file__).resolve().parent
    solve_agent = code_dir / "solve_agent.py"

    if not solve_agent.is_file():
        print(f"ERROR: Missing {solve_agent}")
        return 1

    problem_dirs = sorted(
        path
        for path in root.iterdir()
        if (
            path.is_dir()
            and (path / "problem.json").is_file()
            and (path / "Tests").is_dir()
        )
    )

    if not problem_dirs:
        print("ERROR: No private problems found.")
        return 1

    build_dir.mkdir(parents=True, exist_ok=True)

    results = []
    total_started = time.perf_counter()

    for problem_dir in problem_dirs:
        results.append(
            run_problem(
                solve_agent,
                problem_dir,
                build_dir,
            )
        )

    total_elapsed = time.perf_counter() - total_started

    summary_path = build_dir / "summary.json"

    summary_path.write_text(
        json.dumps(
            {
                "total_elapsed_seconds": round(total_elapsed, 2),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    ac = sum(item["status"] == "AC" for item in results)
    non_ac = sum(item["status"] == "NON_AC" for item in results)
    errors = sum(item["status"] == "ERROR" for item in results)

    print()
    print("=" * 72)
    print("BATCH SUMMARY")
    print("=" * 72)
    print(f"Total : {len(results)}")
    print(f"AC    : {ac}")
    print(f"Non-AC: {non_ac}")
    print(f"Error : {errors}")
    print(f"Time  : {total_elapsed:.2f}s")
    print(f"Summary: {summary_path}")

    for item in results:
        print(
            f"{item['name']}: "
            f"{item['status']} "
            f"(exit={item['exit_code']}, "
            f"{item['elapsed_seconds']:.2f}s)"
        )

    if errors:
        return 1
    if non_ac:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
