"""Explicit tool contracts and contextual UI arbitration with synthetic input."""

from unittest.mock import MagicMock, patch
import unittest

import cv2
import numpy as np

from delay_slider import DelaySlider
from filter_toolbar import FilterToolbar
from freeze_control import FreezeController
from interaction import Rectangle
from panels import PanelCollection
from test_panel_preview import add_panel, samples
import test_frozen_content as preview_support
from test_fist_gesture import pose_hand
from ui import draw_workspace


class ExplicitToolTests(unittest.TestCase):
    def setUp(self):
        self.scene = PanelCollection()

    def release(self):
        self.scene.update(samples(), 640, 480)

    def tool(self, name):
        self.assertTrue(self.scene.switch_tool(name))
        self.release()

    def test_default_select_requires_explicit_creation_and_returns_to_select(self):
        self.assertEqual(self.scene.tool, "SELECT")
        self.scene.update(samples(True), 640, 480)
        self.release()
        self.assertFalse(self.scene.panels)
        self.assertTrue(self.scene.begin_creation())
        self.assertEqual(self.scene.tool, "CREATE")
        self.release()
        self.assertFalse(self.scene.switch_tool("MOVE"))
        self.scene.update(samples(True), 640, 480)
        self.release()
        self.assertEqual(self.scene.tool, "SELECT")
        self.assertEqual(len(self.scene.panels), 1)
        self.assertEqual(self.scene.active_id, self.scene.panels[0].panel_id)
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.release()
        self.assertEqual(self.scene.state, "PLACED")

    def test_select_topmost_and_raise_lower_without_moving_either(self):
        lower = add_panel(self.scene, (50, 120), (300, 300))
        upper = add_panel(self.scene, (150, 150), (400, 350))
        original = [panel.rectangle for panel in self.scene.panels]
        for point, expected in (((200, 200), upper), ((80, 180), lower)):
            self.release()
            self.scene.update(samples(False, point), 640, 480)
            self.scene.update(samples(True, point), 640, 480)
            self.scene.update(samples(True, (450, 250)), 640, 480)
            self.assertEqual(self.scene.active_id, expected.panel_id)
            self.assertIs(self.scene.panels[-1], expected)
            self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.assertEqual(lower.rectangle, original[0])
        self.assertEqual(upper.rectangle, original[1])

    def test_move_does_not_select_another_panel_and_has_no_resize_upgrade(self):
        lower = add_panel(self.scene, (30, 120), (230, 300))
        upper = add_panel(self.scene, (350, 120), (550, 300))
        self.tool("MOVE")
        self.scene.update(samples(False, (100, 200)), 640, 480)
        self.scene.update(samples(True, (100, 200)), 640, 480)
        self.assertEqual(self.scene.active_id, upper.panel_id)
        self.assertEqual(self.scene.state, "PLACED")
        self.scene.update(samples(False, (350, 120), (550, 300)), 640, 480)
        self.scene.update(samples(True, (350, 120), (550, 300)), 640, 480)
        self.assertEqual(self.scene.state, "DRAGGING")
        self.scene.update(samples(True, (350, 120), (550, 300)), 640, 480)
        self.assertEqual(self.scene.state, "DRAGGING")
        self.assertEqual(lower.rectangle, Rectangle(30, 120, 230, 300))

    def test_resize_requires_tool_and_active_opposite_handles(self):
        lower = add_panel(self.scene, (30, 120), (230, 300))
        upper = add_panel(self.scene, (350, 120), (550, 300))
        self.tool("RESIZE")
        for pinching in (False, True):
            self.scene.update(samples(pinching, (30, 120), (230, 300)), 640, 480)
        self.assertEqual(self.scene.state, "PLACED")
        for pinching in (False, True):
            self.scene.update(samples(pinching, (350, 120), (550, 300)), 640, 480)
        self.assertEqual(self.scene.state, "RESIZING")
        self.assertEqual(self.scene.active_id, upper.panel_id)
        self.assertEqual(lower.rectangle, Rectangle(30, 120, 230, 300))

    def test_tool_switch_requires_both_released_and_blocks_switch_during_edit(self):
        add_panel(self.scene)
        self.assertTrue(self.scene.switch_tool("MOVE"))
        self.scene.update(samples(True), 640, 480)
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.assertFalse(self.scene.switch_tool("RESIZE"))
        self.release()
        self.scene.update(samples(False, (200, 200)), 640, 480)
        self.scene.update(samples(True, (200, 200)), 640, 480)
        self.assertEqual(self.scene.state, "DRAGGING")
        for action in ("SELECT", "NEW", "DELETE", "NEON", "TIME", "EFFECTS", "FREEZE"):
            self.assertFalse(self.scene.apply_action(action))

    def test_escape_rolls_back_drag_and_resize_then_selects(self):
        for tool in ("MOVE", "RESIZE"):
            with self.subTest(tool=tool):
                self.setUp()
                panel = add_panel(self.scene)
                original = panel.rectangle
                self.tool(tool)
                for pinching in (False, True):
                    self.scene.update(samples(pinching), 640, 480)
                self.scene.update(samples(True, (80, 80), (380, 340)), 640, 480)
                self.assertNotEqual(panel.rectangle, original)
                self.assertTrue(self.scene.cancel_edit())
                self.assertEqual(panel.rectangle, original)
                self.assertEqual(self.scene.rectangle, original)
                self.assertEqual(self.scene.tool, "SELECT")
                self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
                self.assertFalse(self.scene.cancel_edit())

    def test_lost_controller_stops_without_takeover_and_shows_feedback(self):
        panel = add_panel(self.scene)
        self.tool("MOVE")
        for pinching in (False, True):
            self.scene.update(samples(pinching, (200, 200)), 640, 480)
        before = panel.rectangle
        self.scene.update([pose_hand("neutral", 9, (200, 200), pinching=True)], 640, 480)
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.assertIn("Tracking lost", self.scene.instructions)
        self.assertEqual(panel.rectangle, before)

    def test_escape_after_resize_release_keeps_the_completed_geometry(self):
        panel = add_panel(self.scene)
        self.tool("RESIZE")
        for pinching in (False, True):
            self.scene.update(samples(pinching), 640, 480)
        self.scene.update(samples(True, (80, 80), (380, 340)), 640, 480)
        completed = panel.rectangle
        self.release()
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.scene.cancel_edit()
        self.assertEqual(panel.rectangle, completed)
        self.assertEqual(self.scene.tool, "SELECT")

    def test_context_menus_are_exclusive_and_block_canvas_manipulation(self):
        panel = add_panel(self.scene)
        self.assertTrue(self.scene.apply_action("EFFECTS"))
        self.release()
        self.assertEqual(self.scene.submenu, "EFFECTS")
        self.scene.update(samples(True), 640, 480)
        self.assertEqual(self.scene.state, "PLACED")
        self.assertEqual(self.scene.active_id, panel.panel_id)
        self.assertTrue(self.scene.apply_action("TIME"))
        self.release()
        self.assertEqual(self.scene.submenu, "TIME")
        self.assertTrue(self.scene.apply_action("TIME"))
        self.assertIsNone(self.scene.submenu)

    def test_fist_only_eligible_in_idle_select_with_no_submenu(self):
        add_panel(self.scene)
        self.assertTrue(self.scene.fist_enabled)
        for tool in ("MOVE", "RESIZE"):
            self.tool(tool)
            self.assertFalse(self.scene.fist_enabled)
        self.tool("SELECT")
        for menu in ("EFFECTS", "TIME"):
            self.scene.submenu = menu
            self.assertFalse(self.scene.fist_enabled)
        self.scene.submenu = None
        self.scene.begin_creation()
        self.assertFalse(self.scene.fist_enabled)

    def test_fist_requires_full_open_after_leaving_a_context_menu(self):
        add_panel(self.scene)
        controller = FreezeController()
        raw = preview_support.frame()
        controller.update([pose_hand("open", 1, (500, 300))], self.scene, 0)
        self.scene.submenu = "TIME"
        controller.update([pose_hand("fist", 1, (500, 300))], self.scene, 1)
        self.scene.submenu = None
        controller.update([pose_hand("fist", 1, (500, 300))], self.scene, 3)
        self.assertFalse(controller.apply(self.scene, raw))
        controller.update([pose_hand("open", 1, (500, 300))], self.scene, 4)
        controller.update([pose_hand("fist", 1, (500, 300))], self.scene, 5)
        controller.update([pose_hand("fist", 1, (500, 300))], self.scene, 5.81)
        self.assertTrue(controller.apply(self.scene, raw))


