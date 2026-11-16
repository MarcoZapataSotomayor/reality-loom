"""Delay slider and per-panel offsets, without a camera, model, or native UI."""

from unittest.mock import MagicMock, patch
import unittest

import cv2
import numpy as np

from delay_slider import DelaySlider, SliderTrack
from filter_toolbar import DELETE_KEYS, FilterToolbar
from freeze_control import FreezeController
from interaction import Rectangle
from panels import PanelCollection
from temporal_history import MAX_FRAMES, MAX_IMAGE_BYTES, quantize_delay
from test_fist_gesture import pose_hand
from test_panel_preview import add_panel, samples
import test_frozen_content as preview_support


def hand(track_id, point, pinching=False):
    return pose_hand("neutral" if pinching else "open", track_id, point, pinching=pinching)


def delayed_scene():
    scene = PanelCollection()
    panel = add_panel(scene)
    panel.source_mode = "DELAYED"
    return scene, panel


class SliderMappingTests(unittest.TestCase):
    def test_mapping_clamps_and_quantizes_all_steps_and_midpoints(self):
        track = SliderTrack(20, 420, 200)
        self.assertEqual(track.value_at(-10000), 0.5)
        self.assertEqual(track.value_at(10000), 2.5)
        for tick in range(5, 26):
            x = 20 + (tick - 5) * 20
            self.assertEqual(track.value_at(x), tick / 10)
            self.assertEqual(track.marker_x(tick / 10), x)
        self.assertEqual(track.value_at(29.999), 0.5)
        self.assertEqual(track.value_at(30), 0.6)
        self.assertEqual(quantize_delay(1.15), 1.2)
        self.assertEqual(quantize_delay(2.499999999999), 2.5)

    def test_layout_keeps_slider_caption_track_and_toolbar_apart(self):
        for width, height in ((320, 360), (640, 360), (640, 480), (1280, 720)):
            track = DelaySlider.track(width, height)
            self.assertGreaterEqual(track.y - 30, 114)
            caption_top = FilterToolbar.action_buttons(width, height)[0].top - 30
            self.assertLess(track.y + 14, caption_top)
            self.assertTrue(0 < track.left < track.right < width)
        self.assertIsNone(DelaySlider.track(320, 240))


class SliderCaptureTests(unittest.TestCase):
    def setUp(self):
        self.scene, self.panel = delayed_scene()
        self.slider = DelaySlider()
        self.track = self.slider.track(640, 480)
        self.point = ((self.track.left + self.track.right) / 2, self.track.y)

    def update(self, hands, key=-1, enabled=True):
        return self.slider.update(hands, 640, 480, self.scene, enabled, key)

    def start(self):
        self.assertFalse(self.update([hand(1, self.point)]))
        self.assertTrue(self.update([hand(1, self.point, True)]))
        self.assertTrue(self.scene.adjusting_delay)

    def test_newly_pinched_or_entering_while_held_cannot_activate(self):
        self.assertFalse(self.update([hand(1, self.point, True)]))
        self.update([hand(1, (600, 200))])
        self.assertFalse(self.update([hand(1, (600, 200), True)]))
        self.assertFalse(self.update([hand(1, self.point, True)]))
        self.assertEqual(self.panel.delay_seconds, 2)
        self.assertFalse(self.slider.active)
        self.update([hand(1, self.point)])
        self.assertTrue(self.update([hand(1, self.point, True)]))
        self.assertEqual(self.panel.delay_seconds, 1.5)

    def test_owner_is_stable_even_outside_track_and_other_hand_cannot_take_over(self):
        self.start()
        self.update([hand(7, (self.track.left, self.track.y), True),
                     hand(1, (self.track.right + 200, 10), True)])
        self.assertEqual(self.slider.owner_id, 1)
        self.assertEqual(self.panel.delay_seconds, 2.5)
        self.update([hand(7, self.point, True)])
        self.assertFalse(self.slider.active)
        self.assertFalse(self.scene.adjusting_delay)
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.assertFalse(self.update([hand(7, self.point, True)]))
        self.assertEqual(self.panel.delay_seconds, 2.5)

    def test_release_requires_rearming_and_cannot_immediately_manipulate(self):
        self.start()
        self.assertTrue(self.update([hand(1, self.point)]))
        self.assertFalse(self.slider.active)
        self.assertFalse(self.scene.toolbar_enabled)
        self.scene.update(samples(True), 640, 480)
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.assertFalse(self.scene.apply_action("NEW"))
        self.scene.update(samples(), 640, 480)
        self.update([hand(1, self.point)])
        self.assertTrue(self.update([hand(1, self.point, True)]))

    def test_simultaneous_candidates_choose_lowest_track_id(self):
        self.update([hand(9, self.point), hand(2, self.point)])
        self.update([hand(9, self.point, True), hand(2, self.point, True)])
        self.assertEqual(self.slider.owner_id, 2)

    def test_capture_locks_actions_geometry_and_freezing(self):
        self.start()
        box = self.panel.rectangle
        for action in ("NEW", "DELETE", "NEON", "DELAY"):
            self.assertFalse(self.scene.apply_action(action))
        self.assertFalse(self.scene.begin_creation())
        self.assertFalse(self.scene.delete_active())
        self.assertFalse(self.scene.select_filter("NEON"))
        self.assertFalse(self.scene.toggle_frozen(preview_support.frame()))
        self.scene.update(samples(True, (200, 200), (400, 400)), 640, 480)
        self.assertEqual(self.panel.rectangle, box)
        self.assertEqual(self.panel.content_mode, "DELAYED")

    def test_disabled_modes_and_states_do_not_arm_or_adjust(self):
        for mode in ("LIVE", "FROZEN"):
            self.panel.source_mode = "LIVE"
            self.panel.frozen_image = preview_support.frame() if mode == "FROZEN" else None
            self.assertFalse(self.update([hand(1, self.point)]))
            self.assertFalse(self.update([hand(1, self.point, True)], ord("]")))
        self.panel.frozen_image = None
        self.panel.source_mode = "DELAYED"
        for state in ("CREATING", "DRAGGING", "RESIZING", "WAITING_FOR_RELEASE"):
            self.scene.controller.state = state
            self.assertFalse(self.update([hand(1, self.point)]))
            self.assertFalse(self.update([hand(1, self.point, True)], ord("[")))
        self.scene.controller.state = "PLACED"
        self.assertFalse(self.update([hand(1, self.point)], enabled=False))
        self.assertFalse(self.update([hand(1, self.point, True)], enabled=False))
        self.assertEqual(self.panel.delay_seconds, 2)

    def test_keyboard_steps_do_not_accumulate_error_and_work_without_visible_slider(self):
        for _ in range(30):
            self.assertTrue(self.update([], ord("]")))
        self.assertEqual(self.panel.delay_seconds, 2.5)
        for _ in range(30):
            self.update([], ord("["))
        self.assertEqual(self.panel.delay_seconds, 0.5)
        for _ in range(10):
            self.update([], ord("]"))
        self.assertEqual(self.panel.delay_seconds, 1.5)
        self.assertTrue(self.slider.update([], 320, 240, self.scene, True, ord("]")))
        self.assertEqual(self.panel.delay_seconds, 1.6)

    def test_recovery_cancels_capture_and_preserves_value(self):
        self.start()
        self.scene.prepare_camera_reconnect()
        self.update([hand(1, (self.track.right, self.track.y), True)], enabled=False)
        self.assertFalse(self.slider.active)
        self.assertFalse(self.scene.adjusting_delay)
        self.scene.finish_camera_reconnect((640, 480), (640, 480))
        self.assertEqual(self.panel.delay_seconds, 1.5)
        self.assertFalse(self.update([hand(1, self.point, True)]))


