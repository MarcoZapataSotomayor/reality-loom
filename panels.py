"""Up to four panel data records, operated by one shared gesture controller."""

from dataclasses import dataclass, replace
from time import monotonic

import numpy as np

from interaction import Rectangle, RectangleInteraction, composite_panel_pixels
from temporal_history import DELAY_SECONDS, TemporalHistory, quantize_delay
from ui import draw_buffering


MAX_PANELS = 4


@dataclass
class Panel:
    panel_id: int
    rectangle: Rectangle
    filter_name: str = "ORIGINAL"
    frozen_image: object = None
    source_mode: str = "LIVE"  # Retained while FROZEN for unfreezing.
    delay_seconds: float = DELAY_SECONDS

    @property
    def content_mode(self):
        return "FROZEN" if self.frozen_image is not None else self.source_mode


class PanelCollection:
    def __init__(self, controller=None):
        self.controller = controller if controller is not None else RectangleInteraction()
        self.panels = []  # Back to front; only data, never one controller per panel.
        self.active_id = None
        self.default_filter = "ORIGINAL"
        self._next_id = 1
        self._pinches = {}
        self.notice = ""
        self.creation_mode = False
        self.tool = "SELECT"
        self.submenu = None
        self._edit_start = None
        self._delay_start = None
        self.history = TemporalHistory()
        self._frame_time = 0.0
        self.adjusting_delay = False
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
        panel = self.active_panel
        return panel.content_mode if panel is not None and not self.creation_mode else "LIVE"

    @property
    def can_delay(self):
        return self.can_delete and self.active_panel.content_mode != "FROZEN"

    @property
    def can_adjust_delay(self):
        return (self.can_delete and self.content_mode == "DELAYED"
                and self.controller.can_start_manipulation)

    @property
    def fist_enabled(self):
        return (self.toolbar_enabled and self.tool == "SELECT" and self.submenu is None
                and self.controller.can_start_manipulation and self.active_panel is not None)

    def switch_tool(self, tool):
        if tool not in ("SELECT", "MOVE", "RESIZE") or not self.toolbar_enabled:
            return False
        if tool != "SELECT" and self.active_panel is None:
            return False
        self.tool = tool
        self.submenu = None
        self.require_release()
        self.notice = "Release both hands to use the tool."
        return True

    def cancel_edit(self):
        if self.adjusting_delay:
            if self.active_panel is not None:
                self.active_panel.delay_seconds = self._delay_start
            self.adjusting_delay = False
        elif self._edit_start is not None:
            self.controller.rectangle = self._edit_start
            self._store_active()
        elif self.tool == "SELECT":
            return False
        self._edit_start = None
        self.tool = "SELECT"
        self.submenu = None
        self.require_release()
        self.notice = "Edit canceled. Release both hands."
        return True

    def begin_delay_adjustment(self):
        if not self.can_adjust_delay:
            return False
        self.adjusting_delay = True
        self._delay_start = self.active_panel.delay_seconds
        self.notice = "Adjusting delay. Release the controlling pinch to finish."
        return True

    def set_delay(self, seconds):
        if (self.active_panel is None or self.content_mode != "DELAYED"
                or not (self.can_adjust_delay or self.adjusting_delay)):
            return False
        self.active_panel.delay_seconds = quantize_delay(seconds)
        return True

    def end_delay_adjustment(self):
        if self.adjusting_delay:
            self.adjusting_delay = False
            self.require_release()
            self.notice = "Delay adjusted. Release both hands to resume."

    def record_frame(self, raw_frame, now=None):
        """Called once per live input, before inference, effects, or overlays."""
        self._frame_time = monotonic() if now is None else now
        self.history.record(raw_frame, self._frame_time)
        if (self.notice.startswith("Buffering...")
                and self.active_panel is not None
                and self.history.delayed_frame(self._frame_time, self.active_panel.delay_seconds) is not None):
            self.notice = ""

    @property
    def selected_filter(self):
        if not self.creation_mode and self.active_panel is not None:
            return self.active_panel.filter_name
        return self.default_filter

    @property
    def operation_active(self):
        return self.creation_mode or self.adjusting_delay or self.state in ("DRAGGING", "RESIZING")

    @property
    def toolbar_enabled(self):
        return not self.operation_active and self.state in ("READY", "PLACED")

    @property
    def can_new(self):
        return self.toolbar_enabled and not self.creation_mode and len(self.panels) < MAX_PANELS

    @property
    def can_delete(self):
        return self.toolbar_enabled and not self.creation_mode and self.active_panel is not None

    @property
    def status_text(self):
        target = "NEW" if self.creation_mode else f"ACTIVE #{self.active_id}"
        return f"Panels: {len(self.panels)}/{MAX_PANELS} | {target} | {self.tool} | {self.state.replace('_', ' ')}"

    @property
    def instructions(self):
        if self.notice:
            return self.notice
        if self.creation_mode and self.panels:
            return "Pinch both hands, move, release either. Esc: cancel."
        if self.state == "WAITING_FOR_RELEASE" or not self.controller.can_start_manipulation and self.active_panel:
            return "Release visible hands to resume."
        if self.creation_mode:
            return "Pinch both hands, move, then release either to create."
        if self.active_panel is None:
            return "Choose New / N to create a panel. H: help."
        if self.submenu == "EFFECTS":
            return "Choose an effect for the active panel."
        if self.submenu == "TIME":
            if self.content_mode == "FROZEN":
                return "Unfreeze before changing the delay."
            if self.content_mode == "LIVE":
                return "Toggle Delay to show historical video."
            return "Pinch the slider to adjust the rolling delay."
        return {"SELECT": "Fresh pinch on a panel to select it.",
                "MOVE": "Fresh pinch inside the active panel to move it.",
                "RESIZE": "Pinch diagonally opposite active handles."}[self.tool]

    def _commit_creation(self):
        panel = Panel(self._next_id, self.rectangle, self.default_filter, self.controller.frozen_image)
        self._next_id += 1
        self.panels.append(panel)
        self.active_id = panel.panel_id
        self.creation_mode = False
        self.tool = "SELECT"
        self.submenu = None
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
            self.creation_mode = False
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

    def suspend_for_help(self):
        """Discard a draft, or stop movement at the latest committed geometry."""
        if not self.creation_mode:
            self._store_active()
        self.adjusting_delay = False
        self.creation_mode = False
        self.tool = "SELECT"
        self.submenu = None
        self._edit_start = None
        self._load_active(require_release=True)
        self._pinches = {}
        self.notice = "Release both hands to resume. H: help."

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
        self.tool = "CREATE"
        self.submenu = None
        self.controller.reset()
        self._pinches = {}
        self.notice = "Release both hands to create. Esc: cancel."
        return True

    def cancel_creation(self):
        if not self.creation_mode or not self.panels:
            return False
        self.creation_mode = False
        self.tool = "SELECT"
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
        self.creation_mode = False
        self.tool = "SELECT"
        self.submenu = None
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
        if action == "NOOP":
            return False
        if action == "NEW":
            return self.begin_creation()
        if action == "DELETE":
            return self.delete_active()
        if action in ("SELECT", "MOVE", "RESIZE"):
            return self.switch_tool(action)
        if action in ("EFFECTS", "TIME"):
            if self.active_panel is None:
                return False
            self.submenu = None if self.submenu == action else action
            self.require_release()
            return True
        if action == "FREEZE":
            return self.active_panel is not None
        if action == "DELAY":
            if not self.can_delay:
                self.notice = ("Unfreeze the active panel first." if self.active_panel
                               else "Select a placed panel first.")
                self.require_release()
                return False
            panel = self.active_panel
            panel.source_mode = "LIVE" if panel.source_mode == "DELAYED" else "DELAYED"
            self.require_release()
            self.notice = f"Content: {panel.content_mode}. Release both hands."
            return True
        return self.select_filter(action)

    def reset(self):
        """R is clear-all. IDs and the default for future panels are not reset."""
        self.panels.clear()
        self.active_id = None
        self.creation_mode = False
        self.tool = "SELECT"
        self.submenu = None
        self._edit_start = None
        self.notice = "All panels cleared. Release both hands."
        self._pinches = {}
        self.controller.reset()
        self.adjusting_delay = False

    def observe_pinches(self, hands):
        self._pinches = {hand.track_id: hand.is_pinching for hand in hands}
        self.controller.observe_pinches(hands)

    def update(self, hands, frame_width, frame_height):
        if self.adjusting_delay:
            return
        previous = self._pinches
        self._pinches = {hand.track_id: hand.is_pinching for hand in hands}
        if self.creation_mode:
            old_state = self.state
            self.controller.update(hands, frame_width, frame_height)
            if self.state == "PLACED" and self.rectangle is not None:
                self._commit_creation()
                self.require_release()
            elif old_state == "CREATING" and self.state == "WAITING_FOR_RELEASE":
                self.notice = "Creation failed. Release both hands to retry; Esc cancels."
            elif old_state == "WAITING_FOR_RELEASE" and self.state == "READY":
                self.notice = ""
            return

        if not self.controller.can_start_manipulation:
            was_editing = self.state in ("DRAGGING", "RESIZING")
            lost = ((self.state == "DRAGGING" and self.controller._drag_hand_id not in self._pinches)
                    or (self.state == "RESIZING" and not self.controller._resize_hands.keys() <= self._pinches.keys()))
            if self.state == "DRAGGING":
                self.controller._update_drag(hands, frame_width, frame_height, allow_resize=False)
            elif self.state != "READY":
                self.controller.update(hands, frame_width, frame_height)
            self._store_active()
            if was_editing and self.state not in ("DRAGGING", "RESIZING"):
                self._edit_start = None
                self.notice = ""
            if self.state in ("PLACED", "READY"):
                self.notice = ""
                self._edit_start = None
            if lost:
                self.require_release()
                self.notice = "Tracking lost. Release both hands to resume."
            return
        self.controller.observe_pinches(hands)
        if self.submenu is not None:
            return
        if self.tool == "RESIZE":
            start = replace(self.rectangle)
            fresh = any(hand.is_pinching and previous.get(hand.track_id) is False for hand in hands)
            if fresh and self.controller.try_resize(hands):
                self._edit_start = start
                self.notice = "Release to finish resizing. Esc: cancel."
            return

        candidates = []
        for hand in hands:
            if not hand.is_pinching or previous.get(hand.track_id) is not False:
                continue
            if self.tool == "SELECT":
                hit = next((panel for panel in reversed(self.panels)
                            if panel.rectangle.contains(hand.pinch_point)), None)
            else:
                hit = self.active_panel
                if hit is not None and not hit.rectangle.contains(hand.pinch_point):
                    hit = None
            if hit is not None:
                candidates.append((hand.track_id, hit, hand))
        if candidates:
            _, selected, hand = min(candidates, key=lambda item: item[0])
            if self.tool == "SELECT":
                self.panels.remove(selected)
                self.panels.append(selected)
                self.active_id = selected.panel_id
                self._load_active()
                self.require_release()
                self.notice = "Panel selected. Release both hands."
            elif self.tool == "MOVE":
                self._edit_start = replace(self.rectangle)
                self.controller.begin_drag(hand)
                self.notice = "Release to finish moving. Esc: cancel."

    def toggle_frozen(self, raw_frame):
        if (self.adjusting_delay or self.creation_mode
                or self.active_panel is None or self.state != "PLACED"):
            return False
        panel = self.active_panel
        if panel.content_mode == "DELAYED":
            source = self.history.delayed_crop(
                self.rectangle, (raw_frame.shape[1], raw_frame.shape[0]),
                self._frame_time, panel.delay_seconds)
            if source is None:
                self.notice = "Buffering... Cannot freeze delayed content yet."
                return False
            self.controller.frozen_image = source.copy()
            changed = True
        else:
            changed = self.controller.toggle_frozen(raw_frame)
        self._store_active()
        if changed and self.notice.startswith("Buffering..."):
            self.notice = ""
        return changed

    def hover_target(self, point):
        """Return an eligible panel and optional handle for the visual pointer."""
        if not self.toolbar_enabled or not self.controller.can_start_manipulation or self.submenu:
            return None
        if self.tool == "SELECT":
            panel = next((panel for panel in reversed(self.panels) if panel.rectangle.contains(point)), None)
            return (panel.panel_id, None) if panel else None
        panel = self.active_panel
        if panel is None:
            return None
        if self.tool == "MOVE" and panel.rectangle.contains(point):
            return panel.panel_id, None
        if self.tool == "RESIZE":
            from math import dist
            from interaction import RESIZE_HIT_RADIUS_PIXELS
            corners = panel.rectangle.corner_points()
            name = min(corners, key=lambda name: dist(corners[name], point))
            if dist(corners[name], point) <= RESIZE_HIT_RADIUS_PIXELS:
                return panel.panel_id, name
        return None

    def composite(self, raw_frame, display_frame):
        invalid = []
        for panel in self.panels:
            source = panel.frozen_image
            buffering = False
            if panel.content_mode == "DELAYED":
                source = self.history.delayed_crop(
                    panel.rectangle, (raw_frame.shape[1], raw_frame.shape[0]),
                    self._frame_time, panel.delay_seconds)
                buffering = source is None
                if buffering:
                    source = np.full((1, 1, 3), (29, 25, 23), dtype=np.uint8)
            if not composite_panel_pixels(panel.rectangle, source, raw_frame,
                                          display_frame, "ORIGINAL" if buffering else panel.filter_name):
                invalid.append(panel)
            elif buffering:
                draw_buffering(display_frame, panel.rectangle)
        for panel in invalid:
            self.panels.remove(panel)
        if invalid:
            if self.active_panel is None:
                self.active_id = self.panels[-1].panel_id if self.panels else None
                self.creation_mode = False
                self._load_active(require_release=True)
        if self.creation_mode:
            self.controller.composite_panel(raw_frame, display_frame, self.default_filter)

    def prepare_camera_reconnect(self):
        self.adjusting_delay = False
        self.history.clear()
        if not self.creation_mode:
            self._store_active()
        self.creation_mode = False
        self.tool = "SELECT"
        self.submenu = None
        self._edit_start = None
        self._load_active(require_release=True)
        self._pinches = {}
        self.notice = "Camera recovering. Release both hands after reconnecting."

    def finish_camera_reconnect(self, previous_size, current_size):
        self.history.clear()
        if previous_size != current_size:
            self.reset()
            self.notice = "Frame size changed; panels cleared. Release both hands."
