from model_client import ModelClient


def main() -> int:
    try:
        client = ModelClient()
    except ValueError as error:
        print(f"ERROR: {error}")
        return 1

    result = client.generate(
        instructions=(
            "Follow the requested output format exactly. "
            "Do not add explanations."
        ),
        input_text="Output exactly: MODEL_OK",
        reasoning_effort="none",
        max_output_tokens=32,
    )

    if not result.ok:
        print(f"ERROR TYPE: {result.error_type}")

        if result.status_code is not None:
            print(f"HTTP STATUS: {result.status_code}")

        print(result.error_message)
        return 1

    print(f"Model: {result.model}")
    print(f"Output: {result.text}")
    print()
    print(
        f"Input tokens: "
        f"{result.usage.input_tokens}"
    )
    print(
        f"Cached tokens: "
        f"{result.usage.cached_tokens}"
    )
    print(
        f"Output tokens: "
        f"{result.usage.output_tokens}"
    )
    print(
        f"Reasoning tokens: "
        f"{result.usage.reasoning_tokens}"
    )

    if result.text != "MODEL_OK":
        print()
        print("ERROR: Unexpected model output.")
        return 1

    print()
    print("Status: OK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())