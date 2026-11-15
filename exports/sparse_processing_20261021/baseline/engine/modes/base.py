"""
base.py — ModeProcessor Protocol

All mode-specific processors (JumpProcessor, TreadmillProcessor, etc.)
adhere to this protocol so GaitEngine can delegate polymorphically.
"""

from __future__ import annotations

from typing import List, Protocol


class ModeProcessor(Protocol):
    """Protocol for mode-specific processing in GaitEngine facade.

    Each processor owns:
      - name: internal stable identifier ("jump", "treadmill_gait", …)
      - display_mode: Chinese UI label ("纵跳", "跑步机跑步", …)
    """

    name: str
    display_mode: str

    def reset(self) -> None:
        """Reset all internal state (called by GaitEngine.reset())."""
        ...

    def process_raw_frame(
        self, contact_bits: List[int], rel_time: float, abs_time: float
    ) -> List[object]:
        """Process one frame of raw contact data.

        Returns a list of event objects (FootEvent, GaitStepEvent, etc.)
        that GaitEngine will re-emit via its Qt signals.
        """
        ...

    def build_report(
        self, reason: str, export_frames: tuple, export_timestamps: tuple
    ):
        """Build the final test report dataclass.

        Called by GaitEngine.build_report() after the test has stopped.
        """
        ...
