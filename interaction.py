"""State and pixel geometry for one gesture-controlled rectangle."""

from dataclasses import dataclass


MIN_RECTANGLE_SIZE_PIXELS = 40.0
POSITION_SMOOTHING = 0.35  # 1.0 follows each new position without smoothing.


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


class RectangleInteraction:
    """Create once with two pinches; placement is locked until R resets it."""

    def __init__(self):
        self.state = "READY"
        self.rectangle = None
        self._active_ids = ()
        self._corners = {}

    @property
    def instructions(self):
        return {
            "READY": "Pinch both hands to create a rectangle.",
            "CREATING": "Move both pinched hands; release either to place.",
            "PLACED": "Press R to clear the rectangle.",
            "WAITING_FOR_RELEASE": "Show both hands OPEN to rearm.",
        }[self.state]

    def reset(self):
        """Clear geometry and block creation until both hands are seen released."""
        self.rectangle = None
        self._active_ids = ()
        self._corners = {}
        self.state = "WAITING_FOR_RELEASE"

    def update(self, hands, frame_width, frame_height):
        """Use gesture IDs, pinch states, and thumb/index midpoints from this frame."""
        if self.state == "PLACED":
            # Keep placement inside the image if the camera frame size changes.
            box = self.rectangle
            self.rectangle = Rectangle.from_corners(
                (box.left, box.top), (box.right, box.bottom), frame_width, frame_height
            )
            return

        if self.state == "WAITING_FOR_RELEASE":
            if len(hands) == 2 and all(not hand.is_pinching for hand in hands):
                self.state = "READY"
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
