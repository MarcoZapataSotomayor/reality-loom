"""State and pixel geometry for one gesture-controlled rectangle."""

from dataclasses import dataclass


MIN_RECTANGLE_SIZE_PIXELS = 40.0
POSITION_SMOOTHING = 0.35  # 1.0 follows each new position without smoothing.
DRAG_SMOOTHING = 0.35  # Smooth position only; the placed size never changes.


def clamp_point(point, frame_width, frame_height):
    """Keep a corner inside the image's pixel bounds."""
    return (
        max(0.0, min(frame_width - 1.0, point[0])),
        max(0.0, min(frame_height - 1.0, point[1])),
    )


@dataclass
class Rectangle:
    """Sorted pixel coordinates, independent of which hand is on the left."""

    left: float
    top: float
    right: float
    bottom: float

    @classmethod
    def from_corners(cls, first, second, frame_width, frame_height):
        first = clamp_point(first, frame_width, frame_height)
        second = clamp_point(second, frame_width, frame_height)
        left, right = sorted((first[0], second[0]))
        top, bottom = sorted((first[1], second[1]))
        return cls(left, top, right, bottom)

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top

    def meets_minimum_size(self):
        return (self.width >= MIN_RECTANGLE_SIZE_PIXELS
                and self.height >= MIN_RECTANGLE_SIZE_PIXELS)

    def contains(self, point):
        return self.left <= point[0] <= self.right and self.top <= point[1] <= self.bottom

    def moved_to(self, left, top, frame_width, frame_height):
        """Translate a rectangle that fits in the frame without changing its size."""
        left = max(0.0, min(frame_width - 1.0 - self.width, left))
        top = max(0.0, min(frame_height - 1.0 - self.height, top))
        return Rectangle(left, top, left + self.width, top + self.height)


