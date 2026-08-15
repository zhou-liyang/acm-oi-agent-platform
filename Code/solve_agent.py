import os
import shutil
import subprocess
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv

from balance_client import get_balance


load_dotenv()


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name, "1" if default else "0")
    return value.strip().lower() in ("1", "true", "yes", "on")


def cny_balance() -> Decimal | None:
    result = get_balance()
    if not result.ok:
        return None

    for item in result.balances:
        if item.currency.upper() in ("CNY", "RMB"):
            try:
                return Decimal(item.total)
            except InvalidOperation:
                return None
    return None


def print_balance_delta(before: Decimal | None) -> None:
    if before is None:
        return

    after = cny_balance()
    if after is None:
        return

    delta = before - after
    print()
    print("=== BALANCE DELTA ===")
    print(f"Before: \u00A5{before:.2f}")
    print(f"After : \u00A5{after:.2f}")
    print(f"Delta : \u00A5{delta:.2f}")
    print("Note: balance precision may be too coarse for sub-cent runs.")


def run_step(title: str, args: list[str], env: dict[str, str]) -> int:
    print()
    print(f"=== {title} ===")
    print()

    started = time.perf_counter()
    process = subprocess.run(args, env=env)
    elapsed = time.perf_counter() - started

    print()
    print(f"{title} elapsed: {elapsed:.2f}s")
    return process.returncode


