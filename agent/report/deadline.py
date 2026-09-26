"""Cooperative wall-clock deadlines for one Report Agent request."""

from __future__ import annotations

import inspect
import math
import os
import time
from dataclasses import dataclass
from typing import Callable


DEFAULT_REPORT_ANALYSIS_DEADLINE_SECONDS = 90.0
SYNTHESIS_RESERVE_SECONDS = 20.0
MAX_MODEL_REQUEST_SECONDS = 30.0


class ReportAnalysisDeadlineConfigurationError(ValueError):
    code = "report_configuration_invalid"


class AnalysisDeadlineExceeded(TimeoutError):
    def __init__(self, stage: str):
        super().__init__(f"Report analysis deadline exceeded during {stage}")
        self.stage = stage


@dataclass(frozen=True)
class ReportAnalysisDeadlinePolicy:
    total_seconds: float = DEFAULT_REPORT_ANALYSIS_DEADLINE_SECONDS
    synthesis_reserve_seconds: float = SYNTHESIS_RESERVE_SECONDS
    max_model_request_seconds: float = MAX_MODEL_REQUEST_SECONDS

    def __post_init__(self) -> None:
        values = (
            self.total_seconds,
            self.synthesis_reserve_seconds,
            self.max_model_request_seconds,
        )
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ReportAnalysisDeadlineConfigurationError(
                "Report analysis deadline values must be positive and finite"
            )
        if self.total_seconds <= self.synthesis_reserve_seconds:
            raise ReportAnalysisDeadlineConfigurationError(
                "Report analysis deadline must exceed the synthesis reserve"
            )

    @classmethod
    def from_environment(cls) -> "ReportAnalysisDeadlinePolicy":
        raw = os.getenv("REPORT_ANALYSIS_DEADLINE_SECONDS")
        if raw is None or not raw.strip():
            return cls()
        try:
            total_seconds = float(raw)
        except ValueError as exc:
            raise ReportAnalysisDeadlineConfigurationError(
                "REPORT_ANALYSIS_DEADLINE_SECONDS must be numeric"
            ) from exc
        return cls(total_seconds=total_seconds)


class ReportAnalysisDeadline:
    def __init__(
        self,
        policy: ReportAnalysisDeadlinePolicy,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy
        self._clock = clock
        self.started_at = clock()

    @property
    def investigation_deadline(self) -> float:
        return (
            self.started_at
            + self.policy.total_seconds
            - self.policy.synthesis_reserve_seconds
        )

    @property
    def total_deadline(self) -> float:
        return self.started_at + self.policy.total_seconds

    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self.started_at)

    def remaining_investigation_seconds(self) -> float:
        return max(0.0, self.investigation_deadline - self._clock())

    def remaining_total_seconds(self) -> float:
        return max(0.0, self.total_deadline - self._clock())

    def investigation_expired(self) -> bool:
        return self.remaining_investigation_seconds() <= 0

    def require_total_time(self, stage: str) -> None:
        if self.remaining_total_seconds() <= 0:
            raise AnalysisDeadlineExceeded(stage)

    def model_timeout_seconds(self, stage: str) -> float:
        remaining = (
            self.remaining_investigation_seconds()
            if stage == "decision"
            else self.remaining_total_seconds()
        )
        if remaining <= 0:
            raise AnalysisDeadlineExceeded(stage)
        return min(self.policy.max_model_request_seconds, remaining)


def call_with_optional_timeout(method, *args, timeout_s: float):
    """Pass the additive timeout keyword without breaking legacy fake agents."""

    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        parameters = ()
    accepts_timeout = any(
        parameter.name == "timeout_s"
        or parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    if accepts_timeout:
        return method(*args, timeout_s=timeout_s)
    return method(*args)


__all__ = [
    "AnalysisDeadlineExceeded",
    "DEFAULT_REPORT_ANALYSIS_DEADLINE_SECONDS",
    "MAX_MODEL_REQUEST_SECONDS",
    "ReportAnalysisDeadline",
    "ReportAnalysisDeadlineConfigurationError",
    "ReportAnalysisDeadlinePolicy",
    "SYNTHESIS_RESERVE_SECONDS",
    "call_with_optional_timeout",
]
