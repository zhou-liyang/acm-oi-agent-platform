from pathlib import Path
import sys


def compare_output(
    actual: str,
    expected: str,
) -> tuple[str, str]:
    actual_tokens = actual.split()
    expected_tokens = expected.split()

    if actual_tokens == expected_tokens:
        return "AC", "Output matches."

    limit = min(len(actual_tokens), len(expected_tokens))

    for i in range(limit):
        if actual_tokens[i] != expected_tokens[i]:
            return (
                "WA",
                f"Token {i + 1} differs: "
                f"expected '{expected_tokens[i]}', "
                f"got '{actual_tokens[i]}'."
            )

    if len(actual_tokens) < len(expected_tokens):
        return (
            "WA",
            f"Output is incomplete: expected "
            f"{len(expected_tokens)} tokens, "
            f"got {len(actual_tokens)}."
        )

    return (
        "WA",
        f"Output has extra content: expected "
        f"{len(expected_tokens)} tokens, "
        f"got {len(actual_tokens)}."
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "Usage: py compare_output.py "
            "<actual.txt> <expected.txt>"
        )
        raise SystemExit(1)

    actual_path = Path(sys.argv[1])
    expected_path = Path(sys.argv[2])

    if not actual_path.is_file():
        print(f"Actual output does not exist: {actual_path}")
        raise SystemExit(1)

    if not expected_path.is_file():
        print(f"Expected output does not exist: {expected_path}")
        raise SystemExit(1)

    actual = actual_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    expected = expected_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    status, message = compare_output(actual, expected)

    print(f"Status: {status}")
    print(message)

    raise SystemExit(0 if status == "AC" else 1)