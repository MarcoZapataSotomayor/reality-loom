"""Frozen content checks with synthetic BGR frames and fake camera/UI calls."""

import builtins
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import unittest

import cv2
import numpy as np

from interaction import Rectangle, RectangleInteraction
import main


WIDTH = 640
HEIGHT = 480


def hand(track_id, point, pinching=False):
    return SimpleNamespace(track_id=track_id, pinch_point=point, is_pinching=pinching)


def placed_rectangle():
    interaction = RectangleInteraction()
    for pinching in (True, False):
        interaction.update([hand(1, (100, 120), pinching), hand(2, (300, 280), pinching)],
                           WIDTH, HEIGHT)
    return interaction


def frame(color=(10, 20, 30)):
    return np.full((HEIGHT, WIDTH, 3), color, dtype=np.uint8)


class FrozenContentTests(unittest.TestCase):
    def setUp(self):
        self.interaction = placed_rectangle()
        self.raw = frame()

    def test_capture_is_independent_of_later_raw_frame_mutations(self):
        expected = self.raw[120:280, 100:300].copy()
        self.assertTrue(self.interaction.toggle_frozen(self.raw))
        captured = self.interaction.frozen_image
        self.assertFalse(np.shares_memory(captured, self.raw))
        self.raw[:] = 0
        np.testing.assert_array_equal(captured, expected)

    def test_toggle_returns_to_current_live_pixels_and_can_capture_again(self):
        self.assertEqual(self.interaction.content_mode, "LIVE")
        self.interaction.toggle_frozen(self.raw)
        self.assertEqual(self.interaction.content_mode, "FROZEN")
        current = frame((60, 70, 80))
        self.assertTrue(self.interaction.toggle_frozen(current))
        self.assertEqual(self.interaction.content_mode, "LIVE")
        self.assertIsNone(self.interaction.frozen_image)
        preview = current.copy()
        self.interaction.composite_frozen(preview)
        np.testing.assert_array_equal(preview, current)
        self.interaction.toggle_frozen(current)
        np.testing.assert_array_equal(self.interaction.frozen_image, current[120:280, 100:300])

    def test_drag_moves_the_same_image_without_recapturing_or_resizing(self):
        self.interaction.toggle_frozen(self.raw)
        captured = self.interaction.frozen_image
        self.interaction.update([hand(1, (150, 180), True)], WIDTH, HEIGHT)
        with patch("interaction.DRAG_SMOOTHING", 1.0):
            self.interaction.update([hand(1, (250, 230), True)], WIDTH, HEIGHT)
        self.assertEqual(self.interaction.rectangle, Rectangle(200, 170, 400, 330))
        self.assertIs(self.interaction.frozen_image, captured)
        self.assertEqual(captured.shape, (160, 200, 3))
        current = frame((60, 70, 80))
        expected = current.copy()
        expected[170:330, 200:400] = captured
        preview = current.copy()
        self.interaction.composite_frozen(preview)
        np.testing.assert_array_equal(preview, expected)
        np.testing.assert_array_equal(current, frame((60, 70, 80)))

    def test_live_drag_does_not_transport_an_earlier_crop(self):
        self.interaction.update([hand(1, (150, 180), True)], WIDTH, HEIGHT)
        with patch("interaction.DRAG_SMOOTHING", 1.0):
            self.interaction.update([hand(1, (250, 230), True)], WIDTH, HEIGHT)
        current = frame((60, 70, 80))
        preview = current.copy()
        self.interaction.composite_frozen(preview)
        self.assertIsNone(self.interaction.frozen_image)
        np.testing.assert_array_equal(preview, current)

    def test_f_is_ignored_without_placement_or_during_drag_and_rearming(self):
        empty = RectangleInteraction()
        self.assertFalse(empty.toggle_frozen(None))
        empty.update([hand(1, (100, 120), True), hand(2, (300, 280), True)], WIDTH, HEIGHT)
        self.assertFalse(empty.toggle_frozen(self.raw))
        self.interaction.toggle_frozen(self.raw)
        captured = self.interaction.frozen_image
        self.interaction.update([hand(1, (150, 180), True)], WIDTH, HEIGHT)
        self.assertFalse(self.interaction.toggle_frozen(self.raw))
        self.assertIs(self.interaction.frozen_image, captured)
        self.interaction.prepare_camera_reconnect()
        self.assertFalse(self.interaction.toggle_frozen(self.raw))
        self.assertIs(self.interaction.frozen_image, captured)

    def test_r_reset_releases_image_and_rectangle(self):
        self.interaction.toggle_frozen(self.raw)
        self.interaction.reset()
        self.assertIsNone(self.interaction.frozen_image)
        self.assertIsNone(self.interaction.rectangle)
        self.assertEqual(self.interaction.content_mode, "LIVE")

    def test_recovery_keeps_same_image_when_rectangle_survives(self):
        self.interaction.toggle_frozen(self.raw)
        captured = self.interaction.frozen_image
        rectangle = self.interaction.rectangle
        self.interaction.prepare_camera_reconnect()
        self.interaction.prepare_camera_reconnect()  # Retry after a failed attempt.
        self.interaction.finish_camera_reconnect((WIDTH, HEIGHT), (WIDTH, HEIGHT))
        self.interaction.update([hand(1, (100, 120)), hand(2, (300, 280))], WIDTH, HEIGHT)
        self.assertEqual(self.interaction.state, "PLACED")
        self.assertEqual(self.interaction.rectangle, rectangle)
        self.assertIs(self.interaction.frozen_image, captured)

    def test_recovery_cancels_drag_but_retains_its_frozen_content(self):
        self.interaction.toggle_frozen(self.raw)
        captured = self.interaction.frozen_image
        self.interaction.update([hand(1, (150, 180), True)], WIDTH, HEIGHT)
        self.interaction.prepare_camera_reconnect()
        self.interaction.finish_camera_reconnect((WIDTH, HEIGHT), (WIDTH, HEIGHT))
        self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
        self.assertIs(self.interaction.frozen_image, captured)

    def test_changed_recovery_dimensions_clear_both_geometry_and_image(self):
        self.interaction.toggle_frozen(self.raw)
        self.interaction.prepare_camera_reconnect()
        self.interaction.finish_camera_reconnect((WIDTH, HEIGHT), (1280, 720))
        self.assertIsNone(self.interaction.rectangle)
        self.assertIsNone(self.interaction.frozen_image)

    def test_frame_too_small_clears_both_without_resizing_the_image(self):
        self.interaction.toggle_frozen(self.raw)
        self.interaction.update([], 100, 100)
        self.assertIsNone(self.interaction.rectangle)
        self.assertIsNone(self.interaction.frozen_image)

    def test_fractional_positions_keep_the_captured_pixel_dimensions(self):
        self.interaction.rectangle = Rectangle(100.25, 120.25, 300.75, 280.75)
        self.interaction.toggle_frozen(self.raw)
        captured = self.interaction.frozen_image
        self.interaction.update([hand(1, (150, 180), True)], WIDTH, HEIGHT)
        for _ in range(5):
            self.interaction.update([hand(1, (190.7, 210.3), True)], WIDTH, HEIGHT)
            preview = frame((60, 70, 80))
            self.interaction.composite_frozen(preview)
            left, top = round(self.interaction.rectangle.left), round(self.interaction.rectangle.top)
            height, width = captured.shape[:2]
            np.testing.assert_array_equal(preview[top:top + height, left:left + width], captured)
            self.assertIs(self.interaction.frozen_image, captured)

    def test_invalid_raw_crop_is_ignored_safely(self):
        self.assertFalse(self.interaction.toggle_frozen(self.raw[:10, :10]))
        self.assertIsNone(self.interaction.frozen_image)


