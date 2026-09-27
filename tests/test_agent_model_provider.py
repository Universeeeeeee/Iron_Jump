"""Contracts for the model-provider infrastructure shared by Agent modules."""

from __future__ import annotations

import os
from unittest.mock import Mock, patch

import httpx

from agent.common import model_provider


def test_load_model_provider_settings_reads_explicit_environment():
    with patch.dict(
        os.environ,
        {
            "OPENAI_BASE_URL": "https://provider.example/v1",
            "OPENAI_API_KEY": "test-key",
        },
        clear=False,
    ):
        settings = model_provider.load_model_provider_settings()

    assert settings.base_url == "https://provider.example/v1"
    assert settings.api_key == "test-key"
    assert settings.model_name == "deepseek-v4-flash"


def test_build_chat_model_uses_injected_settings_without_network():
    settings = model_provider.ModelProviderSettings(
        base_url="https://provider.example/v1",
        api_key="test-key",
        model_name="test-model",
    )
    fake_provider = Mock(name="provider")
    fake_model = Mock(name="model")

    with (
        patch.object(model_provider, "OpenAIProvider", return_value=fake_provider) as provider,
        patch.object(model_provider, "OpenAIChatModel", return_value=fake_model) as model,
    ):
        client = Mock(spec=httpx.AsyncClient)
        result = model_provider.build_chat_model(client, settings)

    assert result is fake_model
    provider.assert_called_once_with(
        base_url=settings.base_url,
        api_key=settings.api_key,
        http_client=client,
    )
    model.assert_called_once_with("test-model", provider=fake_provider)


def test_default_model_settings_preserve_disabled_thinking():
    assert model_provider.default_model_settings() == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }


def test_windows_bracketed_ipv6_bypass_preserves_system_proxy(monkeypatch):
    """Simulate urllib's Windows registry fallback, then real HTTPX parsing."""
    import asyncio
    import urllib.request

    registry = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890",
                "no": "localhost,127.*, [::1]"}

    def windows_proxies():
        return urllib.request.getproxies_environment() or registry

    with patch.dict(os.environ, {}, clear=True):
        monkeypatch.setattr(model_provider, "getproxies", windows_proxies)
        monkeypatch.setattr("httpx._utils.getproxies", windows_proxies)
        client = model_provider.build_http_client()
        try:
            # Inspect actual selected transports, not just normalized text.
            direct = client._transport_for_url(httpx.URL("https://[::1]/v1"))
            remote = client._transport_for_url(httpx.URL("https://provider.example/v1"))
            assert direct is client._transport
            assert remote is not client._transport
            assert windows_proxies()["https"] == registry["https"]
            assert windows_proxies()["no"] == "localhost,127.*,::1"
        finally:
            asyncio.run(client.aclose())


def test_valid_proxy_environment_is_not_changed():
    import asyncio
    from urllib.request import getproxies_environment

    env = {"https_proxy": "http://127.0.0.1:7890", "no_proxy": "localhost,::1,.example.org"}
    with patch.dict(os.environ, env, clear=True), patch.object(
        model_provider, "getproxies", getproxies_environment
    ), patch("httpx._utils.getproxies", getproxies_environment):
        before = dict(os.environ)  # Windows normalizes environment keys to uppercase.
        client = model_provider.build_http_client()
        try:
            assert dict(os.environ) == before
            assert client._transport_for_url(httpx.URL("https://a.example.org")) is client._transport
        finally:
            asyncio.run(client.aclose())


def test_ipv6_fix_does_not_hide_an_invalid_proxy_url():
    import pytest
    from urllib.request import getproxies_environment

    with patch.dict(os.environ, {"https_proxy": "http://localhost:invalid", "no_proxy": "[::1]"}, clear=True), patch.object(
        model_provider, "getproxies", getproxies_environment
    ), patch("httpx._utils.getproxies", getproxies_environment):
        with pytest.raises(httpx.InvalidURL, match="Invalid port"):
            model_provider.build_http_client()
