import os
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
    def __init__(self) -> None:
        load_dotenv()

        api_key = os.getenv("DEEPSEEK_API_KEY")

        if not api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY is not set."
            )

        self.base_url = os.getenv(
            "DEEPSEEK_BASE_URL",
            "https://api.deepseek.com",
        )

        self.model = os.getenv(
            "DEEPSEEK_MODEL",
            "deepseek-v4-flash",
        )

        self.client = OpenAI(
            api_key=api_key,
            base_url=self.base_url,
            timeout=30.0,
            max_retries=0,
        )

    @staticmethod
    def _read_usage(response) -> ModelUsage:
        usage = response.usage

        if usage is None:
            return ModelUsage()

        input_details = getattr(
            usage,
            "input_tokens_details",
            None,
        )

        output_details = getattr(
            usage,
            "output_tokens_details",
            None,
        )

        return ModelUsage(
            input_tokens=getattr(
                usage,
                "input_tokens",
                0,
            ),
            cached_tokens=(
                getattr(
                    input_details,
                    "cached_tokens",
                    0,
                )
                if input_details
                else 0
            ),
            output_tokens=getattr(
                usage,
                "output_tokens",
                0,
            ),
            reasoning_tokens=(
                getattr(
                    output_details,
                    "reasoning_tokens",
                    0,
                )
                if output_details
                else 0
            ),
        )

    def generate(
        self,
        instructions: str,
        input_text: str,
        reasoning_effort: str = "none",
        max_output_tokens: int = 2048,
    ) -> ModelResult:
        try:
            response = self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=input_text,
                reasoning={
                    "effort": reasoning_effort,
                },
                max_output_tokens=max_output_tokens,
            )

        except APITimeoutError:
            return ModelResult(
                ok=False,
                model=self.model,
                text="",
                usage=ModelUsage(),
                error_type="TIMEOUT",
                error_message=(
                    "DeepSeek API request timed out."
                ),
            )

        except APIConnectionError as error:
            return ModelResult(
                ok=False,
                model=self.model,
                text="",
                usage=ModelUsage(),
                error_type="CONNECTION",
                error_message=str(error),
            )

        except APIStatusError as error:
            return ModelResult(
                ok=False,
                model=self.model,
                text="",
                usage=ModelUsage(),
                error_type="HTTP",
                error_message=str(error),
                status_code=error.status_code,
            )

        return ModelResult(
            ok=True,
            model=self.model,
            text=response.output_text.strip(),
            usage=self._read_usage(response),
        )