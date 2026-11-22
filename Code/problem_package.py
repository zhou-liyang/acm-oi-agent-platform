from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


EXPECTED_SUFFIXES = {".out", ".ans"}
INPUT_SUFFIX = ".in"


@dataclass(frozen=True)
class TestCase:
    name: str
    input_path: Path
    expected_path: Path

    @property
    def expected_suffix(self) -> str:
        return self.expected_path.suffix.lower()


@dataclass
class TestInventory:
    data_dir: Path
    cases: list[TestCase] = field(default_factory=list)
    input_without_output: list[str] = field(default_factory=list)
    output_without_input: list[str] = field(default_factory=list)
    ambiguous_inputs: dict[str, list[str]] = field(default_factory=dict)
    ambiguous_outputs: dict[str, list[str]] = field(default_factory=dict)
    ignored_files: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.input_without_output
            or self.output_without_input
            or self.ambiguous_inputs
            or self.ambiguous_outputs
        )


def natural_key(text: str) -> tuple:
    parts = re.split(r"(\d+)", text.casefold())
    return tuple(
        int(part) if part.isdigit() else part
        for part in parts
    )


def statement_path(
    problem_dir: Path,
    *,
    allow_legacy: bool = True,
) -> Path | None:
    problem_dir = problem_dir.resolve()

    preferred = problem_dir / "problem.md"
    if preferred.is_file():
        return preferred

    if allow_legacy:
        legacy = problem_dir / "statement.md"
        if legacy.is_file():
            return legacy

    return None


def data_directory(
    problem_dir: Path,
    *,
    allow_legacy: bool = True,
) -> Path | None:
    problem_dir = problem_dir.resolve()

    preferred = problem_dir / "data"
    if preferred.is_dir():
        return preferred

    if allow_legacy:
        legacy = problem_dir / "Tests"
        if legacy.is_dir():
            return legacy

    return None


def _group_case_files(
    directory: Path,
) -> tuple[
    dict[str, list[Path]],
    dict[str, list[Path]],
    list[str],
]:
    inputs: dict[str, list[Path]] = {}
    outputs: dict[str, list[Path]] = {}
    ignored: list[str] = []

    for path in sorted(
        (item for item in directory.iterdir() if item.is_file()),
        key=lambda item: natural_key(item.name),
    ):
        suffix = path.suffix.lower()
        key = path.stem.casefold()

        if suffix == INPUT_SUFFIX:
            inputs.setdefault(key, []).append(path)
        elif suffix in EXPECTED_SUFFIXES:
            outputs.setdefault(key, []).append(path)
        else:
            ignored.append(path.name)

    return inputs, outputs, ignored



def discover_test_cases_in_directory(
    directory: Path,
) -> TestInventory:
    directory = directory.resolve()

    if not directory.is_dir():
        return TestInventory(data_dir=directory)

    inputs, outputs, ignored = _group_case_files(directory)

    inventory = TestInventory(
        data_dir=directory,
        ignored_files=ignored,
    )

    all_keys = sorted(
        set(inputs) | set(outputs),
        key=natural_key,
    )

    for key in all_keys:
        input_candidates = inputs.get(key, [])
        output_candidates = outputs.get(key, [])

        display_name = (
            input_candidates[0].stem
            if input_candidates
            else output_candidates[0].stem
        )

        if len(input_candidates) > 1:
            inventory.ambiguous_inputs[display_name] = [
                path.name for path in input_candidates
            ]

        if len(output_candidates) > 1:
            inventory.ambiguous_outputs[display_name] = [
                path.name for path in output_candidates
            ]

        if not input_candidates:
            inventory.output_without_input.append(display_name)
            continue

        if not output_candidates:
            inventory.input_without_output.append(display_name)
            continue

        if len(input_candidates) != 1 or len(output_candidates) != 1:
            continue

        input_path = input_candidates[0]
        expected_path = output_candidates[0]

        inventory.cases.append(
            TestCase(
                name=input_path.stem,
                input_path=input_path,
                expected_path=expected_path,
            )
        )

    inventory.cases.sort(
        key=lambda case: natural_key(case.name)
    )
    inventory.input_without_output.sort(key=natural_key)
    inventory.output_without_input.sort(key=natural_key)

    return inventory


def discover_test_cases(
    problem_dir: Path,
    *,
    allow_legacy: bool = True,
) -> TestInventory:
    directory = data_directory(
        problem_dir,
        allow_legacy=allow_legacy,
    )

    if directory is None:
        return TestInventory(
            data_dir=(problem_dir.resolve() / "data"),
        )

    return discover_test_cases_in_directory(directory)


def find_test_case(
    problem_dir: Path,
    case_name: str,
    *,
    allow_legacy: bool = True,
) -> TestCase:
    inventory = discover_test_cases(
        problem_dir,
        allow_legacy=allow_legacy,
    )

    if not inventory.ok:
        raise ValueError(
            "Test data are ambiguous or incomplete; "
            "run package_check.py first."
        )

    matches = [
        case
        for case in inventory.cases
        if case.name.casefold() == case_name.casefold()
    ]

    if not matches:
        raise ValueError(
            f"Unknown test case: {case_name}"
        )

    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous test case name: {case_name}"
        )

    return matches[0]


def private_assets(
    problem_dir: Path,
) -> dict[str, object]:
    problem_dir = problem_dir.resolve()

    solution = problem_dir / "solution.md"
    source_dir = problem_dir / "source"

    source_files: list[str] = []
    if source_dir.is_dir():
        source_files = [
            str(path.relative_to(problem_dir))
            for path in sorted(
                (item for item in source_dir.rglob("*") if item.is_file()),
                key=lambda item: natural_key(
                    str(item.relative_to(source_dir))
                ),
            )
        ]

    def find_named(*names: str) -> str | None:
        if not source_dir.is_dir():
            return None

        wanted = {name.casefold() for name in names}
        for path in source_dir.rglob("*"):
            if path.is_file() and path.name.casefold() in wanted:
                return str(path.relative_to(problem_dir))
        return None

    return {
        "solution": (
            str(solution.relative_to(problem_dir))
            if solution.is_file()
            else None
        ),
        "source_dir": (
            str(source_dir.relative_to(problem_dir))
            if source_dir.is_dir()
            else None
        ),
        "source_files": source_files,
        "std": find_named("std.cpp", "std.cc", "std.cxx"),
        "maker": find_named(
            "maker.py",
            "maker.cpp",
            "gen.py",
            "gen.cpp",
        ),
        "spj": find_named(
            "spj.cpp",
            "spj.py",
            "checker.cpp",
            "checker.py",
        ),
        "interactor": find_named(
            "interactor.cpp",
            "interactor.py",
        ),
    }