class ToolPreviewTests(unittest.TestCase):
    def preview(self, scene, keys, gestures=None, images=None, **kwargs):
        return preview_support.FrozenPreviewTests().preview(
            scene, images or [preview_support.frame()] * len(keys), keys,
            gesture_frames=gestures or [samples()] * len(keys), **kwargs)

    def test_tool_ui_consumption_and_held_pinches_cannot_grab_panel(self):
        scene = PanelCollection()
        panel = add_panel(scene)
        button = FilterToolbar.tool_buttons(640, 480)[1]
        point = ((button.left + button.right) / 2, (button.top + button.bottom) / 2)
        opened = samples(False, point)
        held = samples(True, point)
        original = panel.rectangle
        self.preview(scene, [-1, -1, -1, ord("q")], [opened, held, samples(True, (200, 200)), held])
        self.assertEqual(scene.tool, "MOVE")
        self.assertEqual(scene.state, "WAITING_FOR_RELEASE")
        self.assertEqual(panel.rectangle, original)

    def test_freeze_button_uses_current_delayed_raw_source_once_and_unfreezes(self):
        scene = PanelCollection()
        panel = add_panel(scene)
        panel.source_mode = "DELAYED"
        button = FilterToolbar.context_buttons(640, 480)[0]
        point = ((button.left + button.right) / 2, (button.top + button.bottom) / 2)
        images = [preview_support.frame((10, 20, 30)), preview_support.frame((70, 80, 90)),
                  preview_support.frame((90, 100, 110))]
        with patch("panels.monotonic", side_effect=[0, 2.1, 2.2]), \
                patch.object(scene, "toggle_frozen", wraps=scene.toggle_frozen) as freeze:
            inputs, _, _ = self.preview(scene, [-1, -1, ord("q")],
                                       [samples(False, point), samples(True, point), samples(True, point)], images)
            freeze.assert_called_once()
        self.assertEqual(panel.content_mode, "FROZEN")
        self.assertTrue(np.all(panel.frozen_image == (10, 20, 30)))
        for actual, expected in zip(inputs, images):
            np.testing.assert_array_equal(actual, expected)
        self.preview(scene, [ord("f"), ord("q")])
        self.assertEqual(panel.content_mode, "DELAYED")

    def test_escape_during_move_restores_geometry_and_does_not_exit(self):
        scene = PanelCollection()
        panel = add_panel(scene)
        original = panel.rectangle
        scene.switch_tool("MOVE")
        scene.update(samples(), 640, 480)
        gestures = [samples(False, (200, 200)), samples(True, (200, 200)),
                    samples(True, (250, 230)), samples(True), samples(True)]
        self.preview(scene, [-1, -1, -1, 27, ord("q")], gestures)
        self.assertEqual(panel.rectangle, original)
        self.assertEqual(scene.tool, "SELECT")

    def test_clear_all_is_blocked_during_active_move(self):
        scene = PanelCollection()
        panel = add_panel(scene)
        scene.switch_tool("MOVE")
        scene.update(samples(), 640, 480)
        self.preview(scene, [-1, -1, ord("r"), ord("q")],
                     [samples(False, (200, 200)), samples(True, (200, 200)),
                      samples(True, (250, 230)), samples(True, (250, 230))])
        self.assertEqual(scene.panels, [panel])

    def test_debug_overlays_are_off_by_default_and_d_toggles_without_affecting_inference(self):
        scene = PanelCollection()
        draw = MagicMock()
        images = [preview_support.frame((index, 40, 80)) for index in range(5)]
        inputs, _, _ = self.preview(scene, [-1, ord("d"), -1, ord("D"), ord("q")],
                                   images=images, draw_hands=draw)
        self.assertEqual(draw.call_count, 2)
        self.assertEqual(len(inputs), 5)
        for actual, expected in zip(inputs, images):
            np.testing.assert_array_equal(actual, expected)

    def test_visible_submenu_hitboxes_and_disabled_panel_actions_match_rendering(self):
        toolbar = FilterToolbar()
        scene = PanelCollection()
        buttons = toolbar.visible_buttons(640, 480, scene)
        names = {button.name for button in buttons}
        self.assertTrue({"SELECT", "MOVE", "RESIZE", "NEW", "FREEZE", "EFFECTS", "TIME", "DELETE"} <= names)
        self.assertFalse(toolbar.eligible("MOVE", scene))
        self.assertFalse(toolbar.eligible("FREEZE", scene))
        self.assertNotIn("NEON", names)
        add_panel(scene)
        scene.submenu = "EFFECTS"
        self.assertIn("NEON", {button.name for button in toolbar.visible_buttons(640, 480, scene)})
        scene.submenu = "TIME"
        names = {button.name for button in toolbar.visible_buttons(640, 480, scene)}
        self.assertIn("DELAY", names)
        self.assertNotIn("NEON", names)

    def test_handles_only_in_resize_and_hover_uses_eligible_targets(self):
        scene = PanelCollection()
        panel = add_panel(scene)
        with patch.object(cv2, "circle", wraps=cv2.circle) as circles:
            draw_workspace(preview_support.frame(), scene)
        self.assertEqual(circles.call_count, 0)
        self.assertEqual(scene.hover_target((200, 200)), (panel.panel_id, None))
        scene.switch_tool("RESIZE")
        self.assertIsNone(scene.hover_target((100, 100)))
        scene.update(samples(), 640, 480)
        with patch.object(cv2, "circle", wraps=cv2.circle) as circles:
            draw_workspace(preview_support.frame(), scene)
        self.assertEqual(circles.call_count, 4)
        self.assertEqual(scene.hover_target((100, 100)), (panel.panel_id, "top_left"))
        scene.submenu = "TIME"
        self.assertIsNone(scene.hover_target((100, 100)))


if __name__ == "__main__":
    unittest.main()
