"""State and pixel geometry for one gesture-controlled rectangle."""

from dataclasses import dataclass
from math import dist


MIN_RECTANGLE_SIZE_PIXELS = 40.0
POSITION_SMOOTHING = 0.35  # 1.0 follows each new position without smoothing.
DRAG_SMOOTHING = 0.35  # Smooth position only; the placed size never changes.
RESIZE_SMOOTHING = 0.35
RESIZE_HIT_RADIUS_PIXELS = 28.0
DIAGONAL_CORNERS = (("top_left", "bottom_right"), ("top_right", "bottom_left"))


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

    def corner_points(self):
        return {"top_left": (self.left, self.top), "top_right": (self.right, self.top),
                "bottom_left": (self.left, self.bottom), "bottom_right": (self.right, self.bottom)}

    def pixel_size(self):
        # Ignore tiny floating-point drift from translation before choosing pixels.
        return round(round(self.width, 6)), round(round(self.height, 6))

    def moved_to(self, left, top, frame_width, frame_height):
        """Translate a rectangle that fits in the frame without changing its size."""
        left = max(0.0, min(frame_width - 1.0 - self.width, left))
        top = max(0.0, min(frame_height - 1.0 - self.height, top))
        return Rectangle(left, top, left + self.width, top + self.height)


class RectangleInteraction:
    """Create, drag, and resize one rectangle using tracked pinch pointers."""

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
            "PLACED": "Pinch: drag | Opposite corners: resize | R: clear",
            "DRAGGING": "Release to drop; two corner pinches resize.",
            "RESIZING": "Move both corner pinches; release either to finish.",
            "WAITING_FOR_RELEASE": "Show both hands OPEN to rearm.",
        }[self.state]

    @property
    def content_mode(self):
        return "FROZEN" if self.frozen_image is not None else "LIVE"

    def toggle_frozen(self, raw_frame):
        """Capture only raw BGR pixels, or release the existing in-memory crop."""
        if self.state != "PLACED" or self.rectangle is None:
            return False
        if self.frozen_image is not None:
            self.frozen_image = None
            return True

        box = self.rectangle
        left, top = round(box.left), round(box.top)
        # Round the size once, independently of position, so fractional dragging
        # cannot change the captured image's pixel dimensions.
        width, height = box.pixel_size()
        frame_height, frame_width = raw_frame.shape[:2]
        if (width < 1 or height < 1 or left < 0 or top < 0
                or left + width > frame_width or top + height > frame_height):
            return False
        self.frozen_image = raw_frame[top:top + height, left:left + width].copy()
        return True

    def composite_frozen(self, display_frame):
        """Render from the original crop, scaling only for the current geometry."""
        if self.rectangle is None or self.frozen_image is None:
            return
        left, top = round(self.rectangle.left), round(self.rectangle.top)
        width, height = self.rectangle.pixel_size()
        frame_height, frame_width = display_frame.shape[:2]
        if (width < 1 or height < 1 or left < 0 or top < 0 or left + width > frame_width
                or top + height > frame_height):
            self.reset()
            return
        image = self.frozen_image
        if image.shape[:2] != (height, width):
            # Only image rendering needs the already installed OpenCV package.
            import cv2

            image = cv2.resize(self.frozen_image, (width, height), interpolation=cv2.INTER_LINEAR)
        display_frame[top:top + height, left:left + width] = image

    def reset(self):
        """Clear geometry and block creation until both hands are seen released."""
        self.rectangle = None
        self.frozen_image = None
        self._active_ids = ()
        self._corners = {}
        self._pinch_states = {}
        self._drag_hand_id = None
        self._grab_offset = None
        self._drag_position = None
        self._grab_release_required = False
        self._resize_hands = {}
        self.state = "WAITING_FOR_RELEASE"

    def prepare_camera_reconnect(self):
        """Cancel unfinished work, retaining only a placed rectangle provisionally."""
        if self.state in ("PLACED", "DRAGGING", "RESIZING", "WAITING_FOR_RELEASE"):
            self._wait_for_both_releases()
        else:
            self.reset()

    def _wait_for_both_releases(self):
        placed, frozen = self.rectangle, self.frozen_image
        self.reset()
        self.rectangle = placed
        self.frozen_image = frozen

    def finish_camera_reconnect(self, previous_size, current_size):
        """Discard saved geometry if the recovered frame has different dimensions."""
        if previous_size != current_size:
            self.reset()

    def update(self, hands, frame_width, frame_height):
        """Use gesture IDs, pinch states, and thumb/index midpoints from this frame."""
        previous_pinches = self._pinch_states
        # Forget missing IDs. A new/reappearing pinched hand has no OPEN history.
        self._pinch_states = {hand.track_id: hand.is_pinching for hand in hands}

        if self.state == "RESIZING":
            self._update_resize(hands, frame_width, frame_height)
            return

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

            if self._try_start_resize(hands):
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

        # Upgrade before applying drag movement, preserving the displayed box.
        if self._try_start_resize(hands):
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

    def _try_start_resize(self, hands):
        if len(hands) != 2 or not all(hand.is_pinching for hand in hands):
            return False
        first, second = sorted(hands, key=lambda hand: hand.track_id)
        if first.track_id == second.track_id:
            return False
        corners = self.rectangle.corner_points()
        best = None
        best_distance = float("inf")
        for first_role, second_role in DIAGONAL_CORNERS:
            for roles in ((first_role, second_role), (second_role, first_role)):
                distances = [dist(hand.pinch_point, corners[role])
                             for hand, role in zip((first, second), roles)]
                if max(distances) <= RESIZE_HIT_RADIUS_PIXELS and sum(distances) < best_distance:
                    best_distance = sum(distances)
                    best = roles
        if best is None:
            return False

        self._resize_hands = {}
        for hand, role in zip((first, second), best):
            corner = corners[role]
            offset = (corner[0] - hand.pinch_point[0], corner[1] - hand.pinch_point[1])
            self._resize_hands[hand.track_id] = (role, offset)
        self._drag_hand_id = None
        self._grab_offset = None
        self._drag_position = None
        self.state = "RESIZING"
        return True

    @staticmethod
    def _resize_axis(first, second, limit):
        first, second = max(0.0, min(limit, first)), max(0.0, min(limit, second))
        if second - first < MIN_RECTANGLE_SIZE_PIXELS:
            # Roles stay fixed when pointers cross: stop at minimum size, never flip.
            half = MIN_RECTANGLE_SIZE_PIXELS / 2
            center = max(half, min(limit - half, (first + second) / 2))
            first, second = center - half, center + half
        return first, second

    def _update_resize(self, hands, frame_width, frame_height):
        by_id = {hand.track_id: hand for hand in hands}
        if (not self._resize_hands.keys() <= by_id.keys()
                or not all(by_id[track_id].is_pinching for track_id in self._resize_hands)):
            # Keep the last valid box/image and require both hands released. No
            # direct fallback to dragging, even if one pinch is still held.
            self._wait_for_both_releases()
            return
        if not self._keep_placed_in_bounds(frame_width, frame_height):
            return

        edges = {}
        for track_id, (role, offset) in self._resize_hands.items():
            point = by_id[track_id].pinch_point
            vertical, horizontal = role.split("_")
            edges[horizontal] = point[0] + offset[0]
            edges[vertical] = point[1] + offset[1]
        left, right = self._resize_axis(edges["left"], edges["right"], frame_width - 1)
        top, bottom = self._resize_axis(edges["top"], edges["bottom"], frame_height - 1)
        old = self.rectangle
        self.rectangle = Rectangle(
            old.left + RESIZE_SMOOTHING * (left - old.left),
            old.top + RESIZE_SMOOTHING * (top - old.top),
            old.right + RESIZE_SMOOTHING * (right - old.right),
            old.bottom + RESIZE_SMOOTHING * (bottom - old.bottom),
        )
