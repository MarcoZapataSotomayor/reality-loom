"""Per-panel delayed sources, action arbitration, and mocked preview integration."""

from unittest.mock import patch
import unittest

import cv2
import numpy as np

from filter_toolbar import FilterToolbar
from freeze_control import FreezeController
from interaction import Rectangle
from panels import PanelCollection
from test_panel_preview import add_panel, samples
from test_fist_gesture import pose_hand
import test_frozen_content as preview_support
from test_frozen_content import frame


class DelayedPanelTests(unittest.TestCase):
    def setUp(self):
        self.scene = PanelCollection()
        self.panel = add_panel(self.scene)

    def release(self):
        self.scene.update(samples(), 640, 480)

    def delay(self):
        self.assertTrue(self.scene.apply_action("DELAY"))
        self.release()

    def warm(self):
        self.scene.record_frame(frame((10, 20, 30)), 0)
        self.scene.record_frame(frame((60, 70, 80)), 2.1)

    def test_modes_are_independent_and_new_panels_default_to_live(self):
        self.delay()
        self.assertEqual(self.panel.content_mode, "DELAYED")
        other = add_panel(self.scene, (350, 100), (550, 300))
        self.assertEqual(other.content_mode, "LIVE")
        self.scene.apply_action("GRAYSCALE")
        self.release()
        self.delay()
        self.assertEqual(other.content_mode, "DELAYED")
        self.delay()
        self.assertEqual(other.content_mode, "LIVE")
        self.assertEqual(self.panel.content_mode, "DELAYED")
        self.assertEqual(self.panel.filter_name, "ORIGINAL")
        self.assertEqual(other.filter_name, "GRAYSCALE")

    def test_shared_history_stacking_filters_and_selected_only_freeze_delete(self):
        self.delay()
        self.warm()
        history = self.scene.history
        other = add_panel(self.scene, (150, 150), (350, 350))
        other.filter_name = "GRAYSCALE"
        raw = frame((60, 70, 80))
        display = raw.copy()
        self.scene.composite(raw, display)
        np.testing.assert_array_equal(display[140, 140], (10, 20, 30))
        self.assertEqual(len(set(display[200, 200])), 1)
        self.assertTrue(self.scene.toggle_frozen(raw))
        self.assertTrue(np.all(other.frozen_image == (60, 70, 80)))
        self.assertIsNone(self.panel.frozen_image)
        self.assertIs(self.scene.history, history)
        self.assertEqual(len(history.frames), 2)
        self.assertTrue(self.scene.delete_active())
        self.assertEqual(self.scene.panels, [self.panel])
        self.assertEqual(self.scene.content_mode, "DELAYED")
        self.scene.reset()
        self.assertFalse(self.scene.panels)
        self.assertIs(self.scene.history, history)
        self.assertEqual(len(history.frames), 2)

    def test_delayed_freeze_uses_raw_history_not_filter_and_unfreezes_to_delay(self):
        self.delay()
        self.warm()
        self.panel.filter_name = "NEON"
        self.assertTrue(self.scene.toggle_frozen(frame((60, 70, 80))))
        frozen = self.panel.frozen_image
        self.assertEqual(self.panel.content_mode, "FROZEN")
        self.assertTrue(np.all(frozen == (10, 20, 30)))
        self.assertFalse(np.shares_memory(frozen, self.scene.history.at(0)))
        self.assertFalse(self.scene.can_delay)
        self.assertFalse(self.scene.apply_action("DELAY"))
        self.assertIn("Unfreeze", self.scene.notice)
        self.assertEqual(self.panel.source_mode, "DELAYED")
        self.release()
        self.assertTrue(self.scene.toggle_frozen(frame()))
        self.assertEqual(self.panel.content_mode, "DELAYED")
        self.assertIsNone(self.panel.frozen_image)
        self.delay()
        self.assertTrue(self.scene.toggle_frozen(frame((60, 70, 80))))
        self.assertTrue(np.all(self.panel.frozen_image == (60, 70, 80)))
        self.assertTrue(self.scene.toggle_frozen(frame()))
        self.assertEqual(self.panel.content_mode, "LIVE")

    def test_buffering_placeholder_and_freeze_rejection_without_removing_panel(self):
        self.delay()
        self.scene.record_frame(frame(), 0)
        display = frame()
        with patch.object(cv2, "putText", wraps=cv2.putText) as labels:
            self.scene.composite(frame(), display)
        self.assertIn("Buffering...", [call.args[1] for call in labels.call_args_list])
        self.assertFalse(self.scene.toggle_frozen(frame()))
        self.assertIn("Buffering...", self.scene.notice)
        self.assertEqual(self.scene.panels, [self.panel])
        self.assertEqual(self.panel.content_mode, "DELAYED")
        self.assertIsNone(self.panel.frozen_image)
        self.scene.record_frame(frame(), 2.1)
        self.assertTrue(self.scene.toggle_frozen(frame()))
        self.assertEqual(self.scene.notice, "")

    def test_fist_freezes_delayed_pixels_and_ignores_buffering(self):
        self.delay()
        controller = FreezeController()
        for stamp, pose in ((0, "open"), (1, "fist"), (1.81, "fist")):
            self.scene.record_frame(frame((10, 20, 30)), stamp)
            controller.update([pose_hand(pose, 1, (500, 300))], self.scene, now=stamp)
            self.assertFalse(controller.apply(self.scene, frame((60, 70, 80))))
        self.assertIn("Buffering...", self.scene.notice)
        for stamp, pose in ((2, "open"), (2.1, "fist"), (2.91, "fist")):
            self.scene.record_frame(frame((60, 70, 80)), stamp)
            controller.update([pose_hand(pose, 1, (500, 300))], self.scene, now=stamp)
            changed = controller.apply(self.scene, frame((60, 70, 80)))
        self.assertTrue(changed)
        self.assertEqual(self.panel.content_mode, "FROZEN")
        self.assertTrue(np.all(self.panel.frozen_image == (10, 20, 30)))

    def test_moving_and_resizing_resample_current_historical_screen_region(self):
        self.delay()
        raw = frame((10, 20, 30))
        raw[:, 320:] = (80, 90, 100)
        self.scene.record_frame(raw, 0)
        self.scene.record_frame(frame(), 2.1)
        display = frame()
        self.scene.composite(frame(), display)
        np.testing.assert_array_equal(display[200, 200], (10, 20, 30))
        self.scene.controller.rectangle = Rectangle(350, 120, 600, 320)
        self.scene._store_active()
        self.scene.composite(frame(), display)
        np.testing.assert_array_equal(display[200, 400], (80, 90, 100))
        self.assertIsNone(self.panel.frozen_image)

    def test_recovery_retains_mode_but_resets_buffer_and_size_change_clears_panels(self):
        self.delay()
        self.warm()
        self.scene.prepare_camera_reconnect()
        self.assertFalse(self.scene.history.frames)
        self.scene.finish_camera_reconnect((640, 480), (640, 480))
        self.assertEqual(self.panel.content_mode, "DELAYED")
        self.scene.record_frame(frame(), 10)
        self.release()
        self.assertFalse(self.scene.toggle_frozen(frame()))
        self.scene.finish_camera_reconnect((640, 480), (1280, 720))
        self.assertFalse(self.scene.history.frames)
        self.assertEqual(self.scene.panels, [])

    def test_delay_action_consumption_rearms_and_blocks_held_resize(self):
        self.scene.apply_action("DELAY")
        self.scene.update(samples(True), 640, 480)
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.assertFalse(self.scene.apply_action("DELAY"))
        self.assertFalse(self.scene.toggle_frozen(frame()))
        self.release()
        self.scene.switch_tool("RESIZE")
        self.release()
        self.scene.update(samples(True), 640, 480)
        self.assertEqual(self.scene.state, "RESIZING")
        self.assertFalse(self.scene.apply_action("DELAY"))
        self.assertEqual(self.panel.content_mode, "DELAYED")


