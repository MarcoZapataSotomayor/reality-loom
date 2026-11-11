"""Calculate pinch states without depending on OpenCV or MediaPipe."""

from dataclasses import dataclass
from itertools import product
from math import dist


WRIST = 0
THUMB_TIP = 4
INDEX_TIP = 8
MIDDLE_MCP = 9

# Ratios of thumb/index distance to wrist/middle-knuckle distance.
PINCH_CLOSE_THRESHOLD = 0.30
PINCH_OPEN_THRESHOLD = 0.45
MIN_PALM_SIZE_PIXELS = 1.0

# Maximum movement between frames, measured in palm lengths.
MAX_HAND_MATCH_DISTANCE = 2.0


def pixel_point(landmark, frame_width, frame_height):
    """Use both image dimensions so non-square frames do not distort distances."""
    return landmark.x * frame_width, landmark.y * frame_height


@dataclass
class HandGesture:
    """State for one hand, with position and size measured in pixels."""

    track_id: int
    center: tuple[float, float]
    palm_size: float
    pinch_ratio: float | None
    is_pinching: bool = False


class PinchDetector:
    """Match up to two hands between frames and apply pinch hysteresis."""

    def __init__(self):
        self._hands = {}
        self._next_id = 0

    def update(self, hands, frame_width, frame_height):
        """Return states in the current result order, while retaining matched IDs."""
        current_hands = []
        for landmarks in hands:
            wrist = pixel_point(landmarks[WRIST], frame_width, frame_height)
            middle = pixel_point(landmarks[MIDDLE_MCP], frame_width, frame_height)
            thumb = pixel_point(landmarks[THUMB_TIP], frame_width, frame_height)
            index = pixel_point(landmarks[INDEX_TIP], frame_width, frame_height)
            palm_size = dist(wrist, middle)
            center = ((wrist[0] + middle[0]) / 2, (wrist[1] + middle[1]) / 2)
            ratio = None
            if palm_size >= MIN_PALM_SIZE_PIXELS:
                ratio = dist(thumb, index) / palm_size
            current_hands.append(HandGesture(-1, center, palm_size, ratio))

        matches = self._match_hands(current_hands)
        for hand, previous_id in zip(current_hands, matches):
            previous = self._hands.get(previous_id)
            if previous is None:
                hand.track_id = self._next_id
                self._next_id += 1
            else:
                hand.track_id = previous.track_id
                hand.is_pinching = previous.is_pinching

            if hand.pinch_ratio is None:
                # A collapsed palm cannot provide a reliable scale; reset safely.
                hand.is_pinching = False
            elif hand.is_pinching:
                hand.is_pinching = hand.pinch_ratio < PINCH_OPEN_THRESHOLD
            else:
                hand.is_pinching = hand.pinch_ratio <= PINCH_CLOSE_THRESHOLD

        # Only hands seen in this frame survive. Missing hands lose all state.
        self._hands = {hand.track_id: hand for hand in current_hands}
        return current_hands

    def _match_hands(self, current_hands):
        """Prefer the most valid matches, then the smallest total palm movement."""
        best_matches = (None,) * len(current_hands)
        best_score = (0, float("inf"))

        # With at most two hands there are at most nine combinations. None means
        # a new hand. Trying them all avoids a greedy match stealing another hand.
        choices = [None, *self._hands]
        for matches in product(choices, repeat=len(current_hands)):
            used_ids = [track_id for track_id in matches if track_id is not None]
            if len(set(used_ids)) != len(used_ids):
                continue

            total_distance = 0.0
            valid = True
            for hand, previous_id in zip(current_hands, matches):
                if previous_id is None:
                    continue
                previous = self._hands[previous_id]
                scale = max(hand.palm_size, previous.palm_size, MIN_PALM_SIZE_PIXELS)
                distance = dist(hand.center, previous.center) / scale
                if distance > MAX_HAND_MATCH_DISTANCE:
                    valid = False
                    break
                total_distance += distance

            score = (-len(used_ids), total_distance)
            if valid and score < best_score:
                best_score = score
                best_matches = matches

        return best_matches