class RectangleInteraction:
    """Create with two pinches and move the placed rectangle with one fresh grab."""

    def __init__(self):
        self.reset()
        self.state = "READY"

    @property
    def instructions(self):
        if self.state == "PLACED" and self._grab_release_required:
            return "Open visible hands before another grab. R: clear."
        return {
            "READY": "Pinch both hands to create a rectangle.",
            "CREATING": "Move both pinched hands; release either to place.",
            "PLACED": "Pinch inside to drag. R: clear.",
            "DRAGGING": "Move pinched hand; release to drop. R: clear.",
            "WAITING_FOR_RELEASE": "Show both hands OPEN to rearm.",
        }[self.state]

    def reset(self):
        """Clear geometry and block creation until both hands are seen released."""
        self.rectangle = None
        self._active_ids = ()
        self._corners = {}
        self._pinch_states = {}
        self._drag_hand_id = None
        self._grab_offset = None
        self._drag_position = None
        self._grab_release_required = False
        self.state = "WAITING_FOR_RELEASE"

    def prepare_camera_reconnect(self):
        """Cancel unfinished work, retaining only a placed rectangle provisionally."""
        placed = self.rectangle if self.state in ("PLACED", "DRAGGING", "WAITING_FOR_RELEASE") else None
        self.reset()
        self.rectangle = placed

    def finish_camera_reconnect(self, previous_size, current_size):
        """Discard saved geometry if the recovered frame has different dimensions."""
        if previous_size != current_size:
            self.reset()

    def update(self, hands, frame_width, frame_height):
        """Use gesture IDs, pinch states, and thumb/index midpoints from this frame."""
        previous_pinches = self._pinch_states
        # Forget missing IDs. A new/reappearing pinched hand has no OPEN history.
        self._pinch_states = {hand.track_id: hand.is_pinching for hand in hands}

        if self.state == "DRAGGING":
            self._update_drag(hands, frame_width, frame_height)
            return

        if self.state == "PLACED":
            if not self._keep_placed_in_bounds(frame_width, frame_height):
                return
            if self._grab_release_required:
                if hands and all(not hand.is_pinching for hand in hands):
                    self._grab_release_required = False
                return

            candidates = [
                hand for hand in hands
                if hand.is_pinching and previous_pinches.get(hand.track_id) is False
                and self.rectangle.contains(hand.pinch_point)
            ]
            if candidates:
                controller = min(candidates, key=lambda hand: hand.track_id)
                self._drag_hand_id = controller.track_id
                self._grab_offset = (controller.pinch_point[0] - self.rectangle.left,
                                     controller.pinch_point[1] - self.rectangle.top)
                # Reset smoothing at every grab; starting a drag must not move it.
                self._drag_position = (self.rectangle.left, self.rectangle.top)
                self.state = "DRAGGING"
            return

        if self.state == "WAITING_FOR_RELEASE":
            if len(hands) == 2 and all(not hand.is_pinching for hand in hands):
                self.state = "PLACED" if self.rectangle is not None else "READY"
            return

        if self.state == "READY":
            if len(hands) == 2 and all(hand.is_pinching for hand in hands):
                self._active_ids = tuple(hand.track_id for hand in hands)
                self._corners = {
                    hand.track_id: clamp_point(hand.pinch_point, frame_width, frame_height)
                    for hand in hands
                }
                self.state = "CREATING"
                self._update_rectangle(frame_width, frame_height)
            return

        hands_by_id = {hand.track_id: hand for hand in hands}
        if set(hands_by_id) != set(self._active_ids):
            # Check identity before release: a replacement must never place a box.
            self.reset()
            return

        if not all(hand.is_pinching for hand in hands):
            # Keep the last preview from when both pinches were active. Opening
            # fingers can move their midpoints, so do not use release positions.
            if self.rectangle.meets_minimum_size():
                self.state = "PLACED"
                self._active_ids = ()
                self._corners = {}
            else:
                self.reset()
            return

        for track_id in self._active_ids:
            target = clamp_point(hands_by_id[track_id].pinch_point, frame_width, frame_height)
            previous = self._corners[track_id]
            self._corners[track_id] = (
                previous[0] + POSITION_SMOOTHING * (target[0] - previous[0]),
                previous[1] + POSITION_SMOOTHING * (target[1] - previous[1]),
            )
        self._update_rectangle(frame_width, frame_height)

    def _update_rectangle(self, frame_width, frame_height):
        first, second = (self._corners[track_id] for track_id in self._active_ids)
        self.rectangle = Rectangle.from_corners(first, second, frame_width, frame_height)

    def _keep_placed_in_bounds(self, frame_width, frame_height):
        box = self.rectangle
        if box.width > frame_width - 1 or box.height > frame_height - 1:
            # A smaller frame cannot contain this size; clear rather than resize.
            self.reset()
            return False
        self.rectangle = box.moved_to(box.left, box.top, frame_width, frame_height)
        return True

    def _stop_drag(self, require_release=False):
        self.state = "PLACED"
        self._drag_hand_id = None
        self._grab_offset = None
        self._drag_position = None
        self._grab_release_required = require_release

    def _update_drag(self, hands, frame_width, frame_height):
        controller = next((hand for hand in hands if hand.track_id == self._drag_hand_id), None)
        if controller is None:
            self._stop_drag(require_release=True)
            return
        if not controller.is_pinching:
            # Opening fingers can shift the midpoint. Keep the last drag position.
            self._stop_drag()
            return
        if not self._keep_placed_in_bounds(frame_width, frame_height):
            return

        target = self.rectangle.moved_to(
            controller.pinch_point[0] - self._grab_offset[0],
            controller.pinch_point[1] - self._grab_offset[1],
            frame_width, frame_height,
        )
        left = self._drag_position[0] + DRAG_SMOOTHING * (target.left - self._drag_position[0])
        top = self._drag_position[1] + DRAG_SMOOTHING * (target.top - self._drag_position[1])
        self.rectangle = self.rectangle.moved_to(left, top, frame_width, frame_height)
        self._drag_position = (self.rectangle.left, self.rectangle.top)
