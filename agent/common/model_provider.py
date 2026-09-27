"""Lazy model-provider construction shared by Config and Report Agents."""

from __future__ import annotations

import os
from ipaddress import IPv6Address
from dataclasses import dataclass
from pathlib import Path
from urllib.request import getproxies

import httpx
from dotenv import load_dotenv
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


@dataclass(frozen=True)
class ModelProviderSettings:
    base_url: str
    api_key: str
    model_name: str = "deepseek-v4-flash"


def build_http_client() -> httpx.AsyncClient:
    """Normalize Windows IPv6 bypass entries before HTTPX reads proxy settings.

    Only this process's environment is updated. Copy the effective proxies too:
    adding no_proxy alone would suppress urllib's Windows registry fallback.
    """
    proxies = getproxies()
    bypass = proxies.get("no", "")
    hosts = []
    changed = False
    for entry in bypass.split(","):
        host = entry.strip()
        if host.startswith("[") and host.endswith("]"):
            try:
                IPv6Address(host[1:-1])
            except ValueError:
                pass
            else:
                host = host[1:-1]
                changed = True
        hosts.append(host)
    if changed:
        for scheme in ("http", "https", "all"):
            if proxies.get(scheme):
                os.environ[f"{scheme}_proxy"] = proxies[scheme]
        os.environ["no_proxy"] = ",".join(hosts)
    return httpx.AsyncClient()


def load_model_provider_settings() -> ModelProviderSettings:
    """Load provider settings without constructing a model or making requests."""
    dotenv_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(dotenv_path=dotenv_path)
    base_url = os.getenv("OPENAI_BASE_URL")
    api_key = os.getenv("OPENAI_API_KEY")
    if not base_url or not api_key:
        raise RuntimeError(
            "缺少 OPENAI_BASE_URL 或 OPENAI_API_KEY，"
            f"请检查 .env 配置 (查找路径: {dotenv_path})"
        )
    return ModelProviderSettings(base_url=base_url, api_key=api_key)


def build_chat_model(
    http_client: httpx.AsyncClient,
    settings: ModelProviderSettings | None = None,
) -> OpenAIChatModel:
    """Build a fresh model using the caller-owned HTTP client."""
    resolved = settings or load_model_provider_settings()
    provider = OpenAIProvider(
        base_url=resolved.base_url,
        api_key=resolved.api_key,
        http_client=http_client,
    )
    return OpenAIChatModel(resolved.model_name, provider=provider)


def default_model_settings() -> dict:
    """Return the shared provider-specific settings without business policy."""
    return {"extra_body": {"thinking": {"type": "disabled"}}}
