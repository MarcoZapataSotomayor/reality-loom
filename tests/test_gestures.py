"""Camera-independent gesture checks using synthetic normalized landmarks."""

from types import SimpleNamespace
import unittest

from gestures import (
    INDEX_TIP,
    MIDDLE_MCP,
    PINCH_CLOSE_THRESHOLD,
    PINCH_OPEN_THRESHOLD,
    THUMB_TIP,
    WRIST,
    PinchDetector,
)


WIDTH = 1280
HEIGHT = 720
BETWEEN_THRESHOLDS = (PINCH_CLOSE_THRESHOLD + PINCH_OPEN_THRESHOLD) / 2


def make_hand(ratio, center=(320, 360), palm_size=100, width=WIDTH, height=HEIGHT):
    """Build landmarks from pixel geometry, including a diagonal fingertip gap."""
    x, y = center
    points = [SimpleNamespace(x=x / width, y=y / height) for _ in range(21)]
    points[WRIST] = SimpleNamespace(x=x / width, y=(y + palm_size / 2) / height)
    points[MIDDLE_MCP] = SimpleNamespace(x=x / width, y=(y - palm_size / 2) / height)
    points[THUMB_TIP] = SimpleNamespace(x=x / width, y=y / height)
    points[INDEX_TIP] = SimpleNamespace(
        x=(x + 0.6 * ratio * palm_size) / width,
        y=(y + 0.8 * ratio * palm_size) / height,
    )
    return points


class PinchDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = PinchDetector()

    def state_for(self, ratio):
        return self.detector.update([make_hand(ratio)], WIDTH, HEIGHT)[0]

    def test_pinch_activation_and_release(self):
        self.assertFalse(self.state_for(0.8).is_pinching)
        self.assertTrue(self.state_for(PINCH_CLOSE_THRESHOLD - 0.01).is_pinching)
        self.assertFalse(self.state_for(PINCH_OPEN_THRESHOLD + 0.01).is_pinching)

    def test_pinch_midpoint_is_in_image_pixels(self):
        state = self.state_for(0.2)
        self.assertAlmostEqual(state.pinch_point[0], 326)
        self.assertAlmostEqual(state.pinch_point[1], 368)

    def test_hysteresis_retains_previous_state_between_thresholds(self):
        for ratio in (BETWEEN_THRESHOLDS, PINCH_CLOSE_THRESHOLD + 0.01):
            self.assertFalse(self.state_for(ratio).is_pinching)
        self.assertTrue(self.state_for(PINCH_CLOSE_THRESHOLD - 0.01).is_pinching)
        for ratio in (BETWEEN_THRESHOLDS, PINCH_OPEN_THRESHOLD - 0.01,
                      PINCH_CLOSE_THRESHOLD + 0.01):
            self.assertTrue(self.state_for(ratio).is_pinching)
        self.assertFalse(self.state_for(PINCH_OPEN_THRESHOLD + 0.01).is_pinching)
        self.assertFalse(self.state_for(PINCH_OPEN_THRESHOLD - 0.01).is_pinching)

    def test_equivalent_gestures_at_different_image_and_hand_scales(self):
        for width, height in ((1280, 720), (640, 360), (720, 1280)):
            for palm_size in (25, 50, 100):
                with self.subTest(size=(width, height), palm_size=palm_size):
                    detector = PinchDetector()
                    for ratio, expected in ((0.2, True), (BETWEEN_THRESHOLDS, True),
                                            (0.6, False), (BETWEEN_THRESHOLDS, False)):
                        hand = make_hand(ratio, center=(width / 2, height / 2),
                                         palm_size=palm_size, width=width, height=height)
                        state = detector.update([hand], width, height)[0]
                        self.assertAlmostEqual(state.pinch_ratio, ratio)
                        self.assertEqual(state.is_pinching, expected)

    def test_hands_keep_independent_states_when_results_reorder(self):
        left, right = (320, 360), (900, 360)
        first = self.detector.update([make_hand(0.2, left), make_hand(0.8, right)], WIDTH, HEIGHT)
        second = self.detector.update(
            [make_hand(BETWEEN_THRESHOLDS, (890, 365)),
             make_hand(BETWEEN_THRESHOLDS, (330, 365))], WIDTH, HEIGHT,
        )
        self.assertEqual([hand.track_id for hand in second], [first[1].track_id, first[0].track_id])
        self.assertEqual([hand.is_pinching for hand in second], [False, True])

    def test_missing_hand_resets_state(self):
        first = self.state_for(0.2)
        self.assertEqual(self.detector.update([], WIDTH, HEIGHT), [])
        returned = self.state_for(BETWEEN_THRESHOLDS)
        self.assertNotEqual(returned.track_id, first.track_id)
        self.assertFalse(returned.is_pinching)

    def test_explicit_reset_forgets_pinch_and_association(self):
        first = self.state_for(0.2)
        self.detector.reset()
        returned = self.state_for(BETWEEN_THRESHOLDS)
        self.assertNotEqual(returned.track_id, first.track_id)
        self.assertFalse(returned.is_pinching)

    def test_matching_considers_both_hands_together(self):
        first = self.detector.update(
            [make_hand(0.2, (300, 360)), make_hand(0.8, (460, 360))], WIDTH, HEIGHT,
        )
        # The first new position is closer to the second old hand, but the last
        # position is too far from the first old hand. Both can still be matched.
        moved = self.detector.update(
            [make_hand(BETWEEN_THRESHOLDS, (430, 360)),
             make_hand(BETWEEN_THRESHOLDS, (550, 360))], WIDTH, HEIGHT,
        )
        self.assertEqual([hand.track_id for hand in moved], [hand.track_id for hand in first])
        self.assertEqual([hand.is_pinching for hand in moved], [True, False])

    def test_one_missing_hand_does_not_reset_the_other(self):
        left, right = (320, 360), (900, 360)
        first = self.detector.update([make_hand(0.2, left), make_hand(0.2, right)], WIDTH, HEIGHT)
        remaining = self.detector.update([make_hand(BETWEEN_THRESHOLDS, right)], WIDTH, HEIGHT)
        self.assertEqual(remaining[0].track_id, first[1].track_id)
        self.assertTrue(remaining[0].is_pinching)
        returned = self.detector.update(
            [make_hand(BETWEEN_THRESHOLDS, left), make_hand(BETWEEN_THRESHOLDS, right)],
            WIDTH, HEIGHT,
        )
        self.assertNotEqual(returned[0].track_id, first[0].track_id)
        self.assertEqual([hand.is_pinching for hand in returned], [False, True])

    def test_degenerate_palm_resets_without_dividing_by_zero(self):
        for palm_size in (0, 1e-9):
            with self.subTest(palm_size=palm_size):
                self.assertTrue(self.state_for(0.2).is_pinching)
                state = self.detector.update([make_hand(0.0, palm_size=palm_size)], WIDTH, HEIGHT)[0]
                self.assertIsNone(state.pinch_ratio)
                self.assertFalse(state.is_pinching)
                self.assertFalse(self.state_for(BETWEEN_THRESHOLDS).is_pinching)

    def test_far_away_hand_starts_with_fresh_state(self):
        first = self.state_for(0.2)
        new_hand = self.detector.update([make_hand(BETWEEN_THRESHOLDS, (900, 360))], WIDTH, HEIGHT)[0]
        self.assertNotEqual(new_hand.track_id, first.track_id)
        self.assertFalse(new_hand.is_pinching)


if __name__ == "__main__":
    unittest.main()
