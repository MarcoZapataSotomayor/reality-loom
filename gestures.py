"""Calculate tracked hand poses and deliberate holds without camera dependencies."""

from dataclasses import dataclass
from itertools import product
from math import dist
import time


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

# All distances below are multiples of wrist-to-middle-knuckle palm size.
FINGER_PIP_TIPS = ((6, 8), (10, 12), (14, 16), (18, 20))
FIST_FINGER_TIP_MAX = 0.85
FIST_CURL_MARGIN = 0.10
FIST_THUMB_TIP_MAX = 0.85
OPEN_FINGER_EXTENSION_MIN = 0.25
OPEN_THUMB_EXTENSION_MIN = 0.20
FIST_HOLD_SECONDS = 0.8


def pixel_point(landmark, frame_width, frame_height):
    """Use both image dimensions so non-square frames do not distort distances."""
    return landmark.x * frame_width, landmark.y * frame_height


def classify_hand_pose(points, palm_center, palm_size):
    """Recognize folded fingers or a fully extended hand using pixel distances."""
    if palm_size < MIN_PALM_SIZE_PIXELS:
        return False, False
    wrist = points[WRIST]
    curled = all(
        dist(points[tip], palm_center) <= FIST_FINGER_TIP_MAX * palm_size
        and dist(points[tip], wrist) <= dist(points[pip], wrist) + FIST_CURL_MARGIN * palm_size
        for pip, tip in FINGER_PIP_TIPS
    )
    is_fist = curled and dist(points[THUMB_TIP], palm_center) <= FIST_THUMB_TIP_MAX * palm_size

    extended = all(
        dist(points[tip], wrist) >= dist(points[pip], wrist) + OPEN_FINGER_EXTENSION_MIN * palm_size
        for pip, tip in FINGER_PIP_TIPS
    )
    thumb_extended = (
        dist(points[THUMB_TIP], points[17])
        >= dist(points[2], points[17]) + OPEN_THUMB_EXTENSION_MIN * palm_size
    )
    is_open_hand = (extended and thumb_extended
                    and dist(points[THUMB_TIP], points[INDEX_TIP]) >= PINCH_OPEN_THRESHOLD * palm_size)
    return is_fist, is_open_hand


@dataclass
class HandGesture:
    """State for one hand, with position and size measured in pixels."""

    track_id: int
    center: tuple[float, float]
    palm_size: float
    pinch_ratio: float | None
    pinch_point: tuple[float, float]
    is_pinching: bool = False
    is_fist: bool = False
    is_open_hand: bool = False


class PinchDetector:
    """Match up to two hands between frames and apply pinch hysteresis."""

    def __init__(self):
        self._hands = {}
        self._next_id = 0

    def reset(self):
        """Forget associations and pinch states; future hands receive fresh IDs."""
        self._hands.clear()

    def update(self, hands, frame_width, frame_height):
        """Return states in the current result order, while retaining matched IDs."""
        current_hands = []
        for landmarks in hands:
            points = [pixel_point(landmark, frame_width, frame_height) for landmark in landmarks]
            wrist, middle = points[WRIST], points[MIDDLE_MCP]
            thumb, index = points[THUMB_TIP], points[INDEX_TIP]
            palm_size = dist(wrist, middle)
            center = ((wrist[0] + middle[0]) / 2, (wrist[1] + middle[1]) / 2)
            ratio = None
            if palm_size >= MIN_PALM_SIZE_PIXELS:
                ratio = dist(thumb, index) / palm_size
            pinch_point = ((thumb[0] + index[0]) / 2, (thumb[1] + index[1]) / 2)
            is_fist, is_open_hand = classify_hand_pose(points, center, palm_size)
            current_hands.append(HandGesture(-1, center, palm_size, ratio, pinch_point,
                                             is_fist=is_fist, is_open_hand=is_open_hand))

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


@dataclass
class FistHoldState:
    armed: bool = False
    started_at: float | None = None


class FistHoldDetector:
    """Track holds by hand ID; only a full open hand can arm or rearm them."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._hands = {}
        self.message = "Fist: open hand to arm."

    def update(self, hands, rectangle, enabled, now=None):
        now = time.monotonic() if now is None else now
        enabled = enabled and rectangle is not None
        current = {}
        triggered = False
        longest_hold = 0.0
        holding = False
        for hand in hands:
            state = self._hands.get(hand.track_id, FistHoldState())
            current[hand.track_id] = state
            if not enabled:
                state.armed = False
                state.started_at = None
            elif hand.is_open_hand:
                state.armed = True
                state.started_at = None
            elif state.armed and hand.is_fist and not rectangle.contains(hand.center):
                if state.started_at is None:
                    state.started_at = now
                elapsed = max(0.0, now - state.started_at)
                longest_hold = max(longest_hold, elapsed)
                holding = True
                triggered = triggered or elapsed >= FIST_HOLD_SECONDS
            else:
                state.started_at = None

        # Missing/replaced tracks lose their progress and need a new OPEN pose.
        self._hands = current
        if triggered:
            # Consume all current fist holds, preventing a second hand from
            # immediately undoing the same activation. Each must open to rearm.
            for state in current.values():
                if state.started_at is not None:
                    state.armed = False
                    state.started_at = None
            self.message = "Fist activated; open hand to rearm."
        elif not enabled:
            self.message = "Fist: available only while PLACED."
        elif holding:
            self.message = f"Fist hold: {min(longest_hold, FIST_HOLD_SECONDS):.1f} / {FIST_HOLD_SECONDS:.1f} s"
        elif any(state.armed for state in current.values()):
            self.message = "Fist: hold outside the rectangle."
        else:
            self.message = "Fist: open hand fully to arm."
        return triggered
