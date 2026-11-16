"""Shared UI geometry, bounds, and modal help with synthetic input only."""

from unittest.mock import patch
import unittest

import cv2
import numpy as np

from delay_slider import DelaySlider
from filter_toolbar import DELETE_KEYS, FilterToolbar
from freeze_control import FreezeController
from help_overlay import HelpOverlay
from interaction import Rectangle
from panels import PanelCollection
from test_panel_preview import add_panel, samples
import test_frozen_content as preview_support
from ui import BACKGROUND, Layout, badge, draw_fist_feedback, draw_workspace, surface


class SharedLayoutTests(unittest.TestCase):
    def test_controls_and_regions_fit_and_do_not_overlap(self):
        for width, height in ((640, 360), (640, 480), (1280, 720)):
            layout = Layout(width, height)
            regions = [layout.header, layout.slider, layout.toolbar, layout.footer]
            for first, second in zip(regions, regions[1:]):
                self.assertLess(first.bottom, second.top)
            for box in regions + layout.actions + layout.filters:
                self.assertTrue(0 <= box.left < box.right < width)
                self.assertTrue(0 <= box.top < box.bottom < height)
            for button in layout.filters + layout.actions:
                self.assertGreaterEqual(button.bottom - button.top, 36)
                self.assertGreaterEqual(button.width, 120)

    def test_toolbar_and_slider_hitboxes_use_shared_draw_geometry(self):
        layout = Layout(640, 480)
        toolbar = FilterToolbar()
        buttons = toolbar.buttons(640, 480) + toolbar.action_buttons(640, 480)
        for button, box in zip(buttons, layout.filters + layout.actions):
            self.assertEqual((button.left, button.top, button.right, button.bottom),
                             (box.left, box.top, box.right, box.bottom))
            point = ((box.left + box.right) / 2, (box.top + box.bottom) / 2)
            scene = PanelCollection()
            add_panel(scene)
            scene.submenu = "TIME" if button.name == "DELAY" else "EFFECTS" if button.name in ("ORIGINAL", "GRAYSCALE", "PIXELATE", "NEON") else None
            toolbar.update(samples(False, point), 640, 480, True, interaction=scene)
            self.assertTrue(toolbar.update(samples(True, point), 640, 480, True, interaction=scene))
            self.assertEqual(toolbar.action, button.name)
        track = DelaySlider.track(640, 480)
        self.assertEqual((track.left, track.right, track.y), layout.slider_track)
        self.assertTrue(track.contains((track.left, track.y)))
        self.assertFalse(track.contains((track.left - 1, track.y)))

    def test_hidden_controls_have_no_targets_and_keyboard_still_works(self):
        for width, height in ((320, 240), (320, 480), (640, 240)):
            self.assertIsNone(Layout(width, height).toolbar)
            self.assertEqual(FilterToolbar.buttons(width, height), [])
            self.assertEqual(FilterToolbar.action_buttons(width, height), [])
            self.assertIsNone(DelaySlider.track(width, height))
            toolbar = FilterToolbar()
            self.assertTrue(toolbar.update([], width, height, True, ord("3")))
            self.assertEqual(toolbar.action, "PIXELATE")
            scene = PanelCollection()
            panel = add_panel(scene)
            panel.source_mode = "DELAYED"
            self.assertTrue(DelaySlider().update([], width, height, scene, True, ord("[")))
            self.assertEqual(panel.delay_seconds, 1.9)

    def test_badges_are_bounded_even_at_corners_and_with_long_labels(self):
        for width, height in ((160, 120), (640, 480), (1280, 720)):
            image = np.zeros((height, width, 3), np.uint8)
            for point in ((-50, -50), (width - 2, height - 2), (width + 50, height + 50)):
                box = badge(image, "#42 DELAYED / GRAYSCALE", point)
                self.assertTrue(0 <= box.left <= box.right < width)
                self.assertTrue(0 <= box.top <= box.bottom < height)

    def test_glass_surfaces_blend_without_touching_pixels_outside_the_region(self):
        image = np.full((100, 120, 3), 240, np.uint8)
        surface(image, 10, 10, 80, 60)
        self.assertTrue(np.all(image[0, 0] == 240))
        self.assertTrue(np.all(image[30, 30] > BACKGROUND))
        self.assertTrue(np.all(image[30, 30] < 240))

    def test_all_rendered_text_fits_small_and_target_frames(self):
        for width, height in ((160, 120), (320, 240), (640, 480), (1280, 720)):
            scene = PanelCollection()
            panel = add_panel(scene)
            panel.rectangle = Rectangle(width - 100, height - 100, width - 1, height - 1)
            scene.controller.rectangle = panel.rectangle
            image = np.full((height, width, 3), 200, np.uint8)
            with patch.object(cv2, "putText", wraps=cv2.putText) as labels:
                draw_workspace(image, scene)
                draw_fist_feedback(image, "Fist hold: 0.4 / 0.8 s")
                help_overlay = HelpOverlay()
                help_overlay.visible = True
                help_overlay.draw(image)
            for call in labels.call_args_list:
                _, value, (x, y), font, scale, _, thickness, _ = call.args
                (text_width, text_height), baseline = cv2.getTextSize(value, font, scale, thickness)
                self.assertTrue(0 <= x and x + text_width < width, value)
                self.assertTrue(0 <= y - text_height and y + baseline < height, value)


