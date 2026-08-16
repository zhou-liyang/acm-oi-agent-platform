from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

from model_providers import get_provider
from model_router import initial_routes, routing_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect model routing; optionally run tiny live connectivity calls."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Make one tiny non-thinking request to each initial provider.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv()

    print("=== MODEL ROUTING SNAPSHOT ===")
    print(json.dumps(routing_snapshot(), ensure_ascii=False, indent=2))
    print()
    print("=== API KEY PRESENCE ===")

    missing: list[str] = []
    for name in ("deepseek", "qwen"):
        provider = get_provider(name)
        ready = bool(os.getenv(provider.api_key_env))
        print(f"{provider.api_key_env:<20} {'SET' if ready else 'MISSING'}")
        if not ready:
            missing.append(provider.api_key_env)

    if not args.live:
        print("No model API request was made.")
        return 0

    if missing:
        print("ERROR: live test requires: " + ", ".join(missing))
        return 1

    from model_client import ModelClient

    print()
    print("=== LIVE CONNECTIVITY ===")
    failed = False

    for route in initial_routes():
        client = ModelClient(
            provider=route.provider,
            model=route.model,
        )
        result = client.generate(
            instructions="Return exactly MODEL_OK and nothing else.",
            input_text="Connectivity test.",
            reasoning_effort="none",
            max_output_tokens=16,
        )
        state = "OK" if result.ok else f"FAIL/{result.error_type}"
        print(
            f"{route.provider:<8} {route.model:<22} {state:<16} "
            f"tokens={result.usage.input_tokens}+{result.usage.output_tokens}"
        )
        if not result.ok:
            failed = True
            print(f"  {result.error_message}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
