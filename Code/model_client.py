from __future__ import annotations

import os
import time
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)

try:
    from model_providers import get_provider, normalize_provider
except ModuleNotFoundError:
    from Code.model_providers import get_provider, normalize_provider


@dataclass
class ModelUsage:
    input_tokens: int = 0
    cached_tokens: int = 0
    cache_miss_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass
class ModelResult:
    ok: bool
    provider: str
    model: str
    text: str
    usage: ModelUsage
    error_type: str = ""
    error_message: str = ""
    status_code: int | None = None


class ModelClient:
    def __init__(
        self,
        model: str | None = None,
        provider: str | None = None,
    ) -> None:
        load_dotenv()

        self.provider = normalize_provider(
            provider or os.getenv("MODEL_PROVIDER", "deepseek")
        )
        config = get_provider(self.provider)

        api_key = os.getenv(config.api_key_env)
        if not api_key:
            raise ValueError(
                f"{config.api_key_env} is not set for provider {self.provider}."
            )

        self.base_url = os.getenv(
            config.base_url_env,
            config.default_base_url,
        )

        default_model = (
            "deepseek-v4-flash"
            if self.provider == "deepseek"
            else "qwen3.7-flash"
        )

        self.model = (
            model
            or os.getenv("MODEL_NAME")
            or os.getenv(
                "DEEPSEEK_MODEL" if self.provider == "deepseek" else "QWEN_MODEL",
                default_model,
            )
        )

        self.timeout = float(
            os.getenv(config.timeout_env, "60")
        )
        self.transient_retries = int(
            os.getenv(config.retries_env, "1")
        )

        self.client = OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,
        )

    @staticmethod
    def _int_attr(obj, name: str) -> int:
        value = getattr(obj, name, 0)
        return int(value or 0)

    @classmethod
    def _read_usage(cls, response) -> ModelUsage:
        usage = getattr(response, "usage", None)
        if usage is None:
            return ModelUsage()

        prompt_tokens = cls._int_attr(usage, "prompt_tokens")
        output_tokens = cls._int_attr(usage, "completion_tokens")

        cached = cls._int_attr(usage, "prompt_cache_hit_tokens")
        if not cached:
            prompt_details = getattr(usage, "prompt_tokens_details", None)
            if prompt_details is not None:
                cached = cls._int_attr(prompt_details, "cached_tokens")

        missed = cls._int_attr(usage, "prompt_cache_miss_tokens")
        if not missed and prompt_tokens >= cached:
            missed = prompt_tokens - cached

        reasoning = cls._int_attr(usage, "reasoning_tokens")
        completion_details = getattr(
            usage,
            "completion_tokens_details",
            None,
        )
        if not reasoning and completion_details is not None:
            reasoning = cls._int_attr(
                completion_details,
                "reasoning_tokens",
            )

        return ModelUsage(
            input_tokens=prompt_tokens,
            cached_tokens=cached,
            cache_miss_tokens=missed,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning,
        )

    @staticmethod
    def _normalize_effort(reasoning_effort: str) -> str:
        effort = reasoning_effort.strip().lower()
        aliases = {
            "": "none",
            "disabled": "none",
            "off": "none",
            "none": "none",
            "low": "low",
            "medium": "high",
            "high": "high",
            "xhigh": "high",
            "max": "max",
        }
        normalized = aliases.get(effort)
        if normalized is None:
            raise ValueError(
                f"Unsupported reasoning effort: {reasoning_effort}"
            )
        return normalized

    def _provider_request_options(
        self,
        reasoning_effort: str,
        thinking_budget: int | None,
    ) -> tuple[dict, dict]:
        effort = self._normalize_effort(reasoning_effort)
        extra_body: dict = {}
        standard: dict = {}

        if self.provider == "deepseek":
            if effort == "none":
                extra_body["thinking"] = {"type": "disabled"}
            else:
                extra_body["thinking"] = {"type": "enabled"}
                standard["reasoning_effort"] = effort

        elif self.provider == "qwen":
            enabled = effort != "none"
            extra_body["enable_thinking"] = enabled
            if enabled and thinking_budget is not None:
                extra_body["thinking_budget"] = int(thinking_budget)

        return extra_body, standard

    def generate(
        self,
        instructions: str,
        input_text: str,
        reasoning_effort: str = "none",
        max_output_tokens: int = 2048,
        json_output: bool = False,
        thinking_budget: int | None = None,
    ) -> ModelResult:
        try:
            extra_body, standard = self._provider_request_options(
                reasoning_effort,
                thinking_budget,
            )
        except ValueError as error:
            return ModelResult(
                ok=False,
                provider=self.provider,
                model=self.model,
                text="",
                usage=ModelUsage(),
                error_type="CONFIG",
                error_message=str(error),
            )

        attempts = self.transient_retries + 1
        last_error_type = ""
        last_error_message = ""

        for attempt in range(1, attempts + 1):
            try:
                request = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": input_text},
                    ],
                    "max_tokens": max_output_tokens,
                    **standard,
                }

                if extra_body:
                    request["extra_body"] = extra_body

                if json_output:
                    request["response_format"] = {
                        "type": "json_object",
                    }

                response = self.client.chat.completions.create(**request)

                if not response.choices:
                    return ModelResult(
                        ok=False,
                        provider=self.provider,
                        model=self.model,
                        text="",
                        usage=self._read_usage(response),
                        error_type="EMPTY",
                        error_message=(
                            f"{self.provider} returned no choices."
                        ),
                    )

                choice = response.choices[0]
                text = (choice.message.content or "").strip()
                finish_reason = choice.finish_reason or ""

                if finish_reason == "length":
                    return ModelResult(
                        ok=False,
                        provider=self.provider,
                        model=self.model,
                        text=text,
                        usage=self._read_usage(response),
                        error_type="OUTPUT_INCOMPLETE",
                        error_message="Model output reached the token limit.",
                    )

                if finish_reason in (
                    "content_filter",
                    "insufficient_system_resource",
                ):
                    return ModelResult(
                        ok=False,
                        provider=self.provider,
                        model=self.model,
                        text=text,
                        usage=self._read_usage(response),
                        error_type=finish_reason.upper(),
                        error_message=(
                            f"{self.provider} stopped before a normal completion."
                        ),
                    )

                return ModelResult(
                    ok=True,
                    provider=self.provider,
                    model=self.model,
                    text=text,
                    usage=self._read_usage(response),
                )

            except APITimeoutError:
                last_error_type = "TIMEOUT"
                last_error_message = (
                    f"{self.provider} API request timed out."
                )
            except APIConnectionError as error:
                last_error_type = "CONNECTION"
                last_error_message = str(error)
            except APIStatusError as error:
                return ModelResult(
                    ok=False,
                    provider=self.provider,
                    model=self.model,
                    text="",
                    usage=ModelUsage(),
                    error_type="HTTP",
                    error_message=str(error),
                    status_code=error.status_code,
                )

            if attempt < attempts:
                print(
                    "Model request transient failure "
                    f"({self.provider}/{last_error_type}); retrying...",
                    flush=True,
                )
                time.sleep(1.0)

        return ModelResult(
            ok=False,
            provider=self.provider,
            model=self.model,
            text="",
            usage=ModelUsage(),
            error_type=last_error_type,
            error_message=last_error_message,
        )
