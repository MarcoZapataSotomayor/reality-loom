"""Modal help: UI-only input gating with safe cancellation and rearming."""

from ui import ACCENT, MUTED, Box, surface, text


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

    def handle_key(self, key, interaction, slider, toolbar, freeze_control):
        """Consume the opening/closing frame as well as every visible frame."""
        was_visible = self.visible
        if key in (ord("h"), ord("H")) or (self.visible and key == 27):
            self.visible = not self.visible
            slider.cancel(interaction)
            interaction.suspend_for_help()
            toolbar.disable()
            freeze_control.reset()
        return was_visible or self.visible

    def draw(self, frame):
        if not self.visible:
            return
        height, width = frame.shape[:2]
        surface(frame, 0, 0, width - 1, height - 1, opacity=0.65)
        if height < 180 or width < 240:
            text(frame, "Help needs a larger frame.", (8, 20), width - 16, 0.3, ACCENT)
            if height >= 48:
                text(frame, "H/Esc: close | Q: exit", (8, 42), width - 16, 0.3)
            return
        scale = 0.52 if width >= 1000 else 0.43 if width >= 600 else 0.31
        line_height = 28 if width >= 1000 else 23 if width >= 600 else 18
        required_height = 72 + len(HELP_LINES) * line_height
        card_width = min(820, width - 24)
        left = (width - card_width) // 2
        box = Box(left, max(12, (height - required_height) // 2), left + card_width - 1,
                  min(height - 13, max(12, (height - required_height) // 2) + required_height))
        surface(frame, box.left, box.top, box.right, box.bottom, opacity=0.97)
        x, y = box.left + 12, box.top + 25
        text(frame, "CONTROLS", (x, y), box.width - 24, scale + 0.08, ACCENT)
        y += line_height
        text(frame, "Gestures paused. Panels and content preserved.", (x, y), box.width - 24, scale, MUTED)
        for line in HELP_LINES:
            y += line_height
            bottom_margin = 30 if required_height > height - 24 else 10
            if y > box.bottom - bottom_margin:
                break
            text(frame, line, (x, y), box.width - 24, scale)
        if required_height > height - 24:
            text(frame, "Full help needs a taller frame.", (x, box.bottom - 9), box.width - 24, scale, MUTED)
