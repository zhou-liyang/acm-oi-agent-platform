import json
from pathlib import Path
import sys

from judge_problem import judge_problem


def make_result(
    problem_dir: Path,
    source: Path,
) -> dict:
    status, problem_name, results = judge_problem(
        problem_dir,
        source,
    )

    cases = []

    for name, case_status, message in results:
        cases.append(
            {
                "name": name,
                "status": case_status,
                "message": message,
            }
        )

    passed = sum(
        case["status"] == "AC"
        for case in cases
    )

    return {
        "action": "judge",
        "problem": problem_name,
        "source": str(source),
        "verdict": status,
        "passed": passed,
        "total": len(cases),
        "cases": cases,
    }


def print_json(data: dict) -> None:
    print(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    if len(sys.argv) != 4:
        print_json(
            {
                "action": "",
                "problem": "",
                "source": "",
                "verdict": "ERROR",
                "passed": 0,
                "total": 0,
                "cases": [],
                "message": (
                    "Usage: py Code\\agent_tool.py "
                    "judge <problem_dir> <source.cpp>"
                ),
            }
        )
        return 0

    action = sys.argv[1]

    if action != "judge":
        print_json(
            {
                "action": action,
                "problem": "",
                "source": "",
                "verdict": "ERROR",
                "passed": 0,
                "total": 0,
                "cases": [],
                "message": f"Unsupported action: {action}",
            }
        )
        return 0

    result = make_result(
        Path(sys.argv[2]),
        Path(sys.argv[3]),
    )

    print_json(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())