"""Up to four panel data records, operated by one shared gesture controller."""

from dataclasses import dataclass

from interaction import Rectangle, RectangleInteraction, composite_panel_pixels


MAX_PANELS = 4


@dataclass
class Panel:
    panel_id: int
    rectangle: Rectangle
    filter_name: str = "ORIGINAL"
    frozen_image: object = None

    @property
    def content_mode(self):
        return "FROZEN" if self.frozen_image is not None else "LIVE"


class PanelCollection:
    def __init__(self, controller=None):
        self.controller = controller if controller is not None else RectangleInteraction()
        self.panels = []  # Back to front; only data, never one controller per panel.
        self.active_id = None
        self.default_filter = "ORIGINAL"
        self._next_id = 1
        self._pinches = {}
        self.notice = ""
        self.creation_mode = True
        if self.controller.rectangle is not None and self.controller.state not in ("READY", "CREATING"):
            self._commit_creation()

    @property
    def active_panel(self):
        return next((panel for panel in self.panels if panel.panel_id == self.active_id), None)

    @property
    def state(self):
        return self.controller.state

    @property
    def rectangle(self):
        return self.controller.rectangle

    @property
    def content_mode(self):
        return self.controller.content_mode

    @property
    def selected_filter(self):
        if not self.creation_mode and self.active_panel is not None:
            return self.active_panel.filter_name
        return self.default_filter

    @property
    def toolbar_enabled(self):
        return self.state in ("READY", "PLACED") and (not self.creation_mode or not self.panels)

    @property
    def can_new(self):
        return self.toolbar_enabled and not self.creation_mode and len(self.panels) < MAX_PANELS

    @property
    def can_delete(self):
        return self.toolbar_enabled and not self.creation_mode and self.active_panel is not None

    @property
    def status_text(self):
        target = "NEW" if self.creation_mode else f"ACTIVE #{self.active_id}"
        return f"Panels: {len(self.panels)}/{MAX_PANELS} | {target} | {self.state.replace('_', ' ')}"

    @property
    def instructions(self):
        if self.notice:
            return self.notice
        if self.creation_mode and self.panels:
            return "Create with two pinches. Esc: cancel | R: clear all"
        return self.controller.instructions.replace("R: clear", "R: clear ALL")

    def _commit_creation(self):
        panel = Panel(self._next_id, self.rectangle, self.default_filter, self.controller.frozen_image)
        self._next_id += 1
        self.panels.append(panel)
        self.active_id = panel.panel_id
        self.creation_mode = False
        self.notice = ""

    def _load_active(self, require_release=False):
        self.controller.reset()
        panel = self.active_panel
        if panel is not None:
            self.controller.rectangle = panel.rectangle
            self.controller.frozen_image = panel.frozen_image
            if not require_release:
                self.controller.state = "PLACED"

    def _store_active(self):
        panel = self.active_panel
        if panel is None or self.creation_mode:
            return
        if self.rectangle is None:
            self.panels.remove(panel)
            self.active_id = self.panels[-1].panel_id if self.panels else None
            self.creation_mode = not self.panels
            self._load_active(require_release=True)
        else:
            panel.rectangle = self.rectangle
            panel.frozen_image = self.controller.frozen_image

    def require_release(self):
        if not self.creation_mode:
            self._store_active()
            self._load_active(require_release=True)
        else:
            self.controller.reset()
        self._pinches = {}

    def begin_creation(self):
        if self.creation_mode or not self.toolbar_enabled:
            self.notice = "Finish or cancel the current creation first."
            return False
        if len(self.panels) >= MAX_PANELS:
            self.notice = f"Limit: {MAX_PANELS} panels. Delete one first; release both hands."
            self.require_release()
            return False
        self._store_active()
        self.creation_mode = True
        self.controller.reset()
        self._pinches = {}
        self.notice = "Release both hands to create. Esc: cancel."
        return True

    def cancel_creation(self):
        if not self.creation_mode or not self.panels:
            return False
        self.creation_mode = False
        self._load_active(require_release=True)
        self._pinches = {}
        self.notice = "Creation canceled. Release both hands."
        return True

    def delete_active(self):
        if not self.can_delete:
            self.notice = "No placed active panel to delete."
            return False
        self.panels.remove(self.active_panel)
        self.active_id = self.panels[-1].panel_id if self.panels else None
        self.creation_mode = not self.panels
        self._load_active(require_release=True)
        self._pinches = {}
        self.notice = "Panel deleted. Release both hands."
        return True

    def select_filter(self, name):
        if not self.toolbar_enabled:
            return False
        from filters import FILTER_NAMES

        if name not in FILTER_NAMES:
            raise ValueError(f"Unknown panel filter: {name}")
        if not self.creation_mode and self.active_panel is not None:
            self.active_panel.filter_name = name
        else:
            self.default_filter = name
        self.require_release()
        self.notice = f"Filter: {name}. Release both hands."
        return True

    def apply_action(self, action):
        if not self.toolbar_enabled:
            return False
        if action == "NEW":
            return self.begin_creation()
        if action == "DELETE":
            return self.delete_active()
        return self.select_filter(action)

    def reset(self):
        """R is clear-all. IDs and the default for future panels are not reset."""
        self.panels.clear()
        self.active_id = None
        self.creation_mode = True
        self.notice = "All panels cleared. Release both hands."
        self._pinches = {}
        self.controller.reset()

    def observe_pinches(self, hands):
        self._pinches = {hand.track_id: hand.is_pinching for hand in hands}
        self.controller.observe_pinches(hands)

    def update(self, hands, frame_width, frame_height):
        previous = self._pinches
        self._pinches = {hand.track_id: hand.is_pinching for hand in hands}
        if self.creation_mode:
            old_state = self.state
            self.controller.update(hands, frame_width, frame_height)
            if self.state == "PLACED" and self.rectangle is not None:
                self._commit_creation()
            elif old_state == "CREATING" and self.state == "WAITING_FOR_RELEASE":
                self.notice = "Creation failed. Release both hands to retry; Esc cancels."
            elif old_state == "WAITING_FOR_RELEASE" and self.state == "READY":
                self.notice = ""
            return

        if not self.controller.can_start_manipulation:
            self.controller.update(hands, frame_width, frame_height)
            self._store_active()
            if self.state == "PLACED":
                self.notice = ""
            return
        self.controller.observe_pinches(hands)
        if self.controller.try_resize(hands):
            self.notice = ""
            return

        candidates = []
        for hand in hands:
            if not hand.is_pinching or previous.get(hand.track_id) is not False:
                continue
            hit = next((panel for panel in reversed(self.panels)
                        if panel.rectangle.contains(hand.pinch_point)), None)
            if hit is not None:
                candidates.append((hand.track_id, hit, hand))
        if candidates:
            _, selected, hand = min(candidates, key=lambda item: item[0])
            self.panels.remove(selected)
            self.panels.append(selected)
            self.active_id = selected.panel_id
            self._load_active()
            self.controller.begin_drag(hand)
            self.notice = ""

    def toggle_frozen(self, raw_frame):
        if self.creation_mode or self.active_panel is None:
            return False
        changed = self.controller.toggle_frozen(raw_frame)
        self._store_active()
        return changed

    def composite(self, raw_frame, display_frame):
        invalid = []
        for panel in self.panels:
            if not composite_panel_pixels(panel.rectangle, panel.frozen_image, raw_frame,
                                          display_frame, panel.filter_name):
                invalid.append(panel)
        for panel in invalid:
            self.panels.remove(panel)
        if invalid:
            if self.active_panel is None:
                self.active_id = self.panels[-1].panel_id if self.panels else None
                self.creation_mode = not self.panels
                self._load_active(require_release=True)
        if self.creation_mode:
            self.controller.composite_panel(raw_frame, display_frame, self.default_filter)

    def prepare_camera_reconnect(self):
        if not self.creation_mode:
            self._store_active()
        self.creation_mode = not self.panels
        self._load_active(require_release=True)
        self._pinches = {}
        self.notice = "Camera recovering. Release both hands after reconnecting."

    def finish_camera_reconnect(self, previous_size, current_size):
        if previous_size != current_size:
            self.reset()
            self.notice = "Frame size changed; panels cleared. Release both hands."