class DelayedPreviewTests(unittest.TestCase):
    def test_delayed_display_freeze_and_raw_live_inference_with_exit_cleanup(self):
        scene = PanelCollection()
        panel = add_panel(scene)
        panel.source_mode = "DELAYED"
        images = [frame((10, 20, 30)), frame((60, 70, 80)), frame((90, 100, 110))]
        helper = preview_support.FrozenPreviewTests()
        def overlay(display, result, gestures):
            display[125, 105] = (255, 0, 255)
        with patch("panels.monotonic", side_effect=[0, 2.1, 2.2]):
            inputs, shown, _ = helper.preview(scene, images, [-1, ord("f"), ord("q")], draw_hands=overlay)
        for actual, expected in zip(inputs, images):
            np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(shown[1][200, 200], (10, 20, 30))
        self.assertEqual(panel.content_mode, "FROZEN")
        self.assertTrue(np.all(panel.frozen_image == (10, 20, 30)))
        self.assertFalse(scene.history.frames)
        self.assertEqual(scene.history.image_bytes, 0)

    def test_delay_button_overlap_wins_over_resize_and_consumes_held_pinches(self):
        scene = PanelCollection()
        panel = add_panel(scene)
        button = FilterToolbar.action_buttons(640, 480)[2]
        point = ((button.left + button.right) / 2, (button.top + button.bottom) / 2)
        panel.rectangle = Rectangle(*point, 550, 470)
        scene.controller.rectangle = panel.rectangle
        scene.submenu = "TIME"
        opened = samples(False, point, (550, 470))
        held = samples(True, point, (550, 470))
        preview_support.FrozenPreviewTests().preview(scene, [frame()] * 3, [-1, -1, ord("q")],
                                    gesture_frames=[opened, held, held])
        self.assertEqual(panel.content_mode, "DELAYED")
        self.assertEqual(scene.state, "WAITING_FOR_RELEASE")
        self.assertEqual(panel.rectangle, Rectangle(*point, 550, 470))

    def test_t_uses_same_action_and_busy_t_is_ignored(self):
        scene = PanelCollection()
        panel = add_panel(scene)
        preview_support.FrozenPreviewTests().preview(scene, [frame()] * 3, [ord("T"), -1, ord("q")],
                                    gesture_frames=[samples()] * 3)
        self.assertEqual(panel.content_mode, "DELAYED")
        scene.switch_tool("RESIZE")
        scene.update(samples(), 640, 480)
        scene.update(samples(True), 640, 480)
        self.assertEqual(scene.state, "RESIZING")
        preview_support.FrozenPreviewTests().preview(scene, [frame()] * 2, [ord("t"), ord("q")],
                                    gesture_frames=[samples(True)] * 2)
        self.assertEqual(panel.content_mode, "DELAYED")

    def test_no_tracking_never_constructs_history(self):
        with patch("panels.TemporalHistory", side_effect=AssertionError("history initialized")):
            preview_support.FrozenPreviewTests().preview(None, [frame()], [ord("q")], tracking=False)

    def test_frozen_t_reports_feedback_and_leaves_previous_mode_unchanged(self):
        scene = PanelCollection()
        panel = add_panel(scene)
        scene.toggle_frozen(frame())
        original = panel.frozen_image
        _, _, labels = preview_support.FrozenPreviewTests().preview(
            scene, [frame()] * 2, [ord("t"), ord("q")], gesture_frames=[samples()] * 2)
        self.assertTrue(any("Unfreeze" in label for label in labels))
        self.assertIs(panel.frozen_image, original)
        self.assertEqual(panel.source_mode, "LIVE")

    def test_delay_keyboard_wins_filter_pinch_and_consumes_all_held_hands(self):
        toolbar = FilterToolbar()
        button = toolbar.buttons(640, 480)[1]
        point = ((button.left + button.right) / 2, (button.top + button.bottom) / 2)
        toolbar.update(samples(False, point), 640, 480, True)
        hands = samples(True, point)
        self.assertTrue(toolbar.update(hands, 640, 480, True, ord("t")))
        self.assertEqual(toolbar.action, "DELAY")
        self.assertEqual(toolbar.selected, "ORIGINAL")
        self.assertEqual(toolbar.panel_hands(hands), [])
        self.assertFalse(toolbar.update(hands, 640, 480, True))


if __name__ == "__main__":
    unittest.main()