class HelpInputTests(unittest.TestCase):
    def setUp(self):
        self.scene = PanelCollection()
        self.panel = add_panel(self.scene)
        self.slider, self.toolbar = DelaySlider(), FilterToolbar()
        self.freeze, self.help = FreezeController(), HelpOverlay()

    def key(self, key):
        return self.help.handle_key(key, self.scene, self.slider, self.toolbar, self.freeze)

    def test_help_discards_only_draft_and_preserves_committed_content(self):
        self.scene.toggle_frozen(preview_support.frame())
        original = self.panel.frozen_image
        self.panel.delay_seconds = 1.2
        self.panel.filter_name = "NEON"
        self.scene.begin_creation()
        self.scene.update(samples(), 640, 480)
        self.scene.update(samples(True, (350, 100), (550, 300)), 640, 480)
        self.assertEqual(self.scene.state, "CREATING")
        self.assertTrue(self.key(ord("h")))
        self.assertFalse(self.scene.creation_mode)
        self.assertEqual(self.scene.panels, [self.panel])
        self.assertIs(self.panel.frozen_image, original)
        self.assertEqual(self.panel.filter_name, "NEON")
        self.assertEqual(self.panel.delay_seconds, 1.2)

    def test_help_stops_drag_resize_and_slider_at_last_geometry_or_value(self):
        for operation in ("DRAGGING", "RESIZING", "SLIDER"):
            with self.subTest(operation=operation):
                self.setUp()
                if operation == "SLIDER":
                    self.panel.source_mode = "DELAYED"
                    self.scene.submenu = "TIME"
                    track = self.slider.track(640, 480)
                    point = (track.left, track.y)
                    self.slider.update(samples(False, point), 640, 480, self.scene, True)
                    self.slider.update(samples(True, point), 640, 480, self.scene, True)
                    self.assertTrue(self.slider.active)
                else:
                    self.scene.controller.state = operation
                original_box = self.panel.rectangle
                original_delay = self.panel.delay_seconds
                self.key(ord("h"))
                self.assertFalse(self.slider.active)
                self.assertFalse(self.scene.adjusting_delay)
                self.assertEqual(self.panel.rectangle, original_box)
                self.assertEqual(self.panel.delay_seconds, original_delay)
                self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")

    def test_h_and_escape_close_help_then_require_both_releases(self):
        for close_key in (ord("h"), 27):
            self.setUp()
            self.assertTrue(self.key(ord("H")))
            self.assertTrue(self.key(close_key))
            self.assertFalse(self.help.visible)
            self.scene.update(samples(True), 640, 480)
            self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
            self.scene.update(samples(), 640, 480)
            self.assertEqual(self.scene.state, "PLACED")

    def test_help_gates_keyboard_and_gestures_but_keeps_live_raw_inference(self):
        self.panel.source_mode = "DELAYED"
        original_box = self.panel.rectangle
        keys = [ord("h"), ord("n"), DELETE_KEYS[0], ord("1"), ord("t"), ord("]"),
                ord("f"), ord("r"), ord("c"), 27, -1, ord("q")]
        images = [preview_support.frame((index, 50, 90)) for index in range(len(keys))]
        with patch.object(self.scene, "toggle_frozen", wraps=self.scene.toggle_frozen) as freeze:
            inputs, _, labels = preview_support.FrozenPreviewTests().preview(
                self.scene, images, keys, gesture_frames=[samples(True)] * len(keys),
                recover=lambda *args: self.fail("C must be gated by help"))
            freeze.assert_not_called()
        self.assertEqual(self.scene.panels, [self.panel])
        self.assertEqual(self.panel.rectangle, original_box)
        self.assertEqual(self.panel.content_mode, "DELAYED")
        self.assertEqual(self.panel.delay_seconds, 2)
        self.assertEqual(self.panel.filter_name, "ORIGINAL")
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.assertIn("CONTROLS", labels)
        for actual, expected in zip(inputs, images):
            np.testing.assert_array_equal(actual, expected)

    def test_h_can_close_help_and_q_can_exit_while_help_is_visible(self):
        for keys in ([ord("h"), ord("q")], [ord("h"), ord("h"), -1, ord("q")]):
            with self.subTest(keys=keys):
                preview_support.FrozenPreviewTests().preview(
                    self.scene, [preview_support.frame()] * len(keys), keys,
                    gesture_frames=[samples()] * len(keys))


if __name__ == "__main__":
    unittest.main()
