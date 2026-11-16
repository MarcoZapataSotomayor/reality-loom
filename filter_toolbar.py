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

    @staticmethod
    def tool_buttons(width, height):
        return [FilterButton(name, box.left, box.top, box.right, box.bottom)
                for name, box in zip(("SELECT", "MOVE", "RESIZE", "NEW"), Layout(width, height).tools)]

    @staticmethod
    def context_buttons(width, height):
        return [FilterButton(name, box.left, box.top, box.right, box.bottom)
                for name, box in zip(("FREEZE", "EFFECTS", "TIME", "DELETE"), Layout(width, height).context)]

    def visible_buttons(self, width, height, interaction=None):
        if interaction is None:
            return self.buttons(width, height) + self.action_buttons(width, height)
        buttons = self.tool_buttons(width, height) + self.context_buttons(width, height)
        if interaction.submenu == "EFFECTS":
            buttons += self.buttons(width, height)
        elif interaction.submenu == "TIME":
            buttons += self.action_buttons(width, height)[2:]
        return buttons

    @staticmethod
    def eligible(name, interaction, enabled=True):
        if not enabled or not interaction.toolbar_enabled:
            return False
        if name in ("SELECT", "NEW"):
            return True if name == "SELECT" else interaction.can_new
        if interaction.active_panel is None:
            return False
        if name == "DELAY":
            return interaction.can_delay
        return True

    def update(self, hands, frame_width, frame_height, enabled, key=-1, interaction=None):
        self.action = None
        visible = {hand.track_id for hand in hands}
        pinching = {hand.track_id for hand in hands if hand.is_pinching}
        self._armed.intersection_update(visible)
        self._consumed.intersection_update(pinching)
        if not enabled:
            self.disable()
            return False
        candidates = []
        buttons = self.visible_buttons(frame_width, frame_height, interaction)
        for hand in hands:
            if not hand.is_pinching:
                self._armed.add(hand.track_id)
            elif hand.track_id in self._armed:
                self._armed.remove(hand.track_id)
                for button in buttons:
                    if button.contains(hand.pinch_point):
                        allowed = interaction is None or self.eligible(button.name, interaction)
                        action = button.name if allowed or button.name == "NEW" else "NOOP"
                        candidates.append((hand.track_id, action))
                        break
        choice = KEY_FILTERS.get(key)
        shortcuts = {ord("n"): "NEW", ord("t"): "DELAY", ord("v"): "SELECT",
                     ord("m"): "MOVE", ord("s"): "RESIZE", ord("e"): "EFFECTS", ord("y"): "TIME"}
        letter = chr(key).lower() if 0 <= key < 128 else ""
        choice = shortcuts.get(ord(letter), choice) if letter else choice
        if key in DELETE_KEYS:
            choice = "DELETE"
        if choice is None and candidates:
            choice = min(candidates, key=lambda item: item[0])[1]
        if choice is None:
            return False
        if choice in FILTER_NAMES:
            self.select(choice)
        self.action = choice
        self._consumed.update(pinching)
        return True

    def panel_hands(self, hands):
        """A selecting pinch stays out of panel manipulation until it releases."""
        return [hand for hand in hands if hand.track_id not in self._consumed]

    def draw(self, display_frame, hands, enabled, can_new=True, can_delete=True, context="",
             can_delay=False, delayed=False, interaction=None):
        height, width = display_frame.shape[:2]
        layout = Layout(width, height)
        if layout.toolbar is None:
            return
        card(display_frame, layout.toolbar)
        caption = "TOOLS / PANEL" if enabled else "CONTROLS PAUSED"
        text(display_frame, caption, (layout.toolbar.left + 8, layout.toolbar.top + round(19 * layout.scale)),
             layout.toolbar.width - 16, 0.4 * layout.scale, MUTED)
        if interaction is not None and interaction.submenu is not None:
            card(display_frame, layout.slider)
        labels = {"NEW": "N New", "SELECT": "V Select", "MOVE": "M Move", "RESIZE": "S Resize",
                  "FREEZE": "F Freeze", "EFFECTS": "E Effects", "TIME": "Y Time", "DELETE": "Del Delete", "DELAY": "T Delay"}
        if interaction is not None and interaction.content_mode == "FROZEN":
            labels["FREEZE"] = "F Unfreeze"
        for button in self.visible_buttons(width, height, interaction):
            selected = button.name == self.selected
            if interaction is not None:
                selected = (button.name == interaction.tool or button.name == interaction.submenu
                            or button.name == interaction.selected_filter
                            or button.name == "DELAY" and interaction.content_mode == "DELAYED")
                allowed = self.eligible(button.name, interaction, enabled)
            else:
                allowed = enabled and (can_new if button.name == "NEW" else can_delete if button.name == "DELETE"
                                       else can_delay if button.name == "DELAY" else True)
            hovered = allowed and any(not hand.is_pinching and button.contains(hand.pinch_point) for hand in hands)
            color = (83, 67, 25) if selected else (75, 65, 50) if hovered else (53, 47, 42) if allowed else (33, 30, 28)
            surface(display_frame, button.left, button.top, button.right, button.bottom, color, 0.92)
            cv2.rectangle(display_frame, (button.left, button.top), (button.right, button.bottom),
                          ACCENT if selected or hovered else (94, 85, 74), 2 if hovered else 1)
            if button.name in FILTER_NAMES:
                label = f"{FILTER_NAMES.index(button.name) + 1} {button.name}"
            else:
                label = labels.get(button.name, button.name)
            label_width = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45 * layout.scale, 1)[0][0]
            scale = 0.45 * layout.scale * min(1.0, (button.right - button.left - 16) / max(1, label_width))
            baseline = button.top + (button.bottom - button.top) // 2 + round(5 * layout.scale)
            text(display_frame, label, (button.left + 8, baseline), button.right - button.left - 16,
                 scale, TEXT if allowed else (130, 130, 130))

    @staticmethod
    def draw_pointers(frame, hands):
        for hand in hands:
            point = (round(hand.pinch_point[0]), round(hand.pinch_point[1]))
            color = (0, 220, 255) if hand.is_pinching else TEXT
            cv2.circle(frame, point, POINTER_RADIUS, color, -1 if hand.is_pinching else 1, cv2.LINE_AA)
            cv2.circle(frame, point, 1, color, -1, cv2.LINE_AA)
