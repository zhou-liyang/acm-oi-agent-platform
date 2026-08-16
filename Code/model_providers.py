from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key_env: str
    base_url_env: str
    default_base_url: str
    timeout_env: str
    retries_env: str


PROVIDERS: dict[str, ProviderConfig] = {
    "deepseek": ProviderConfig(
        name="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        base_url_env="DEEPSEEK_BASE_URL",
        default_base_url="https://api.deepseek.com",
        timeout_env="DEEPSEEK_TIMEOUT_SECONDS",
        retries_env="DEEPSEEK_TRANSIENT_RETRIES",
    ),
    "qwen": ProviderConfig(
        name="qwen",
        api_key_env="DASHSCOPE_API_KEY",
        base_url_env="QWEN_BASE_URL",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_env="QWEN_TIMEOUT_SECONDS",
        retries_env="QWEN_TRANSIENT_RETRIES",
    ),
}


def normalize_provider(name: str | None) -> str:
    value = (name or "deepseek").strip().lower()

    aliases = {
        "ds": "deepseek",
        "deepseek": "deepseek",
        "qwen": "qwen",
        "dashscope": "qwen",
        "aliyun": "qwen",
    }

    normalized = aliases.get(value)
    if normalized is None:
        raise ValueError(f"Unsupported model provider: {name}")

    return normalized


def get_provider(name: str | None) -> ProviderConfig:
    return PROVIDERS[normalize_provider(name)]


def provider_ready(name: str) -> bool:
    provider = get_provider(name)
    return bool(os.getenv(provider.api_key_env))
