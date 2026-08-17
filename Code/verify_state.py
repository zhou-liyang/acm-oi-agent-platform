from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FINAL_STATES = {
    "PACKAGE_FAIL",
    "TESTS_CORROBORATED",
    "TESTS_SUPPORTED_AFTER_ADJUDICATION",
    "REVIEW_REQUIRED",
    "INCONCLUSIVE",
    "TOOL_ERROR",
    "BLOCKED",
}


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(
            encoding="utf-8-sig",
        )
    )


def write_json(
    path: Path,
    data: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def index_package_check(
    summary: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    for item in summary.get("problems", []):
        if not isinstance(item, dict):
            continue

        folder = item.get("folder")
        name = item.get("name")

        key = (
            folder
            if isinstance(folder, str) and folder
            else name
        )

        if isinstance(key, str) and key:
            result[key] = item

    return result


def index_solve_check(
    summary: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    for item in summary.get("results", []):
        if not isinstance(item, dict):
            continue

        name = item.get("problem")

        if isinstance(name, str) and name:
            result[name] = item

    return result


def index_case_compare(
    summary: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    for item in summary.get("problems", []):
        if not isinstance(item, dict):
            continue

        name = item.get("problem")

        if isinstance(name, str) and name:
            result[name] = item

    return result


def merge_adjudications(
    paths: list[Path],
) -> dict[tuple[str, str], dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    # Later files override earlier files for the same problem/case.
    # A later successful adjudication therefore supersedes an earlier
    # tool error from a cheaper model.
    for path in paths:
        summary = read_json(path)

        for record in summary.get("records", []):
            if not isinstance(record, dict):
                continue

            problem = record.get("problem")
            case = record.get("case")

            if not isinstance(problem, str):
                continue

            if not isinstance(case, (str, int)):
                continue

            merged[(problem, str(case))] = {
                **record,
                "source_summary": str(path.resolve()),
            }

    return merged


def resolve_problem(
    name: str,
    package_check: dict[str, dict[str, Any]],
    solve_check: dict[str, dict[str, Any]],
    case_compare: dict[str, dict[str, Any]],
    adjudications: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    package_item = package_check.get(name)
    solve_item = solve_check.get(name)
    compare_item = case_compare.get(name)

    evidence: list[dict[str, Any]] = []

    if package_item is None:
        return {
            "problem": name,
            "state": "BLOCKED",
            "message": "No Package Check result is available.",
            "evidence": evidence,
        }

    package_overall = package_item.get("overall")

    evidence.append(
        {
            "stage": "PACKAGE_CHECK",
            "result": package_overall,
            "meaning": "Mechanical package consistency.",
        }
    )

    if package_overall == "FAIL":
        return {
            "problem": name,
            "state": "PACKAGE_FAIL",
            "message": (
                "Mechanical package checks failed. "
                "Later model evidence must not override this."
            ),
            "evidence": evidence,
        }

    if solve_item is None:
        return {
            "problem": name,
            "state": "INCONCLUSIVE",
            "message": "No independent-solver evidence is available.",
            "evidence": evidence,
        }

    solve_evidence = solve_item.get("evidence")

    evidence.append(
        {
            "stage": "SOLVE_CHECK",
            "result": solve_evidence,
            "meaning": (
                "Fresh whole-problem solver evidence; "
                "non-AC is never treated as proof of a bad package."
            ),
            "attempts_run": solve_item.get("attempts_run"),
        }
    )

    if solve_evidence == "CORROBORATED":
        return {
            "problem": name,
            "state": "TESTS_CORROBORATED",
            "message": (
                "At least one fresh independent whole-problem solver "
                "matched every existing test output."
            ),
            "evidence": evidence,
        }

    if solve_evidence == "TOOL_ERROR":
        return {
            "problem": name,
            "state": "TOOL_ERROR",
            "message": "Independent solving failed at the tool/API layer.",
            "evidence": evidence,
        }

    if solve_evidence == "BLOCKED":
        return {
            "problem": name,
            "state": "BLOCKED",
            "message": "Independent solving was blocked.",
            "evidence": evidence,
        }

    if solve_evidence != "INCONCLUSIVE":
        return {
            "problem": name,
            "state": "INCONCLUSIVE",
            "message": (
                "Independent-solver evidence has an unrecognized state."
            ),
            "evidence": evidence,
        }

    if compare_item is None:
        return {
            "problem": name,
            "state": "INCONCLUSIVE",
            "message": (
                "Whole-problem solvers were non-AC and no local "
                "disagreement analysis is available."
            ),
            "evidence": evidence,
        }

    compare_status = compare_item.get("status")
    suspicious_cases = [
        str(case)
        for case in compare_item.get("suspicious_cases", [])
    ]

    evidence.append(
        {
            "stage": "CASE_COMPARE",
            "result": compare_status,
            "meaning": (
                "Local disagreement matrix across already-generated "
                "candidate programs. Shared disagreement is a trigger "
                "for investigation, not a vote against expected output."
            ),
            "shared_disagreement_cases": suspicious_cases,
        }
    )

    if not suspicious_cases:
        return {
            "problem": name,
            "state": "INCONCLUSIVE",
            "message": (
                "No independent whole-problem AC was found, but no shared "
                "candidate contradiction requiring adjudication was found."
            ),
            "evidence": evidence,
        }

    case_results: list[dict[str, Any]] = []
    unresolved: list[str] = []
    contradicted: list[str] = []
    supported: list[str] = []

    for case in suspicious_cases:
        record = adjudications.get(
            (name, case)
        )

        if record is None:
            unresolved.append(case)
            case_results.append(
                {
                    "case": case,
                    "status": "MISSING",
                }
            )
            continue

        status = record.get("oracle_status")

        case_results.append(
            {
                "case": case,
                "status": status,
                "model": record.get("model"),
                "reasoning": record.get("reasoning"),
                "confidence": record.get("oracle_confidence"),
                "answer": record.get("oracle_answer"),
                "reason": record.get("oracle_reason"),
                "source_summary": record.get("source_summary"),
            }
        )

        if status == "SUPPORTS_EXPECTED":
            supported.append(case)
        elif status == "CONTRADICTS_EXPECTED":
            contradicted.append(case)
        else:
            unresolved.append(case)

    evidence.append(
        {
            "stage": "ADJUDICATION",
            "result": "CASE_LEVEL",
            "meaning": (
                "Case oracle sees only statement + one input. "
                "Expected output, test purpose, candidate code, "
                "and votes are hidden."
            ),
            "cases": case_results,
        }
    )

    if contradicted:
        return {
            "problem": name,
            "state": "REVIEW_REQUIRED",
            "message": (
                "At least one case adjudicator independently contradicts "
                "the existing expected output. Do not auto-edit data; "
                "escalate to stronger or cross-provider verification."
            ),
            "supported_cases": supported,
            "contradicted_cases": contradicted,
            "unresolved_cases": unresolved,
            "evidence": evidence,
        }

    if unresolved:
        return {
            "problem": name,
            "state": "INCONCLUSIVE",
            "message": (
                "Some shared-disagreement cases are still unresolved "
                "because adjudication is missing or failed."
            ),
            "supported_cases": supported,
            "contradicted_cases": contradicted,
            "unresolved_cases": unresolved,
            "evidence": evidence,
        }

    return {
        "problem": name,
        "state": "TESTS_SUPPORTED_AFTER_ADJUDICATION",
        "message": (
            "Whole-problem solvers disagreed with existing outputs on "
            "specific cases, but every shared-disagreement case was "
            "independently adjudicated in favor of the existing output."
        ),
        "supported_cases": supported,
        "contradicted_cases": contradicted,
        "unresolved_cases": unresolved,
        "evidence": evidence,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate Package Check, Solve Check, Case Compare, and Case Review evidence "
            "into explicit problem-level evidence states."
        )
    )

    parser.add_argument(
        "--package-check",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--solve-check",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--case-compare",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--adjudication",
        type=Path,
        action="append",
        default=[],
    )

    parser.add_argument(
        "--names",
        nargs="+",
        required=True,
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    package_check = index_package_check(
        read_json(args.package_check)
    )
    solve_check = index_solve_check(
        read_json(args.solve_check)
    )
    case_compare = index_case_compare(
        read_json(args.case_compare)
    )
    adjudications = merge_adjudications(
        args.adjudication
    )

    problems = [
        resolve_problem(
            name,
            package_check,
            solve_check,
            case_compare,
            adjudications,
        )
        for name in args.names
    ]

    counts = {
        state: sum(
            item["state"] == state
            for item in problems
        )
        for state in sorted(FINAL_STATES)
    }

    report = {
        "semantics": {
            "PACKAGE_FAIL": (
                "Deterministic mechanical package failure."
            ),
            "TESTS_CORROBORATED": (
                "A fresh whole-problem solver matched all existing tests."
            ),
            "TESTS_SUPPORTED_AFTER_ADJUDICATION": (
                "Shared candidate disagreements were resolved in favor "
                "of existing outputs by independent case adjudication."
            ),
            "REVIEW_REQUIRED": (
                "Independent case adjudication contradicts at least one "
                "existing expected output; human/strong/cross-provider "
                "review is required."
            ),
            "INCONCLUSIVE": (
                "Current evidence is insufficient; this is not a failure."
            ),
            "TOOL_ERROR": (
                "Verifier infrastructure/API failure."
            ),
            "BLOCKED": (
                "A prerequisite stage is unavailable."
            ),
        },
        "counts": counts,
        "problems": problems,
    }

    write_json(
        args.output,
        report,
    )

    print()
    print("=== VERIFIER EVIDENCE STATE ===")

    for item in problems:
        print(
            f"{item['problem']:<16} "
            f"{item['state']}"
        )
        print(
            f"  {item['message']}"
        )

        if item.get("supported_cases"):
            print(
                "  supported cases: "
                + ", ".join(
                    item["supported_cases"]
                )
            )

        if item.get("contradicted_cases"):
            print(
                "  contradicted cases: "
                + ", ".join(
                    item["contradicted_cases"]
                )
            )

        if item.get("unresolved_cases"):
            print(
                "  unresolved cases: "
                + ", ".join(
                    item["unresolved_cases"]
                )
            )

    print()
    print("Counts:")
    for state in sorted(FINAL_STATES):
        if counts[state]:
            print(
                f"  {state}: {counts[state]}"
            )

    print()
    print(
        f"Report: {args.output.resolve()}"
    )
    print(
        "No model API request was made."
    )

    if counts["PACKAGE_FAIL"]:
        return 1

    if counts["TOOL_ERROR"]:
        return 1

    if counts["BLOCKED"]:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
