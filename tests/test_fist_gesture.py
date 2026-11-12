"""Camera-independent fist geometry, timing, and freeze-priority checks."""

from math import cos, sin
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import numpy as np

from freeze_control import FreezeController
from gestures import FIST_HOLD_SECONDS, FistHoldDetector, PinchDetector
from interaction import Rectangle, RectangleInteraction


def landmarks_for(pose, scale=80, width=640, height=480, angle=0.0):
    """Construct a palm with extended or folded fingers in a local coordinate system."""
    points = [(0.0, 0.0)] * 21
    points[1:5] = [(-0.25, 0.1), (-0.5, 0.3), (-0.9, 0.65), (-1.25, 1.0)]
    for mcp, base in ((5, (-0.35, 0.8)), (9, (0.0, 1.0)),
                      (13, (0.3, 0.9)), (17, (0.55, 0.7))):
        points[mcp] = base
        if pose in ("fist", "neutral"):
            offsets = (0.3, 0.1, -0.3)
        else:
            offsets = (0.65, 1.0, 1.35)
        for index, offset in zip((mcp + 1, mcp + 2, mcp + 3), offsets):
            points[index] = (base[0], base[1] + offset)
    if pose == "fist":
        points[4] = (-0.1, 0.55)
    elif pose == "pinch":
        points[4], points[8] = (-0.3, 0.65), (-0.25, 0.65)
    elif pose == "degenerate":
        points = [(0.0, 0.0)] * 21

    result = []
    for x, y in points:
        rotated_x, rotated_y = x * cos(angle) - y * sin(angle), x * sin(angle) + y * cos(angle)
        result.append(SimpleNamespace(x=(width / 2 + scale * rotated_x) / width,
                                      y=(height * 0.75 - scale * rotated_y) / height))
    return result


def pose_hand(pose, track_id=1, center=(100, 100), pinch_point=None, pinching=False):
    return SimpleNamespace(track_id=track_id, center=center, pinch_point=pinch_point or center,
                           is_pinching=pinching, is_fist=pose == "fist", is_open_hand=pose == "open")


class FistGeometryTests(unittest.TestCase):
    def test_closed_fist_extended_pinch_open_hand_and_neutral_are_distinct(self):
        for pose in ("fist", "pinch", "open", "neutral", "degenerate"):
            with self.subTest(pose=pose):
                hand = PinchDetector().update([landmarks_for(pose)], 640, 480)[0]
                self.assertEqual(hand.is_fist, pose == "fist")
                self.assertEqual(hand.is_open_hand, pose == "open")
                if pose == "pinch":
                    self.assertTrue(hand.is_pinching)

    def test_geometry_is_palm_relative_and_accounts_for_aspect_ratio(self):
        for width, height in ((640, 480), (480, 640)):
            for scale in (40, 80, 120):
                for angle in (0.0, 0.7, 1.5):
                    for pose in ("fist", "pinch", "open"):
                        with self.subTest(size=(width, height), scale=scale, angle=angle, pose=pose):
                            hand = PinchDetector().update(
                                [landmarks_for(pose, scale, width, height, angle)], width, height,
                            )[0]
                            self.assertEqual(hand.is_fist, pose == "fist")
                            self.assertEqual(hand.is_open_hand, pose == "open")


