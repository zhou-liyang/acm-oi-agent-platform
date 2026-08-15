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
    ) -> None:
        load_dotenv()

        api_key = os.getenv(
            "DEEPSEEK_API_KEY"
        )

        if not api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY is not set."
            )

        self.base_url = os.getenv(
            "DEEPSEEK_BASE_URL",
            "https://api.deepseek.com",
        )

        self.model = (
            model
            or os.getenv(
                "DEEPSEEK_MODEL",
                "deepseek-v4-flash",
            )
        )

        self.timeout = float(
            os.getenv(
                "DEEPSEEK_TIMEOUT_SECONDS",
                "60",
            )
        )

        self.transient_retries = int(
            os.getenv(
                "DEEPSEEK_TRANSIENT_RETRIES",
                "1",
            )
        )

        self.client = OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,
        )

    @staticmethod
    def _read_usage(response) -> ModelUsage:
        usage = response.usage

        if usage is None:
            return ModelUsage()

        completion_details = getattr(
            usage,
            "completion_tokens_details",
            None,
        )

        cached = getattr(
            usage,
            "prompt_cache_hit_tokens",
            0,
        )

        missed = getattr(
            usage,
            "prompt_cache_miss_tokens",
            0,
        )

        prompt_tokens = getattr(
            usage,
            "prompt_tokens",
            0,
        )

        if not missed and prompt_tokens >= cached:
            missed = prompt_tokens - cached

        return ModelUsage(
            input_tokens=prompt_tokens,
            cached_tokens=cached,
            cache_miss_tokens=missed,
            output_tokens=getattr(
                usage,
                "completion_tokens",
                0,
            ),
            reasoning_tokens=(
                getattr(
                    completion_details,
                    "reasoning_tokens",
                    0,
                )
                if completion_details
                else 0
            ),
        )

    @staticmethod
    def _thinking_config(
        reasoning_effort: str,
    ) -> tuple[dict, str | None]:
        effort = (
            reasoning_effort
            .strip()
            .lower()
        )

        if effort in (
            "",
            "none",
            "disabled",
            "off",
        ):
            return (
                {
                    "thinking": {
                        "type": "disabled",
                    }
                },
                None,
            )

        mapping = {
            "low": "low",
            "medium": "high",
            "high": "high",
            "xhigh": "high",
            "max": "max",
        }

        mapped = mapping.get(effort)

        if mapped is None:
            raise ValueError(
                "Unsupported reasoning effort: "
                f"{reasoning_effort}"
            )

        return (
            {
                "thinking": {
                    "type": "enabled",
                }
            },
            mapped,
        )

    def generate(
        self,
        instructions: str,
        input_text: str,
        reasoning_effort: str = "none",
        max_output_tokens: int = 2048,
        json_output: bool = False,
    ) -> ModelResult:
        try:
            extra_body, mapped_effort = (
                self._thinking_config(
                    reasoning_effort
                )
            )

        except ValueError as error:
            return ModelResult(
                ok=False,
                model=self.model,
                text="",
                usage=ModelUsage(),
                error_type="CONFIG",
                error_message=str(error),
            )

        attempts = (
            self.transient_retries + 1
        )

        last_error_type = ""
        last_error_message = ""

        for attempt in range(
            1,
            attempts + 1,
        ):
            try:
                request = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": instructions,
                        },
                        {
                            "role": "user",
                            "content": input_text,
                        },
                    ],
                    "max_tokens": max_output_tokens,
                    "extra_body": extra_body,
                }

                if mapped_effort is not None:
                    request[
                        "reasoning_effort"
                    ] = mapped_effort

                if json_output:
                    request["response_format"] = {
                        "type": "json_object",
                    }

                response = (
                    self.client.chat.completions.create(
                        **request
                    )
                )

                if not response.choices:
                    return ModelResult(
                        ok=False,
                        model=self.model,
                        text="",
                        usage=self._read_usage(
                            response
                        ),
                        error_type="EMPTY",
                        error_message=(
                            "DeepSeek returned "
                            "no choices."
                        ),
                    )

                choice = response.choices[0]
                text = (
                    choice.message.content
                    or ""
                ).strip()

                if choice.finish_reason == "length":
                    return ModelResult(
                        ok=False,
                        model=self.model,
                        text=text,
                        usage=self._read_usage(
                            response
                        ),
                        error_type=(
                            "OUTPUT_INCOMPLETE"
                        ),
                        error_message=(
                            "Model output reached "
                            "the token limit."
                        ),
                    )

                if choice.finish_reason in (
                    "content_filter",
                    "insufficient_system_resource",
                ):
                    return ModelResult(
                        ok=False,
                        model=self.model,
                        text=text,
                        usage=self._read_usage(
                            response
                        ),
                        error_type=(
                            choice.finish_reason.upper()
                        ),
                        error_message=(
                            "DeepSeek stopped before "
                            "a normal completion."
                        ),
                    )

                return ModelResult(
                    ok=True,
                    model=self.model,
                    text=text,
                    usage=self._read_usage(
                        response
                    ),
                )

            except APITimeoutError:
                last_error_type = "TIMEOUT"
                last_error_message = (
                    "DeepSeek API request "
                    "timed out."
                )

            except APIConnectionError as error:
                last_error_type = (
                    "CONNECTION"
                )
                last_error_message = str(
                    error
                )

            except APIStatusError as error:
                return ModelResult(
                    ok=False,
                    model=self.model,
                    text="",
                    usage=ModelUsage(),
                    error_type="HTTP",
                    error_message=str(
                        error
                    ),
                    status_code=(
                        error.status_code
                    ),
                )

            if attempt < attempts:
                print(
                    "Model request transient "
                    f"failure "
                    f"({last_error_type}); "
                    "retrying...",
                    flush=True,
                )
                time.sleep(1.0)

        return ModelResult(
            ok=False,
            model=self.model,
            text="",
            usage=ModelUsage(),
            error_type=last_error_type,
            error_message=last_error_message,
        )