class AdjustableHistoryTests(unittest.TestCase):
    def test_independent_offsets_timestamp_boundaries_and_freeze_retention(self):
        scene, first = delayed_scene()
        first.delay_seconds = 2.5
        second = add_panel(scene, (350, 100), (550, 300))
        self.assertEqual(second.delay_seconds, 2)
        second.source_mode = "DELAYED"
        scene.set_delay(0.5)
        for stamp, value in ((0.3, 30), (1.1, 60), (2.3, 90), (2.8, 120)):
            scene.record_frame(preview_support.frame((value, value, value)), stamp)
        raw = preview_support.frame((120, 120, 120))
        display = raw.copy()
        scene.composite(raw, display)
        np.testing.assert_array_equal(display[200, 200], (30, 30, 30))
        np.testing.assert_array_equal(display[200, 400], (90, 90, 90))
        self.assertTrue(scene.toggle_frozen(raw))
        self.assertTrue(np.all(second.frozen_image == 90))
        self.assertTrue(scene.toggle_frozen(raw))
        self.assertEqual(second.content_mode, "DELAYED")
        self.assertEqual(second.delay_seconds, 0.5)
        scene.apply_action("DELAY")
        scene.update(samples(), 640, 480)
        scene.apply_action("DELAY")
        scene.update(samples(), 640, 480)
        self.assertEqual(second.delay_seconds, 0.5)
        self.assertEqual(first.delay_seconds, 2.5)
        scene.prepare_camera_reconnect()
        scene.finish_camera_reconnect((640, 480), (640, 480))
        self.assertEqual([panel.delay_seconds for panel in scene.panels], [2.5, 0.5])

    def test_longer_offset_buffers_and_blocks_freeze_until_available(self):
        scene, panel = delayed_scene()
        scene.set_delay(2.5)
        scene.record_frame(preview_support.frame(), 0)
        scene.record_frame(preview_support.frame(), 2.4)
        self.assertFalse(scene.toggle_frozen(preview_support.frame()))
        self.assertIn("Buffering", scene.notice)
        scene.record_frame(preview_support.frame(), 2.5)
        self.assertTrue(scene.toggle_frozen(preview_support.frame()))
        self.assertEqual(panel.delay_seconds, 2.5)

    def test_adjusting_and_rendering_do_not_duplicate_or_expand_history(self):
        scene, panel = delayed_scene()
        history = scene.history
        raw = np.zeros((360, 640, 3), np.uint8)
        for index in range(500):
            scene.record_frame(raw, index / 100)
        images = [image for _, image in history.frames]
        byte_count = history.image_bytes
        for tick in range(5, 26):
            scene.set_delay(tick / 10)
            scene.composite(raw, raw.copy())
        self.assertIs(scene.history, history)
        self.assertEqual(history.image_bytes, byte_count)
        self.assertTrue(all(a is b for a, (_, b) in zip(images, history.frames)))
        self.assertLessEqual(len(history.frames), MAX_FRAMES)
        self.assertLessEqual(byte_count, MAX_IMAGE_BYTES)
        self.assertEqual(panel.delay_seconds, 2.5)


