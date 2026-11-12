"""Application-level panel actions with mocked camera, models, and windows."""

from unittest.mock import patch
import unittest

import cv2

from filter_toolbar import DELETE_KEYS, FilterToolbar
from interaction import Rectangle
from panels import MAX_PANELS, PanelCollection
from test_fist_gesture import pose_hand
import test_frozen_content as preview_support
import main


WIDTH, HEIGHT = 640, 480


def samples(pinching=False, first=(100, 100), second=(300, 300)):
    pose = "neutral" if pinching else "open"
    return [pose_hand(pose, 1, first, pinching=pinching), pose_hand(pose, 2, second, pinching=pinching)]


def add_panel(scene, first=(100, 100), second=(300, 300)):
    if scene.panels:
        scene.begin_creation()
        scene.update(samples(), WIDTH, HEIGHT)
    scene.update(samples(True, first, second), WIDTH, HEIGHT)
    scene.update(samples(False, first, second), WIDTH, HEIGHT)
    return scene.active_panel


class PanelPreviewTests(unittest.TestCase):
    def preview(self, scene, keys, gestures=None):
        helper = preview_support.FrozenPreviewTests()
        return helper.preview(scene, [preview_support.frame() for _ in keys], keys,
                              gesture_frames=gestures)

    def test_new_toolbar_pinch_is_consumed_and_creation_waits_for_both_released(self):
        scene = PanelCollection()
        old = add_panel(scene)
        toolbar = FilterToolbar()
        button = toolbar.action_buttons(WIDTH, HEIGHT)[0]
        point = ((button.left + button.right) / 2, (button.top + button.bottom) / 2)
        hands_open = samples(False, point, (550, 300))
        held = samples(True, point, (550, 300))
        new_open = samples(False, (350, 100), (550, 300))
        new_pinches = samples(True, (350, 100), (550, 300))
        gestures = [hands_open, held, held, new_open, new_pinches, new_open, new_open]
        self.preview(scene, [-1] * 6 + [ord("q")], gestures)
        self.assertEqual(len(scene.panels), 2)
        self.assertEqual(scene.panels[0], old)
        self.assertEqual(scene.active_id, 2)
        self.assertEqual(scene.active_panel.rectangle, Rectangle(350, 100, 550, 300))

    def test_n_and_escape_cancel_creation_before_a_release_can_commit(self):
        scene = PanelCollection()
        old = add_panel(scene)
        gestures = [samples(), samples(), samples(True, (350, 100), (550, 300)),
                    samples(), samples()]
        self.preview(scene, [ord("n"), -1, -1, 27, ord("q")], gestures)
        self.assertEqual(scene.panels, [old])
        self.assertFalse(scene.creation_mode)
        self.assertEqual(scene.state, "PLACED")

    def test_escape_with_no_committed_panels_and_q_during_creation_exit(self):
        scene = PanelCollection()
        self.preview(scene, [27], [samples()])
        self.assertEqual(scene.panels, [])
        old = add_panel(scene)
        scene.begin_creation()
        scene.update(samples(), WIDTH, HEIGHT)
        scene.update(samples(True), WIDTH, HEIGHT)
        self.preview(scene, [ord("q")], [samples(True)])
        self.assertEqual(scene.panels, [old])

    def test_delete_key_removes_only_active_and_does_not_need_truncated_keycodes(self):
        for key in DELETE_KEYS:
            with self.subTest(key=key):
                scene = PanelCollection()
                lower = add_panel(scene)
                removed = add_panel(scene, (350, 100), (550, 300))
                self.preview(scene, [key, ord("q")], [samples(), samples()])
                self.assertEqual(scene.panels, [lower])
                self.assertEqual(scene.active_id, lower.panel_id)
                self.assertNotIn(removed, scene.panels)

    def test_delete_button_over_panel_consumes_its_pinch_without_grabbing_remaining_panel(self):
        scene = PanelCollection()
        lower = add_panel(scene, (100, 330), (400, 470))
        add_panel(scene, (100, 330), (400, 470))
        button = FilterToolbar.action_buttons(WIDTH, HEIGHT)[1]
        point = ((button.left + button.right) / 2, (button.top + button.bottom) / 2)
        opened = [pose_hand("open", 1, point)]
        pinched = [pose_hand("neutral", 1, point, pinching=True)]
        self.preview(scene, [-1, -1, ord("q")], [opened, pinched, pinched])
        self.assertEqual(scene.panels, [lower])
        self.assertEqual(scene.state, "WAITING_FOR_RELEASE")
        self.assertEqual(lower.rectangle, Rectangle(100, 330, 400, 470))

    def test_limit_feedback_and_busy_n_do_not_destroy_existing_panels(self):
        scene = PanelCollection()
        for _ in range(MAX_PANELS):
            add_panel(scene)
        _, _, labels = self.preview(scene, [ord("N"), ord("q")], [samples(), samples()])
        self.assertEqual(len(scene.panels), MAX_PANELS)
        self.assertTrue(any("Limit: 4 panels" in text for text in labels))
        scene.update(samples(), WIDTH, HEIGHT)
        scene.update([pose_hand("open", 1, (200, 200))], WIDTH, HEIGHT)
        scene.update([pose_hand("neutral", 1, (200, 200), pinching=True)], WIDTH, HEIGHT)
        self.assertEqual(scene.state, "DRAGGING")
        self.preview(scene, [ord("N"), ord("q")],
                     [[pose_hand("neutral", 1, (200, 200), pinching=True)]] * 2)
        self.assertFalse(scene.creation_mode)
        self.assertEqual(len(scene.panels), MAX_PANELS)

    def test_only_active_handles_and_clear_all_removes_every_panel(self):
        scene = PanelCollection()
        add_panel(scene)
        active = add_panel(scene, (350, 100), (550, 300))
        display = preview_support.frame()
        with patch.object(cv2, "circle", wraps=cv2.circle) as circles:
            main.draw_rectangle_interaction(display, scene)
        self.assertEqual(circles.call_count, 4)
        self.assertEqual({call.args[1] for call in circles.call_args_list},
                         {(round(x), round(y)) for x, y in active.rectangle.corner_points().values()})
        self.preview(scene, [ord("r"), ord("q")], [samples(), samples()])
        self.assertEqual(scene.panels, [])


if __name__ == "__main__":
    unittest.main()
