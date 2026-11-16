"""Modal help: UI-only input gating with safe cancellation and rearming."""

from ui import ACCENT, MUTED, Box, draw_button, surface, text


HELP_LINES = (
    "H / Esc: close help     Q: exit",
    "V: select   M: move   S: resize   N: create",
    "E: effects   Y: time   Del: delete   R: clear all",
    "1-4: filter     F: freeze / unfreeze",
    "T: live / delayed     [ / ]: delay step",
    "C: reconnect   D: landmark debug overlays",
    "Create tool: two pinches, move, release",
    "Select / Move: fresh pinch on eligible panel",
    "Resize tool: pinch opposite active handles",
    "Slider: pinch, move, release",
    "Fist: SELECT only; open, hold outside 0.8 s",
    "Esc: restore active edit; idle SELECT exits",
)


class HelpOverlay:
    def __init__(self):
        self.visible = False
        self.notice = ""

    def handle_key(self, key, interaction, slider, toolbar, freeze_control):
        """Consume the opening/closing frame as well as every visible frame."""
        was_visible = self.visible
        if key in (ord("h"), ord("H")) or (self.visible and key == 27):
            self.visible = not self.visible
            self.notice = ""
            slider.cancel(interaction)
            interaction.suspend_for_help()
            toolbar.disable()
            freeze_control.reset()
        return was_visible or self.visible

    @staticmethod
    def geometry(width, height):
        scale = 0.52 if width >= 1000 else 0.43 if width >= 600 else 0.31
        line_height = 28 if width >= 1000 else 23 if width >= 600 else 18
        required_height = 72 + len(HELP_LINES) * line_height
        if width >= 480 and height >= 360:
            required_height += 48
        card_width = min(820, width - 24)
        left = (width - card_width) // 2
        top = max(12, (height - required_height) // 2)
        box = Box(left, top, left + card_width - 1, min(height - 13, top + required_height))
        return box, scale, line_height, required_height

    @classmethod
    def tutorial_buttons(cls, width, height, active=False):
        if width < 480 or height < 360:
            return {}
        box, _, _, _ = cls.geometry(width, height)
        top, bottom = box.bottom - 44, box.bottom - 12
        if not active:
            return {"START": Box(box.left + 12, top, box.right - 12, bottom)}
        middle = (box.left + box.right) // 2
        return {"START": Box(box.left + 12, top, middle - 4, bottom),
                "SKIP": Box(middle + 4, top, box.right - 12, bottom)}

    def draw(self, frame, tutorial_active=False, hands=()):
        if not self.visible:
            return
        height, width = frame.shape[:2]
        surface(frame, 0, 0, width - 1, height - 1, opacity=0.65)
        if height < 180 or width < 240:
            message = "G: skip tutorial" if tutorial_active else "Help needs a larger frame."
            text(frame, message, (8, 20), width - 16, 0.3, ACCENT)
            if height >= 48:
                text(frame, "H/Esc: close | Q: exit", (8, 42), width - 16, 0.3)
            return
        box, scale, line_height, required_height = self.geometry(width, height)
        buttons = self.tutorial_buttons(width, height, tutorial_active)
        surface(frame, box.left, box.top, box.right, box.bottom, opacity=0.97)
        x, y = box.left + 12, box.top + 25
        text(frame, "CONTROLS", (x, y), box.width - 24, scale + 0.08, ACCENT)
        y += line_height
        text(frame, self.notice or "Gestures paused. Panels and content preserved.",
             (x, y), box.width - 24, scale, MUTED)
        for line in HELP_LINES:
            y += line_height
            bottom_margin = 60 if buttons else 30 if required_height > height - 24 else 10
            if y > box.bottom - bottom_margin:
                break
            text(frame, line, (x, y), box.width - 24, scale)
        for name, button in buttons.items():
            label = "U Tutorial" if name == "START" else "G Skip tutorial"
            hovered = any(not hand.is_pinching and button.contains(hand.pinch_point) for hand in hands)
            draw_button(frame, button, label, hovered=hovered)
        if required_height > height - 24 and not buttons:
            message = "G: skip | U: tutorial" if tutorial_active else "U: tutorial / Full help needs a taller frame."
            text(frame, message, (x, box.bottom - 9), box.width - 24, scale, MUTED)