def copy_final(source: Path, final_file: Path) -> None:
    final_file.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == final_file.resolve():
        return
    shutil.copy2(source, final_file)


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "Usage: py Code\\solve_agent.py "
            "<problem_dir> <statement.md> <output.cpp>"
        )
        return 1

    start_balance = cny_balance()

    try:
        code_dir = Path(__file__).resolve().parent
        problem_dir = Path(sys.argv[1]).resolve()
        statement_file = Path(sys.argv[2]).resolve()
        output_file = Path(sys.argv[3]).resolve()

        final_file = output_file.with_name(output_file.stem + "_final.cpp")
        repair1_file = output_file.with_name(output_file.stem + "_repair1.cpp")
        repair2_file = output_file.with_name(output_file.stem + "_repair2.cpp")
        low_file = output_file.with_name(output_file.stem + "_repair_low.cpp")

        solve_tool = code_dir / "solve_once.py"
        repair_tool = code_dir / "repair_once.py"

        if not problem_dir.is_dir():
            print(f"ERROR: Problem directory does not exist: {problem_dir}")
            return 1
        if not statement_file.is_file():
            print(f"ERROR: Statement file does not exist: {statement_file}")
            return 1
        if not solve_tool.is_file():
            print(f"ERROR: Missing solver tool: {solve_tool}")
            return 1
        if not repair_tool.is_file():
            print(f"ERROR: Missing repair tool: {repair_tool}")
            return 1

        output_file.parent.mkdir(parents=True, exist_ok=True)
        base_env = os.environ.copy()

        solver_env = base_env.copy()
        solver_env.update(
            {
                "DEEPSEEK_SOLVER_MODEL": os.getenv(
                    "DEEPSEEK_AGENT_SOLVER_MODEL",
                    "deepseek-v4-flash",
                ),
                "DEEPSEEK_SOLVER_REASONING": os.getenv(
                    "DEEPSEEK_AGENT_SOLVER_REASONING",
                    "none",
                ),
                "DEEPSEEK_SOLVER_MAX_TOKENS": os.getenv(
                    "DEEPSEEK_AGENT_SOLVER_MAX_TOKENS",
                    "3072",
                ),
            }
        )

        solve_exit = run_step(
            "SOLVER: FLASH / NO THINKING",
            [
                sys.executable,
                str(solve_tool),
                str(problem_dir),
                str(statement_file),
                str(output_file),
            ],
            solver_env,
        )

        if solve_exit == 0:
            copy_final(output_file, final_file)
            print()
            print("=== PIPELINE RESULT ===")
            print("Solver reached AC.")
            print(f"Final source: {final_file}")
            return 0

        if solve_exit != 2:
            print()
            print("=== PIPELINE RESULT ===")
            print("Solver failed before a normal non-AC judge result.")
            print(f"Solver exit code: {solve_exit}")
            return 1

        if not output_file.is_file():
            print()
            print("ERROR: Solver returned non-AC but did not create a source file.")
            return 1

        cheap_env = base_env.copy()
        cheap_env.update(
            {
                "DEEPSEEK_REPAIRER_MODEL": "deepseek-v4-flash",
                "DEEPSEEK_REPAIRER_REASONING": "none",
                "DEEPSEEK_REPAIRER_MAX_TOKENS": "3072",
                "DEEPSEEK_FAILED_CASE_LIMIT": "2",
                "DEEPSEEK_CASE_TEXT_LIMIT": "1600",
            }
        )

        cheap_env["DEEPSEEK_REPAIR_PASS"] = "1"

        repair1_exit = run_step(
            "DIRECT REPAIR #1: FLASH / NO THINKING",
            [
                sys.executable,
                str(repair_tool),
                str(problem_dir),
                str(statement_file),
                str(output_file),
                str(repair1_file),
            ],
            cheap_env,
        )

        if repair1_exit == 0:
            copy_final(repair1_file, final_file)
            print()
            print("=== PIPELINE RESULT ===")
            print("Direct repair #1 reached AC.")
            print(f"Initial source: {output_file}")
            print(f"Final source: {final_file}")
            return 0

        if repair1_exit != 2:
            print()
            print("=== PIPELINE RESULT ===")
            print("Direct repair #1 failed before a normal non-AC judge result.")
            print(f"Repair exit code: {repair1_exit}")
            return 1

        cheap_env["DEEPSEEK_REPAIR_PASS"] = "2"

        repair2_exit = run_step(
            "DIRECT REPAIR #2: FLASH / NO THINKING",
            [
                sys.executable,
                str(repair_tool),
                str(problem_dir),
                str(statement_file),
                str(repair1_file),
                str(repair2_file),
            ],
            cheap_env,
        )

        if repair2_exit == 0:
            copy_final(repair2_file, final_file)
            print()
            print("=== PIPELINE RESULT ===")
            print("Direct repair #2 reached AC.")
            print(f"Final source: {final_file}")
            return 0

        if repair2_exit != 2:
            print()
            print("=== PIPELINE RESULT ===")
            print("Direct repair #2 failed before a normal non-AC judge result.")
            print(f"Repair exit code: {repair2_exit}")
            return 1

        if not env_flag("DEEPSEEK_AGENT_LOW_PASS", False):
            print()
            print("=== PIPELINE RESULT ===")
            print("Two no-thinking repairs are still non-AC.")
            print("Automatic thinking escalation is disabled to protect cost.")
            print(
                "Set DEEPSEEK_AGENT_LOW_PASS=1 only when you want one "
                "Flash-low repair attempt."
            )
            print(f"Latest source: {repair2_file}")
            return 2

        low_env = base_env.copy()
        low_env.update(
            {
                "DEEPSEEK_REPAIRER_MODEL": "deepseek-v4-flash",
                "DEEPSEEK_REPAIRER_REASONING": "low",
                "DEEPSEEK_REPAIRER_MAX_TOKENS": "8192",
                "DEEPSEEK_FAILED_CASE_LIMIT": "3",
                "DEEPSEEK_CASE_TEXT_LIMIT": "2000",
                "DEEPSEEK_REPAIR_PASS": "3",
            }
        )

        low_exit = run_step(
            "DIRECT REPAIR #3: FLASH / LOW THINKING",
            [
                sys.executable,
                str(repair_tool),
                str(problem_dir),
                str(statement_file),
                str(repair2_file),
                str(low_file),
            ],
            low_env,
        )

        print()
        print("=== PIPELINE RESULT ===")

        if low_exit == 0:
            copy_final(low_file, final_file)
            print("Flash-low repair reached AC.")
            print(f"Final source: {final_file}")
            return 0

        if low_exit == 2:
            print("Flash-low repair is still non-AC.")
            print("Stop here. Pro is never called automatically.")
            print(f"Latest source: {low_file}")
            return 2

        print("Flash-low repair failed before a normal judge result.")
        print(f"Exit code: {low_exit}")
        return 1

    finally:
        print_balance_delta(start_balance)


if __name__ == "__main__":
    raise SystemExit(main())