class FistHoldTests(unittest.TestCase):
    def setUp(self):
        self.detector = FistHoldDetector()
        self.box = Rectangle(200, 200, 400, 400)

    def update(self, hands, now, enabled=True):
        return self.detector.update(hands, self.box, enabled, now)

    def arm(self):
        self.update([pose_hand("open")], 0.0)

    def test_duration_is_independent_of_frame_intervals(self):
        schedules = ([1.0, 1.79, 1.81], [1.0, 1.2, 1.4, 1.6, 1.79, 1.81],
                     [1.0 + index * 0.01 for index in range(82)])
        for times in schedules:
            with self.subTest(samples=len(times)):
                self.setUp()
                self.arm()
                triggered_at = [now for now in times if self.update([pose_hand("fist")], now)]
                self.assertEqual(len(triggered_at), 1)
                self.assertGreaterEqual(triggered_at[0] - 1.0, FIST_HOLD_SECONDS)

    def test_default_clock_is_monotonic(self):
        with patch("gestures.time.monotonic", side_effect=[0.0, 1.0, 1.81]):
            self.detector.update([pose_hand("open")], self.box, True)
            self.assertFalse(self.detector.update([pose_hand("fist")], self.box, True))
            self.assertTrue(self.detector.update([pose_hand("fist")], self.box, True))

    def test_one_trigger_per_hold_and_only_full_open_rearms(self):
        self.arm()
        self.assertFalse(self.update([pose_hand("fist")], 1.0))
        self.assertTrue(self.update([pose_hand("fist")], 1.81))
        for now in (2.0, 3.0, 8.0):
            self.assertFalse(self.update([pose_hand("fist")], now))
        self.update([pose_hand("neutral")], 9.0)
        self.assertFalse(self.update([pose_hand("fist")], 10.0))
        self.assertFalse(self.update([pose_hand("fist")], 11.0))
        self.update([pose_hand("open")], 12.0)
        self.update([pose_hand("fist")], 13.0)
        self.assertTrue(self.update([pose_hand("fist")], 13.81))

    def test_pose_interruption_restarts_the_whole_hold_duration(self):
        self.arm()
        self.update([pose_hand("fist")], 1.0)
        self.update([pose_hand("neutral")], 1.7)
        self.update([pose_hand("fist")], 2.0)
        self.assertFalse(self.update([pose_hand("fist")], 2.7))
        self.assertTrue(self.update([pose_hand("fist")], 2.81))

    def test_loss_and_replacement_require_new_open_observation(self):
        for next_id in (1, 2):
            with self.subTest(next_id=next_id):
                self.setUp()
                self.arm()
                self.update([pose_hand("fist")], 1.0)
                self.update([], 1.5)
                self.assertFalse(self.update([pose_hand("fist", next_id)], 2.0))
                self.assertFalse(self.update([pose_hand("fist", next_id)], 4.0))
                self.update([pose_hand("open", next_id)], 5.0)
                self.update([pose_hand("fist", next_id)], 6.0)
                self.assertTrue(self.update([pose_hand("fist", next_id)], 6.81))

    def test_order_changes_do_not_transfer_hold_progress(self):
        self.update([pose_hand("open", 1), pose_hand("open", 2)], 0.0)
        self.update([pose_hand("fist", 1), pose_hand("open", 2)], 1.0)
        self.assertTrue(self.update([pose_hand("open", 2), pose_hand("fist", 1)], 1.81))

    def test_direct_track_replacement_does_not_inherit_a_hold(self):
        self.arm()
        self.update([pose_hand("fist", 1)], 1.0)
        self.assertFalse(self.update([pose_hand("fist", 2)], 1.81))
        self.assertFalse(self.update([pose_hand("fist", 2)], 4.0))

    def test_simultaneous_fists_trigger_once_and_both_are_latched(self):
        self.update([pose_hand("open", 1), pose_hand("open", 2)], 0.0)
        self.update([pose_hand("fist", 1), pose_hand("fist", 2)], 1.0)
        self.assertTrue(self.update([pose_hand("fist", 2), pose_hand("fist", 1)], 1.81))
        self.assertFalse(self.update([pose_hand("fist", 1), pose_hand("fist", 2)], 4.0))
        self.update([pose_hand("open", 1), pose_hand("fist", 2)], 5.0)
        self.update([pose_hand("neutral", 1), pose_hand("fist", 2)], 6.0)
        self.assertFalse(self.update([pose_hand("neutral", 1), pose_hand("fist", 2)], 8.0))

    def test_inside_rectangle_interrupts_hold_and_outside_restarts_it(self):
        self.arm()
        self.update([pose_hand("fist")], 1.0)
        self.update([pose_hand("fist", center=(300, 300))], 1.7)
        self.update([pose_hand("fist")], 2.0)
        self.assertFalse(self.update([pose_hand("fist")], 2.7))
        self.assertTrue(self.update([pose_hand("fist")], 2.81))

    def test_disabled_interaction_cancels_and_requires_open_again(self):
        self.arm()
        self.update([pose_hand("fist")], 1.0)
        self.update([pose_hand("fist")], 1.6, enabled=False)
        self.assertFalse(self.update([pose_hand("fist")], 3.0))
        self.update([pose_hand("open")], 4.0)
        self.update([pose_hand("fist")], 5.0)
        self.assertTrue(self.update([pose_hand("fist")], 5.81))


