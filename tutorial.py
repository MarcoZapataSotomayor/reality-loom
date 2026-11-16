"""Session-only guidance driven by real workspace action outcomes."""

from math import dist, hypot
import time

import cv2

from ui import ACCENT, MUTED, Layout, card, draw_button, text


TUTORIAL_MOVE_MIN_FRAME_FRACTION = 0.05  # Final displacement / frame diagonal.
SUCCESS_FEEDBACK_SECONDS = 2.5
SUCCESS_MESSAGE = "Tutorial complete! Release both hands for free play."
EMPTY_MESSAGE = "Tutorial needs an empty workspace. Keep panels or clear them with R in free play."


class Tutorial:
    def __init__(self, interaction):
        self.state = "FREE" if interaction.panels else "WELCOME"
        self.panel_id = None
        self._armed = set()
        self._consumed = set()
        self._help_visible = False
        self._success_until = 0.0

    @property
    def active(self):
        return self.state in ("CREATE", "MOVE", "FREEZE")

    @property
    def showing_card(self):
        return self.active or self.state == "WELCOME"

    def instruction_override(self, interaction):
        if self.showing_card:
            return ""  # The card already contains the current instruction.
        if self._success_until and interaction.notice in ("", SUCCESS_MESSAGE):
            return SUCCESS_MESSAGE
        return None

    def start(self, interaction):
        if interaction.panels:
            interaction.notice = EMPTY_MESSAGE
            return False
        interaction.suspend_for_help()
        interaction.drain_events()
        self.state = "CREATE"
        self.panel_id = None
        self._armed.clear()
        self._success_until = 0.0
        return True

    def skip(self, interaction):
        interaction.suspend_for_help()
        interaction.drain_events()
        self.state = "FREE"
        self.panel_id = None
        self._armed.clear()
        interaction.notice = "Free play. Release both hands to resume."

    def buttons(self, width, height, help_overlay=None):
        if help_overlay is not None and help_overlay.visible:
            return help_overlay.tutorial_buttons(width, height, self.active)
        boxes = Layout(width, height).tutorial_buttons
        if not boxes:
            return {}
        if self.state == "WELCOME":
            return {name: boxes[name] for name in ("START", "FREE")}
        if self.active:
            names = ("FREEZE", "SKIP") if self.state == "FREEZE" else ("SKIP",)
            return {name: boxes[name] for name in names}
        return {}

    def handle_input(self, key, hands, interaction, help_overlay, width, height, camera_ready=True):
        """Return a tutorial UI action; the application still owns freeze/capture."""
        if self.state == "WELCOME" and interaction.panels:
            self.state = "FREE"
        if help_overlay.visible != self._help_visible:
            self._armed.clear()
            self._help_visible = help_overlay.visible
        self._armed.intersection_update(hand.track_id for hand in hands)
        pinching = {hand.track_id for hand in hands if hand.is_pinching}
        self._consumed.intersection_update(pinching)
        candidates = []
        for hand in hands:
            if not hand.is_pinching:
                self._armed.add(hand.track_id)
            elif hand.track_id in self._armed:
                self._armed.remove(hand.track_id)
                hit = False
                for name, box in self.buttons(width, height, help_overlay).items():
                    if box.contains(hand.pinch_point):
                        candidates.append((hand.track_id, name))
                        hit = True
                        break
                background = Layout(width, height).toolbar
                if not hit and self.showing_card and not help_overlay.visible and background and background.contains(hand.pinch_point):
                    candidates.append((hand.track_id, "NOOP"))
        action = min(candidates)[1] if candidates else None
        if key in (ord("u"), ord("U")):
            action = "START"
        elif key in (ord("g"), ord("G")) and self.showing_card:
            action = "SKIP" if self.active else "FREE"
        elif key in (ord("f"), ord("F")) and self.state == "FREEZE" and not help_overlay.visible:
            action = "FREEZE"
        if action is not None:
            self._consumed.update(pinching)
        if action == "START":
            if not camera_ready:
                help_overlay.notice = "Wait for the camera to reconnect."
            elif self.start(interaction):
                help_overlay.visible = False
                help_overlay.notice = ""
            else:
                help_overlay.notice = EMPTY_MESSAGE
            return "CONSUMED"
        if action in ("FREE", "SKIP"):
            self.skip(interaction)
            return "CONSUMED"
        if action == "FREEZE":
            return "FREEZE" if camera_ready and interaction.can_delete and not help_overlay.visible else "CONSUMED"
        if action == "NOOP":
            return "CONSUMED"
        # Existing workspace shortcuts also let experienced users enter free play.
        free_keys = "nNvVmMsSeEyYtTfFrR1234[]"
        if (self.state == "WELCOME" and not help_overlay.visible
                and (key in map(ord, free_keys) or key in (0x2E0000, 0xFFFF, 127))):
            self.state = "FREE"
        return None

    def panel_hands(self, hands):
        return [hand for hand in hands if hand.track_id not in self._consumed]

    def targets(self, width, height):
        box = Layout(width, height).toolbar
        return [box] if self.showing_card and box is not None else []

    def ensure_tool(self, interaction):
        """Use normal tool actions, waiting for their existing release gates."""
        if not self.active:
            return
        if self.state == "CREATE" and self.panel_id is None and interaction.panels:
            self.state = "FREE"
            interaction.notice = EMPTY_MESSAGE
            return
        if self.panel_id is not None and not any(panel.panel_id == self.panel_id for panel in interaction.panels):
            if interaction.panels:
                self.state = "FREE"
                interaction.notice = EMPTY_MESSAGE
                return
            self.state = "CREATE"
            self.panel_id = None
        if not interaction.toolbar_enabled:
            return
        if self.state == "CREATE" and not interaction.creation_mode:
            interaction.begin_creation()
        elif self.state == "MOVE" and interaction.tool != "MOVE":
            interaction.switch_tool("MOVE")
        elif self.state == "FREEZE" and interaction.tool != "SELECT":
            interaction.switch_tool("SELECT")

    def observe(self, interaction, frame_size, paused=False, now=None):
        events = interaction.drain_events()
        if self._success_until and not any(panel.panel_id == self.panel_id for panel in interaction.panels):
            self._success_until = 0.0
            if interaction.notice == SUCCESS_MESSAGE:
                interaction.notice = ""
        if self._success_until and now is None:
            now = time.monotonic()
        if self._success_until and now >= self._success_until:
            if interaction.notice == SUCCESS_MESSAGE:
                interaction.notice = ""
            self._success_until = 0.0
        if paused or not self.active:
            return
        for event in events:
            if self.state == "CREATE" and event.kind == "PLACED":
                if any(panel.panel_id == event.panel_id for panel in interaction.panels):
                    self.panel_id = event.panel_id
                    self.state = "MOVE"
                    interaction.require_release()
                    break
            elif self.state == "MOVE" and event.kind == "DRAG_COMPLETED" and event.panel_id == self.panel_id:
                threshold = hypot(*frame_size) * TUTORIAL_MOVE_MIN_FRAME_FRACTION
                if event.start is not None and event.end is not None and dist(event.start, event.end) >= threshold:
                    self.state = "FREEZE"
                    interaction.require_release()
                    break
            elif self.state == "FREEZE" and event.kind == "FROZEN" and event.panel_id == self.panel_id:
                self.state = "FREE"
                interaction.require_release()
                interaction.notice = SUCCESS_MESSAGE
                self._success_until = (time.monotonic() if now is None else now) + SUCCESS_FEEDBACK_SECONDS
                break

    def on_recovery(self, interaction):
        # A recovery cancellation is never a completed drag or successful freeze.
        interaction.drain_events()
        self._armed.clear()
        if self.active and self.panel_id is not None and not interaction.panels:
            self.state = "CREATE"
            self.panel_id = None

    def draw(self, frame, interaction, hands=(), camera_ready=True):
        if not self.showing_card:
            return
        height, width = frame.shape[:2]
        layout = Layout(width, height)
        if layout.toolbar is None:
            text(frame, "U: tutorial | G: skip / free play", (12, height - 18), width - 24, 0.34, ACCENT)
            return
        box, scale = layout.toolbar, layout.scale
        card(frame, box)
        if self.state == "WELCOME":
            title, instruction = "Create with your hands", "Learn to create, move, and freeze one panel."
        else:
            number = {"CREATE": 1, "MOVE": 2, "FREEZE": 3}[self.state]
            title = f"{number} / 3   {self.state.title()} a panel" if number == 1 else f"{number} / 3   {self.state.title()} your panel"
            instruction = {"CREATE": "Pinch both hands. Move, then release either.",
                           "MOVE": "Pinch inside, drag to a new spot, then release.",
                           "FREEZE": "Activate Freeze to hold your panel's content."}[self.state]
            if interaction.state == "WAITING_FOR_RELEASE":
                instruction = "Release both hands to continue."
        if not camera_ready:
            instruction = "Camera paused. C: retry   Q: exit   G: skip"
        text(frame, title, (box.left + 8, box.top + round(25 * scale)), box.width - 16, 0.58 * scale, ACCENT)
        text(frame, instruction, (box.left + 8, box.top + round(49 * scale)), box.width - 16, 0.42 * scale)
        labels = {"START": "U Start tutorial", "FREE": "G Free play", "SKIP": "G Skip", "FREEZE": "F Freeze"}
        for name, button in self.buttons(width, height).items():
            enabled = name in ("SKIP", "FREE") or camera_ready
            if name == "FREEZE":
                enabled = enabled and interaction.can_delete
            hovered = any(not hand.is_pinching and button.contains(hand.pinch_point) for hand in hands)
            draw_button(frame, button, labels[name], enabled, hovered, scale)
            if name == "FREEZE" and enabled:
                cv2.rectangle(frame, (button.left, button.top), (button.right, button.bottom), ACCENT, 2)
        if not self.active or not camera_ready:
            return
        if self.state == "CREATE":
            corners = layout.tutorial_corners
            if interaction.rectangle is not None:
                rect = interaction.rectangle
                corners = ((round(rect.left), round(rect.top)), (round(rect.right), round(rect.bottom)))
            first, second = corners
            if interaction.rectangle is None:
                cv2.rectangle(frame, first, second, MUTED, 1, cv2.LINE_AA)
            for x, y in corners:
                cv2.line(frame, (x - 9, y), (x + 9, y), ACCENT, 2, cv2.LINE_AA)
                cv2.line(frame, (x, y - 9), (x, y + 9), ACCENT, 2, cv2.LINE_AA)
        elif self.state == "MOVE" and interaction.active_panel is not None:
            rect = interaction.active_panel.rectangle
            x, y = round((rect.left + rect.right) / 2), round((rect.top + rect.bottom) / 2)
            end_x = min(width - 12, x + round(width * 0.1))
            cv2.arrowedLine(frame, (x, y), (end_x, y), ACCENT, 2, cv2.LINE_AA, tipLength=0.25)