class SliderPreviewTests(unittest.TestCase):
    def preview(self, scene, keys, gestures, **kwargs):
        return preview_support.FrozenPreviewTests().preview(
            scene, [preview_support.frame()] * len(keys), keys, gesture_frames=gestures, **kwargs)

    def capture_hands(self):
        track = DelaySlider.track(640, 480)
        point = ((track.left + track.right) / 2, track.y)
        return [hand(1, point)], [hand(1, point, True)]

    def test_capture_wins_panel_resize_and_blocks_keys_until_release(self):
        for key in (ord("f"), ord("n"), ord("1"), ord("t"), DELETE_KEYS[0], ord("]")):
            with self.subTest(key=key):
                scene, panel = delayed_scene()
                opened, held = self.capture_hands()
                point = held[0].pinch_point
                panel.rectangle = Rectangle(*point, 550, 450)
                scene.controller.rectangle = panel.rectangle
                opened.append(hand(2, (550, 450)))
                held.append(hand(2, (550, 450), True))
                with patch.object(scene, "toggle_frozen", wraps=scene.toggle_frozen) as freeze:
                    self.preview(scene, [-1, key, key, ord("q")], [opened, held, held, held])
                    freeze.assert_not_called()
                self.assertEqual(scene.panels, [panel])
                self.assertEqual(panel.delay_seconds, 1.5)
                self.assertEqual(panel.content_mode, "DELAYED")
                self.assertEqual(panel.filter_name, "ORIGINAL")
                self.assertFalse(scene.creation_mode)
                self.assertEqual(panel.rectangle, Rectangle(*point, 550, 450))

    def test_slider_cancels_pending_fist_and_blocks_held_toolbar_activation(self):
        scene, panel = delayed_scene()
        opened, held = self.capture_hands()
        track = DelaySlider.track(640, 480)
        button = FilterToolbar.buttons(640, 480)[1]
        over_filter = [hand(1, (track.right, (button.top + button.bottom) / 2), True)]
        controller = FreezeController()
        open_fist = opened + [pose_hand("open", 2, (500, 300))]
        holding_fist = opened + [pose_hand("fist", 2, (500, 300))]
        captured_fist = held + [pose_hand("fist", 2, (500, 300))]
        with patch("freeze_control.FreezeController", return_value=controller), \
                patch("freeze_control.time.monotonic", side_effect=[0, 1, 3]):
            self.preview(scene, [-1, -1, ord("f"), -1, -1, ord("q")],
                         [open_fist, holding_fist, captured_fist, over_filter, [], over_filter])
        self.assertFalse(controller._pending)
        self.assertEqual(panel.content_mode, "DELAYED")
        self.assertEqual(panel.filter_name, "ORIGINAL")
        self.assertEqual(scene.state, "WAITING_FOR_RELEASE")

    def test_keyboard_consumes_simultaneous_pinches_and_can_repeat_without_hands(self):
        scene, panel = delayed_scene()
        self.preview(scene, [ord("["), ord("["), ord("q")], [[], [], []])
        self.assertEqual(panel.delay_seconds, 1.8)
        self.preview(scene, [ord("]"), -1, ord("q")], [samples(True)] * 3)
        self.assertEqual(panel.delay_seconds, 1.9)
        self.assertEqual(scene.state, "WAITING_FOR_RELEASE")

    def test_r_c_escape_and_q_remain_available_during_capture(self):
        for key in (ord("r"), ord("c"), 27, ord("q")):
            with self.subTest(key=key):
                scene, panel = delayed_scene()
                opened, held = self.capture_hands()
                keys = [-1, -1, key]
                gestures = [opened, held, held]
                if key in (ord("r"), ord("c")):
                    keys.append(ord("q"))
                    gestures.append(held)
                pending = MagicMock(poll=MagicMock(return_value=None))
                def recover(camera, *args):
                    camera.release()
                    return pending
                self.preview(scene, keys, gestures, recover=recover)
                self.assertFalse(scene.adjusting_delay)
                if key == ord("r"):
                    self.assertFalse(scene.panels)
                else:
                    self.assertEqual(panel.delay_seconds, 1.5)
                if key == ord("c"):
                    pending.close.assert_called_once()
                    self.assertFalse(scene.history.frames)


if __name__ == "__main__":
    unittest.main()
