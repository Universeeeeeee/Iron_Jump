"""Short-lived transcript echo rejection, referenced to delivered TTS audio.

This is not acoustic echo cancellation. Exact test controls remain available
for barge-in; headphones are still recommended for reliable full duplex.
"""

from collections import deque
import time

from voice.command_router import match_command, normalize


class PlaybackEchoGuard:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.replies = deque(maxlen=4)

    def remember(self, text, duration_s):
        value = normalize(text).lower()
        expires = self.clock() + duration_s + 2.0
        if self.replies and self.replies[-1][0] == value:
            self.replies[-1] = (value, expires)
        else:
            self.replies.append((value, expires))

    def is_echo(self, text, *, final):
        if match_command(text):
            return False
        value = normalize(text).lower()
        if not value or (final and len(value) < 4):
            return False
        now = self.clock()
        return any(now <= expires and value in reply for reply, expires in self.replies)
