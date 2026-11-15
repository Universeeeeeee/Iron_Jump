"""Compatibility entry point for the unchanged walking algorithm."""
from engine.overground_session import OvergroundSession
from engine.modes.walking_processor import WalkingProcessor


class WalkingSession(OvergroundSession):
    def __init__(self, config, parent=None):
        super().__init__(config, WalkingProcessor, parent)
