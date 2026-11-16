"""Fresh-pinch capture for the active panel's rolling delay offset."""

from dataclasses import dataclass

import cv2

from temporal_history import MIN_DELAY_SECONDS, MAX_DELAY_SECONDS, quantize_delay
from ui import ACCENT, MUTED, Layout, card, text


@dataclass
class SliderTrack:
    left: int
    right: int
    y: int

    def contains(self, point):
        return self.left <= point[0] <= self.right and abs(point[1] - self.y) <= 10

    def value_at(self, x):
        fraction = (x - self.left) / (self.right - self.left)
        return quantize_delay(MIN_DELAY_SECONDS + fraction * (MAX_DELAY_SECONDS - MIN_DELAY_SECONDS))

    def marker_x(self, seconds):
        fraction = (quantize_delay(seconds) - MIN_DELAY_SECONDS) / (MAX_DELAY_SECONDS - MIN_DELAY_SECONDS)
        return round(self.left + fraction * (self.right - self.left))


class DelaySlider:
    def __init__(self):
        self.owner_id = None
        self._armed = set()

    @property
    def active(self):
        return self.owner_id is not None

    @staticmethod
    def track(frame_width, frame_height):
        geometry = Layout(frame_width, frame_height).slider_track
        return SliderTrack(*geometry) if geometry is not None else None

    def cancel(self, interaction):
        self.owner_id = None
        self._armed.clear()
        interaction.end_delay_adjustment()

    def update(self, hands, width, height, interaction, enabled, key=-1):
        """Return True for every captured frame, including release or loss."""
        track = self.track(width, height)
        if not enabled or (self.active and track is None):
            consumed = self.active
            self.cancel(interaction)
            return consumed
        if self.active:
            owner = next((hand for hand in hands if hand.track_id == self.owner_id), None)
            if (not interaction.adjusting_delay or interaction.content_mode != "DELAYED"
                    or owner is None or not owner.is_pinching):
                self.cancel(interaction)
            else:
                interaction.set_delay(track.value_at(owner.pinch_point[0]))
            return True
        if not interaction.can_adjust_delay:
            self._armed.clear()
            return False

        visible = {hand.track_id for hand in hands}
        self._armed.intersection_update(visible)
        candidates = []
        for hand in hands:
            if not hand.is_pinching:
                self._armed.add(hand.track_id)
            elif hand.track_id in self._armed:
                self._armed.remove(hand.track_id)
                if track is not None and track.contains(hand.pinch_point):
                    candidates.append(hand)
        if candidates:
            owner = min(candidates, key=lambda hand: hand.track_id)
            if interaction.begin_delay_adjustment():
                self.owner_id = owner.track_id
                interaction.set_delay(track.value_at(owner.pinch_point[0]))
                return True
        if key in (ord("["), ord("]")):
            step = -1 if key == ord("[") else 1
            interaction.set_delay((round(interaction.active_panel.delay_seconds * 10) + step) / 10)
            if any(hand.is_pinching for hand in hands):
                interaction.require_release()
            self._armed.clear()
            return True
        return False

    def draw(self, frame, interaction, enabled):
        if interaction.content_mode != "DELAYED" or interaction.creation_mode:
            return
        height, width = frame.shape[:2]
        layout = Layout(width, height)
        track = self.track(width, height)
        if track is None:
            return
        card(frame, layout.slider)
        color = ACCENT if enabled else MUTED
        value = interaction.active_panel.delay_seconds
        text(frame, f"Delay: {value:.1f} s   [ / ]", (track.left, layout.slider.top + round(19 * layout.scale)),
             track.right - track.left, 0.45 * layout.scale, color)
        cv2.line(frame, (track.left, track.y), (track.right, track.y), MUTED, 2, cv2.LINE_AA)
        cv2.circle(frame, (track.marker_x(value), track.y), 5, color, -1, cv2.LINE_AA)
