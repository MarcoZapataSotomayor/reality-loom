"""Fixed toolbar layout, fresh-pinch selection, and visible pointer feedback."""

from dataclasses import dataclass

import cv2

from filters import FILTER_NAMES


TOOLBAR_MARGIN = 12
BUTTON_WIDTH = 104
BUTTON_HEIGHT = 28
BUTTON_GAP = 6
TOOLBAR_BOTTOM_MARGIN = 64
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
        available = frame_width - 2 * TOOLBAR_MARGIN - 3 * BUTTON_GAP
        width = max(1, min(BUTTON_WIDTH, available // 4))
        top = max(0, frame_height - TOOLBAR_BOTTOM_MARGIN - BUTTON_HEIGHT)
        return [FilterButton(name, TOOLBAR_MARGIN + index * (width + BUTTON_GAP), top,
                             TOOLBAR_MARGIN + index * (width + BUTTON_GAP) + width, top + BUTTON_HEIGHT)
                for index, name in enumerate(FILTER_NAMES)]

    def disable(self):
        """Keep the choice, but require a released pinch after returning to idle."""
        self._armed.clear()

    @classmethod
    def action_buttons(cls, frame_width, frame_height):
        filters = cls.buttons(frame_width, frame_height)
        width = filters[0].right - filters[0].left
        top = max(0, filters[0].top - BUTTON_HEIGHT - 12)
        return [FilterButton(name, TOOLBAR_MARGIN + index * (width + BUTTON_GAP), top,
                             TOOLBAR_MARGIN + index * (width + BUTTON_GAP) + width, top + BUTTON_HEIGHT)
                for index, name in enumerate(("NEW", "DELETE"))]

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

    def draw(self, display_frame, hands, enabled, can_new=True, can_delete=True, context=""):
        height, width = display_frame.shape[:2]
        buttons = self.buttons(width, height)
        actions = self.action_buttons(width, height)
        caption = f"Filter: {self.selected} | " + (context or ("pinch or keys 1-4" if enabled else "selection paused"))
        position = (TOOLBAR_MARGIN, max(12, actions[0].top - 10))
        cv2.putText(display_frame, caption, position, cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(display_frame, caption, position, cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (255, 255, 255), 1, cv2.LINE_AA)
        labels = {"NEW": "N New panel", "DELETE": "Del Delete"}
        for index, button in enumerate(buttons + actions):
            selected = button.name == self.selected
            allowed = enabled and (can_new if button.name == "NEW" else can_delete if button.name == "DELETE" else True)
            color = (70, 120, 40) if selected else (35, 35, 35) if allowed else (20, 20, 20)
            cv2.rectangle(display_frame, (button.left, button.top), (button.right, button.bottom), color, -1)
            cv2.rectangle(display_frame, (button.left, button.top), (button.right, button.bottom),
                          (255, 255, 255) if selected else (110, 110, 110), 1)
            label = labels.get(button.name, f"{index + 1} {button.name}")
            text_width = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)[0][0]
            scale = 0.42 * min(1.0, (button.right - button.left - 8) / max(1, text_width))
            cv2.putText(display_frame, label, (button.left + 4, button.top + 19),
                        cv2.FONT_HERSHEY_SIMPLEX, max(0.1, scale),
                        (255, 255, 255) if allowed else (130, 130, 130), 1, cv2.LINE_AA)
        for hand in hands:
            point = (round(hand.pinch_point[0]), round(hand.pinch_point[1]))
            color = (0, 255, 255) if hand.is_pinching else (255, 255, 255)
            cv2.circle(display_frame, point, POINTER_RADIUS, color, 1, cv2.LINE_AA)
            cv2.circle(display_frame, point, 1, color, -1, cv2.LINE_AA)