class FreezeControllerTests(unittest.TestCase):
    def setUp(self):
        self.interaction = RectangleInteraction()
        for pinching in (True, False):
            self.interaction.update(
                [pose_hand("neutral", 1, (200, 200), pinching=pinching),
                 pose_hand("neutral", 2, (400, 400), pinching=pinching)], 640, 480,
            )
        self.controller = FreezeController()
        self.raw = np.full((480, 640, 3), (10, 20, 30), dtype=np.uint8)

    def tick(self, hands, now, keyboard=False):
        self.interaction.update(hands, 640, 480)
        self.controller.update(hands, self.interaction, now)
        return self.controller.apply(self.interaction, self.raw, keyboard)

    def test_fist_toggle_uses_existing_independent_raw_crop(self):
        self.tick([pose_hand("open")], 0.0)
        self.tick([pose_hand("fist")], 1.0)
        self.assertTrue(self.tick([pose_hand("fist")], 1.81))
        self.assertEqual(self.interaction.content_mode, "FROZEN")
        np.testing.assert_array_equal(self.interaction.frozen_image, self.raw[200:400, 200:400])
        self.assertFalse(np.shares_memory(self.interaction.frozen_image, self.raw))
        self.assertIn("FROZEN activated", self.controller.message)

    def test_keyboard_and_gesture_same_frame_toggle_only_once(self):
        self.tick([pose_hand("open")], 0.0)
        self.tick([pose_hand("fist")], 1.0)
        self.controller.update([pose_hand("fist")], self.interaction, now=1.81)
        with patch.object(self.interaction, "toggle_frozen", wraps=self.interaction.toggle_frozen) as toggle:
            self.assertTrue(self.controller.apply(self.interaction, self.raw, keyboard=True))
            self.assertFalse(self.controller.apply(self.interaction, self.raw, keyboard=True))
            toggle.assert_called_once()
        self.assertEqual(self.interaction.content_mode, "FROZEN")
        self.assertFalse(self.tick([pose_hand("fist")], 3.0))

    def test_keyboard_cancels_pending_hold_until_full_open(self):
        self.tick([pose_hand("open")], 0.0)
        self.tick([pose_hand("fist")], 1.0)
        self.assertTrue(self.tick([pose_hand("fist")], 1.6, keyboard=True))
        self.assertFalse(self.tick([pose_hand("fist")], 3.0))
        self.tick([pose_hand("neutral")], 4.0)
        self.assertFalse(self.tick([pose_hand("fist")], 6.0))
        self.tick([pose_hand("open")], 7.0)
        self.tick([pose_hand("fist")], 8.0)
        self.assertTrue(self.tick([pose_hand("fist")], 8.81))
        self.assertEqual(self.interaction.content_mode, "LIVE")

    def test_valid_drag_start_has_priority_over_a_completed_fist_hold(self):
        self.tick([pose_hand("open", 1), pose_hand("open", 2, (300, 300))], 0.0)
        self.tick([pose_hand("fist", 1), pose_hand("open", 2, (300, 300))], 1.0)
        hands = [pose_hand("fist", 1), pose_hand("neutral", 2, (300, 300), pinching=True)]
        self.assertFalse(self.tick(hands, 1.81, keyboard=True))
        self.assertEqual(self.interaction.state, "DRAGGING")
        self.assertEqual(self.interaction.content_mode, "LIVE")

    def test_creation_and_recovery_block_gesture_activation(self):
        for state in ("CREATING", "WAITING_FOR_RELEASE"):
            with self.subTest(state=state):
                self.controller.reset()
                self.controller.update([pose_hand("open")], self.interaction, now=0.0)
                self.controller.update([pose_hand("fist")], self.interaction, now=1.0)
                self.interaction.state = state
                self.controller.update([pose_hand("fist")], self.interaction, now=1.81)
                self.assertFalse(self.controller.apply(self.interaction, self.raw))
                self.interaction.state = "PLACED"
                self.controller.update([pose_hand("fist")], self.interaction, now=3.0)
                self.assertFalse(self.controller.apply(self.interaction, self.raw))

    def test_r_reset_cancels_completed_but_unapplied_request(self):
        self.tick([pose_hand("open")], 0.0)
        self.tick([pose_hand("fist")], 1.0)
        self.controller.update([pose_hand("fist")], self.interaction, now=1.81)
        self.interaction.reset()
        self.controller.reset()
        self.assertFalse(self.controller.apply(self.interaction, self.raw))
        self.assertIsNone(self.interaction.frozen_image)
        self.assertIsNone(self.interaction.rectangle)

    def test_c_reset_preserves_frozen_image_but_not_hold_progress(self):
        self.tick([pose_hand("open")], 0.0)
        self.tick([pose_hand("fist")], 1.0)
        self.tick([pose_hand("fist")], 1.81)
        captured = self.interaction.frozen_image
        self.interaction.prepare_camera_reconnect()
        self.controller.reset()
        self.interaction.finish_camera_reconnect((640, 480), (640, 480))
        self.assertFalse(self.tick([pose_hand("fist")], 5.0))
        self.assertIs(self.interaction.frozen_image, captured)
        self.tick([pose_hand("open", 1), pose_hand("open", 2)], 6.0)
        self.tick([pose_hand("fist")], 7.0)
        self.assertTrue(self.tick([pose_hand("fist")], 7.81))
        self.assertEqual(self.interaction.content_mode, "LIVE")


if __name__ == "__main__":
    unittest.main()
