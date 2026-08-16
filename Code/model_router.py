from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str
    reasoning: str
    max_tokens: int
    thinking_budget: int | None = None


INITIAL_ROUTES = (
    ModelRoute(
        provider="deepseek",
        model="deepseek-v4-flash",
        reasoning="none",
        max_tokens=3072,
    ),
    ModelRoute(
        provider="qwen",
        model="qwen3.7-flash",
        reasoning="none",
        max_tokens=3072,
    ),
)

ADJUDICATION_ROUTES = (
    ModelRoute(
        provider="deepseek",
        model="deepseek-v4-pro",
        reasoning="low",
        max_tokens=4096,
    ),
    ModelRoute(
        provider="qwen",
        model="qwen3.7-plus",
        reasoning="low",
        max_tokens=4096,
        thinking_budget=512,
    ),
)


def initial_routes() -> tuple[ModelRoute, ...]:
    return INITIAL_ROUTES


def adjudication_routes() -> tuple[ModelRoute, ...]:
    return ADJUDICATION_ROUTES


def routing_snapshot() -> dict:
    return {
        "initial": [asdict(item) for item in INITIAL_ROUTES],
        "adjudication": [asdict(item) for item in ADJUDICATION_ROUTES],
        "policy": {
            "initial_votes": 2,
            "same_provider_resampling": False,
            "escalation_trigger": "case-level substantive disagreement",
            "adjudication_votes": 2,
            "automatic_test_output_edit": False,
        },
    }
