"""Combine keyboard and deliberate fist requests into one content toggle."""

import time

from gestures import FistHoldDetector


ACTIVATION_FEEDBACK_SECONDS = 1.2


class FreezeController:
    def __init__(self):
        self.fists = FistHoldDetector()
        self.reset()

    def reset(self):
        """Cancel holds and require a new full-open observation, including after R/C."""
        self.fists.reset()
        self._pending = False
        self._applied = False
        self._now = 0.0
        self._feedback_until = 0.0
        self._feedback = ""

    @property
    def message(self):
        if self._now < self._feedback_until:
            return self._feedback
        return self.fists.message

    def update(self, hands, interaction, now=None):
        """Call after interaction.update so a valid drag-start wins this frame."""
        self._now = time.monotonic() if now is None else now
        self._applied = False
        enabled = interaction.state == "PLACED" and interaction.rectangle is not None
        self._pending = self.fists.update(hands, interaction.rectangle, enabled, self._now)
        if not enabled:
            self._feedback_until = 0.0

    def apply(self, interaction, raw_frame, keyboard=False):
        """Apply at most once per update, after this frame's keyboard input."""
        if self._applied:
            return False
        self._applied = True
        requested = keyboard or self._pending
        self._pending = False
        if keyboard:
            self.fists.reset()  # F must not leave a nearly completed hold running.
        if requested and interaction.toggle_frozen(raw_frame):
            self.fists.reset()
            self._feedback = f"{interaction.content_mode} activated - open hand to rearm."
            self._feedback_until = self._now + ACTIVATION_FEEDBACK_SECONDS
            return True
        return False
