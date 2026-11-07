"""Agent package exports."""

import qt_runtime  # Select PySide6 before any Qt-dependent submodule.

import os


def _disable_logfire_pydantic_plugin() -> None:
    """Avoid loading the unused Logfire plugin during Pydantic model creation."""
    disabled = os.environ.get("PYDANTIC_DISABLE_PLUGINS", "")
    if disabled in {"__all__", "1", "true"}:
        return

    plugins = [name.strip() for name in disabled.split(",") if name.strip()]
    if "logfire-plugin" not in plugins:
        plugins.append("logfire-plugin")
        os.environ["PYDANTIC_DISABLE_PLUGINS"] = ",".join(plugins)


_disable_logfire_pydantic_plugin()

from .config.models import (
    AthleteProfile,
    LLMTreadmillGaitConfig,
    LLMTreadmillRunningConfig,
)

__all__ = [
    "AthleteProfile",
    "ConfigService",
    "GaitAgent",
    "LLMTreadmillGaitConfig",
    "LLMTreadmillRunningConfig",
]


def __getattr__(name: str):
    if name in {"ConfigService", "GaitAgent"}:
        from .config.service import ConfigService

        return ConfigService
    raise AttributeError(name)

