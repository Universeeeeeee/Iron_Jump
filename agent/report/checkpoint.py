"""Minimal adapter from the sequential loop to ReportRepository checkpoints."""

from __future__ import annotations

from reporting.models import SequentialLoopCheckpoint
from reporting.repository import ReportRepository


class RepositoryCheckpointSink:
    def __init__(self, repository: ReportRepository, run_id: str, *, request_digest: str = ""):
        self._repository = repository
        self._run_id = run_id
        self._request_digest = request_digest
        self.latest_checkpoint: SequentialLoopCheckpoint | None = None

    def save(self, checkpoint: SequentialLoopCheckpoint) -> None:
        if checkpoint.request_digest and checkpoint.request_digest != self._request_digest:
            raise ValueError("Checkpoint belongs to another question")
        checkpoint = checkpoint.model_copy(update={"request_digest": self._request_digest})
        self._repository.save_analysis_checkpoint(self._run_id, checkpoint)
        self.latest_checkpoint = checkpoint


__all__ = ["RepositoryCheckpointSink"]
