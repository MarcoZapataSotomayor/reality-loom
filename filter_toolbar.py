"""Fixed toolbar layout, fresh-pinch selection, and visible pointer feedback."""

from dataclasses import dataclass

import cv2

from filters import FILTER_NAMES
from ui import ACCENT, MUTED, TEXT, Layout, card, surface, text


POINTER_RADIUS = 6
KEY_FILTERS = {ord(str(index + 1)): name for index, name in enumerate(FILTER_NAMES)}
DELETE_KEYS = (0x2E0000, 0xFFFF, 127)  # Windows waitKeyEx, X11, and common backspace/delete.


@dataclass
class FilterButton:
    name: str
    left: int
    top: int
    right: int
    bottom: int

    def contains(self, point):
        return self.left <= point[0] <= self.right and self.top <= point[1] <= self.bottom


class FilterToolbar:
    def __init__(self):
        self.selected = "ORIGINAL"
        self._armed = set()
        self._consumed = set()
        self.action = None

    @staticmethod
    def buttons(frame_width, frame_height):
        return [FilterButton(name, box.left, box.top, box.right, box.bottom)
                for name, box in zip(FILTER_NAMES, Layout(frame_width, frame_height).filters)]

    def disable(self):
        """Keep the choice, but require a released pinch after returning to idle."""
        self._armed.clear()

    @classmethod
    def action_buttons(cls, frame_width, frame_height):
        return [FilterButton(name, box.left, box.top, box.right, box.bottom)
                for name, box in zip(("NEW", "DELETE", "DELAY"), Layout(frame_width, frame_height).actions)]

    def select(self, name):
        """The one action shared by pinch selection and keys 1-4."""
        if name not in FILTER_NAMES:
            raise ValueError(f"Unknown panel filter: {name}")
        self.selected = name

    def update(self, hands, frame_width, frame_height, enabled, key=-1):
        self.action = None
        visible = {hand.track_id for hand in hands}
        pinching = {hand.track_id for hand in hands if hand.is_pinching}
        self._armed.intersection_update(visible)
        self._consumed.intersection_update(pinching)
        if not enabled:
            self.disable()
            return False

        candidates = []
        buttons = self.buttons(frame_width, frame_height) + self.action_buttons(frame_width, frame_height)
        for hand in hands:
            if not hand.is_pinching:
                self._armed.add(hand.track_id)
            elif hand.track_id in self._armed:
                # Any pinch edge consumes arming, including a pinch outside buttons.
                self._armed.remove(hand.track_id)
                for button in buttons:
                    if button.contains(hand.pinch_point):
                        candidates.append((hand.track_id, button.name))
                        break

        choice = KEY_FILTERS.get(key)
        if key in (ord("n"), ord("N")):
            choice = "NEW"
        elif key in DELETE_KEYS:
            choice = "DELETE"
        elif key in (ord("t"), ord("T")):
            choice = "DELAY"
        if choice is None and candidates:
            choice = min(candidates, key=lambda item: item[0])[1]
        if choice is None:
            return False
        if choice in FILTER_NAMES:
            self.select(choice)
        self.action = choice  # A disabled New/Delete request is consumed for feedback.
        self._consumed.update(pinching)
        return True

    def panel_hands(self, hands):
        """A selecting pinch stays out of panel manipulation until it releases."""
        return [hand for hand in hands if hand.track_id not in self._consumed]

    def draw(self, display_frame, hands, enabled, can_new=True, can_delete=True, context="",
             can_delay=False, delayed=False):
        height, width = display_frame.shape[:2]
        layout = Layout(width, height)
        if layout.toolbar is None:
            return
        buttons = self.buttons(width, height)
        actions = self.action_buttons(width, height)
        caption = (context or "Panel controls") + ("  |  pinch to select" if enabled else "  |  controls paused")
        card(display_frame, layout.toolbar)
        text(display_frame, caption, (layout.toolbar.left + 8, layout.toolbar.top + round(19 * layout.scale)),
             layout.toolbar.width - 16, 0.4 * layout.scale, MUTED)
        labels = {"NEW": "N New panel", "DELETE": "Del Delete", "DELAY": "T Delay"}
        for index, button in enumerate(buttons + actions):
            selected = button.name == self.selected or (button.name == "DELAY" and delayed)
            allowed = enabled and (can_new if button.name == "NEW" else can_delete if button.name == "DELETE"
                                   else can_delay if button.name == "DELAY" else True)
            color = (83, 67, 25) if selected else (53, 47, 42) if allowed else (33, 30, 28)
            surface(display_frame, button.left, button.top, button.right, button.bottom, color, 0.92)
            cv2.rectangle(display_frame, (button.left, button.top), (button.right, button.bottom),
                          ACCENT if selected else (94, 85, 74), 1)
            label = labels.get(button.name, f"{index + 1} {button.name}")
            text_width = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45 * layout.scale, 1)[0][0]
            scale = 0.45 * layout.scale * min(1.0, (button.right - button.left - 16) / max(1, text_width))
            baseline = button.top + (button.bottom - button.top) // 2 + round(5 * layout.scale)
            text(display_frame, label, (button.left + 8, baseline),
                 button.right - button.left - 16, scale,
                 TEXT if allowed else (130, 130, 130))
        for hand in hands:
            point = (round(hand.pinch_point[0]), round(hand.pinch_point[1]))
            color = (0, 255, 255) if hand.is_pinching else (255, 255, 255)
            cv2.circle(display_frame, point, POINTER_RADIUS, color, 1, cv2.LINE_AA)
            cv2.circle(display_frame, point, 1, color, -1, cv2.LINE_AA)