class FrozenPreviewTests(unittest.TestCase):
    def preview(self, interaction, frames, keys, draw_hands=None, recover=None, tracking=True,
                gesture_frames=None):
        """Exercise the real preview loop without native cameras, models, or windows."""
        inputs, shown = [], []
        camera, tracker, pinch = MagicMock(), MagicMock(), MagicMock()
        camera.read.side_effect = [(True, image) for image in frames[1:]]

        def detect(image):
            inputs.append(image.copy())
            return SimpleNamespace(hand_landmarks=[])

        tracker.detect.side_effect = detect
        if gesture_frames is None:
            pinch.update.return_value = []
        else:
            pinch.update.side_effect = gesture_frames
        fake_tracking = SimpleNamespace(HandTracker=lambda: tracker,
                                        draw_hand_landmarks=draw_hands or MagicMock())
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(StringIO()))
            arguments = ["main.py", "--camera", "0"]
            if tracking:
                stack.enter_context(patch.dict(main.sys.modules, {"hand_tracking": fake_tracking}))
                stack.enter_context(patch("gestures.PinchDetector", return_value=pinch))
                stack.enter_context(patch("interaction.RectangleInteraction", return_value=interaction))
            else:
                arguments.append("--no-tracking")
                original_import = builtins.__import__

                def guard(name, *args, **kwargs):
                    if name in ("hand_tracking", "gestures", "interaction", "freeze_control", "mediapipe"):
                        raise AssertionError(f"Unexpected tracking import: {name}")
                    return original_import(name, *args, **kwargs)

                stack.enter_context(patch.object(builtins, "__import__", side_effect=guard))
            stack.enter_context(patch.object(main.sys, "argv", arguments))
            stack.enter_context(patch.object(main, "open_camera", return_value=(camera, frames[0])))
            stack.enter_context(patch.object(main, "CameraReconnect", side_effect=recover))
            stack.enter_context(patch.object(cv2, "namedWindow"))
            stack.enter_context(patch.object(cv2, "imshow", side_effect=lambda title, image: shown.append(image.copy())))
            stack.enter_context(patch.object(cv2, "waitKey", side_effect=keys))
            stack.enter_context(patch.object(cv2, "getWindowProperty", return_value=1))
            labels = stack.enter_context(patch.object(cv2, "putText", wraps=cv2.putText))
            destroy = stack.enter_context(patch.object(cv2, "destroyAllWindows"))
            self.assertEqual(main.main(), 0)
            destroy.assert_called_once()
            camera.release.assert_called_once()
            if tracking:
                tracker.close.assert_called_once()
        return inputs, shown, [call.args[1] for call in labels.call_args_list]

    def test_capture_and_inference_use_raw_pixels_and_overlays_stay_above_composite(self):
        interaction = placed_rectangle()
        first, second = frame(), frame((60, 70, 80))
        marker = (240, 10, 240)

        def draw_hands(display, result, gestures):
            display[125, 105] = marker

        inputs, shown, labels = self.preview(
            interaction, [first, second], [ord("f"), ord("q")], draw_hands=draw_hands,
        )
        # The captured border and landmark pixels must still be original raw BGR.
        np.testing.assert_array_equal(interaction.frozen_image, first[120:280, 100:300])
        np.testing.assert_array_equal(inputs[0], first)
        np.testing.assert_array_equal(inputs[1], second)
        np.testing.assert_array_equal(shown[1][140, 120], first[140, 120])
        np.testing.assert_array_equal(shown[1][125, 105], marker)
        np.testing.assert_array_equal(shown[1][400, 450], second[400, 450])
        self.assertTrue(any(text.startswith("Content: LIVE") for text in labels))
        self.assertTrue(any(text.startswith("Content: FROZEN") for text in labels))
        np.testing.assert_array_equal(first, frame())
        np.testing.assert_array_equal(second, frame((60, 70, 80)))

    def test_f_is_ignored_during_pending_camera_recovery(self):
        interaction = placed_rectangle()
        interaction.toggle_frozen(frame())
        captured = interaction.frozen_image
        job = MagicMock(poll=MagicMock(return_value=None))

        def recover(camera, index, opener):
            camera.release()
            return job

        self.preview(interaction, [frame()], [ord("c"), ord("F"), ord("q")], recover=recover)
        self.assertEqual(interaction.state, "WAITING_FOR_RELEASE")
        self.assertIs(interaction.frozen_image, captured)
        job.close.assert_called_once()

    def test_instructions_stay_visible_when_frozen_content_covers_the_text_area(self):
        interaction = placed_rectangle()
        interaction.rectangle = Rectangle(100, 40, 300, 200)
        first, second = frame(), frame((60, 70, 80))
        inputs, shown, labels = self.preview(interaction, [first, second], [ord("F"), ord("q")])
        np.testing.assert_array_equal(interaction.frozen_image, first[40:200, 100:300])
        # This interior area contains instruction glyphs, away from the border.
        self.assertTrue(np.any(shown[1][95:110, 110:200] != first[95:110, 110:200]))

    def test_f_is_ignored_in_camera_only_mode_without_loading_tracking(self):
        inputs, shown, labels = self.preview(
            None, [frame(), frame((60, 70, 80))], [ord("F"), 27], tracking=False,
        )
        self.assertEqual(inputs, [])
        self.assertEqual(labels, [])
        np.testing.assert_array_equal(shown[1], frame((60, 70, 80)))

    def test_simultaneous_fist_and_f_key_use_one_raw_frame_toggle(self):
        from test_fist_gesture import pose_hand

        interaction = placed_rectangle()
        images = [frame((10 + index, 20, 30)) for index in range(4)]
        gestures = [[pose_hand("open")], [pose_hand("fist")],
                    [pose_hand("fist")], [pose_hand("fist")]]
        with patch("freeze_control.time.monotonic", side_effect=[0.0, 1.0, 1.81, 3.0]), \
                patch.object(interaction, "toggle_frozen", wraps=interaction.toggle_frozen) as toggle:
            inputs, shown, labels = self.preview(
                interaction, images, [-1, -1, ord("F"), ord("q")], gesture_frames=gestures,
            )
            toggle.assert_called_once()
        np.testing.assert_array_equal(interaction.frozen_image, images[2][120:280, 100:300])
        self.assertTrue(any("FROZEN activated" in label for label in labels))
        for actual, expected in zip(inputs, images):
            np.testing.assert_array_equal(actual, expected)

    def test_r_cancels_a_fist_that_completes_in_the_same_frame(self):
        from test_fist_gesture import pose_hand

        interaction = placed_rectangle()
        gestures = [[pose_hand("open")], [pose_hand("fist")],
                    [pose_hand("fist")], [pose_hand("fist")]]
        with patch("freeze_control.time.monotonic", side_effect=[0.0, 1.0, 1.81, 3.0]), \
                patch.object(interaction, "toggle_frozen", wraps=interaction.toggle_frozen) as toggle:
            self.preview(interaction, [frame() for _ in gestures], [-1, -1, ord("r"), ord("q")],
                         gesture_frames=gestures)
            toggle.assert_not_called()
        self.assertIsNone(interaction.rectangle)
        self.assertIsNone(interaction.frozen_image)

    def test_c_cancels_completed_hold_before_recovery_without_changing_content(self):
        from test_fist_gesture import pose_hand

        interaction = placed_rectangle()
        interaction.toggle_frozen(frame())
        captured = interaction.frozen_image
        job = MagicMock(poll=MagicMock(return_value=None))

        def recover(camera, index, opener):
            camera.release()
            return job

        gestures = [[pose_hand("open")], [pose_hand("fist")], [pose_hand("fist")]]
        with patch("freeze_control.time.monotonic", side_effect=[0.0, 1.0, 1.81]), \
                patch.object(interaction, "toggle_frozen", wraps=interaction.toggle_frozen) as toggle:
            self.preview(interaction, [frame() for _ in gestures], [-1, -1, ord("c"), ord("q")],
                         gesture_frames=gestures, recover=recover)
            toggle.assert_not_called()
        self.assertIs(interaction.frozen_image, captured)
        self.assertEqual(interaction.state, "WAITING_FOR_RELEASE")
        job.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
