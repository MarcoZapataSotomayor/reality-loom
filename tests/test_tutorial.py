"""Tutorial progression from actual workspace actions and mocked-camera input."""

from math import hypot
from unittest.mock import MagicMock, patch
import unittest

import numpy as np

from filter_toolbar import FilterToolbar
from freeze_control import FreezeController
from help_overlay import HelpOverlay
from delay_slider import DelaySlider
from panels import PanelCollection
from tutorial import SUCCESS_MESSAGE, TUTORIAL_MOVE_MIN_FRAME_FRACTION, Tutorial
from test_panel_preview import add_panel, samples
import test_frozen_content as preview_support
from ui import Layout


class TutorialTests(unittest.TestCase):
    def setUp(self):
        self.scene = PanelCollection()
        self.tutorial = Tutorial(self.scene)
        self.help = HelpOverlay()

    def tick(self, hands=None, paused=False):
        if not paused:
            self.tutorial.ensure_tool(self.scene)
            self.scene.update(samples() if hands is None else hands, 640, 480)
        self.tutorial.observe(self.scene, (640, 480), paused=paused, now=10)

    def ready(self):
        for _ in range(4):
            self.tick()

    def create(self):
        self.assertTrue(self.tutorial.start(self.scene))
        self.ready()
        self.assertEqual(self.scene.tool, "CREATE")
        self.tick(samples(True))
        self.tick(samples())
        self.assertEqual(self.tutorial.state, "MOVE")
        return self.scene.active_panel

    def drag(self, dx):
        self.ready()
        self.assertEqual(self.scene.tool, "MOVE")
        self.tick(samples(False, (200, 200), (500, 300)))
        self.tick(samples(True, (200, 200), (500, 300)))
        with patch("interaction.DRAG_SMOOTHING", 1.0):
            self.tick(samples(True, (200 + dx, 200), (500, 300)))
        self.tick(samples(False, (200 + dx, 200), (500, 300)))

    def input(self, key=-1, hands=None):
        return self.tutorial.handle_input(key, hands or [], self.scene, self.help, 640, 480)

    def test_real_create_completed_move_and_successful_freeze_complete_tutorial(self):
        panel = self.create()
        self.drag(60)
        self.assertEqual(self.tutorial.state, "FREEZE")
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.ready()
        self.assertEqual(self.scene.tool, "SELECT")
        raw = preview_support.frame((10, 20, 30))
        freeze = FreezeController()
        freeze.update([], self.scene, now=10)
        self.assertTrue(freeze.apply(self.scene, raw, keyboard=True))
        self.tutorial.observe(self.scene, (640, 480), now=10)
        self.assertEqual(self.tutorial.state, "FREE")
        self.assertEqual(self.scene.panels, [panel])
        self.assertEqual(panel.content_mode, "FROZEN")
        self.assertTrue(np.all(panel.frozen_image == (10, 20, 30)))
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.assertEqual(self.scene.notice, SUCCESS_MESSAGE)
        self.scene.update(samples(), 640, 480)
        self.assertEqual(self.tutorial.instruction_override(self.scene), SUCCESS_MESSAGE)
        self.tutorial.observe(self.scene, (640, 480), now=13)
        self.assertEqual(self.scene.notice, "")
        self.assertIsNone(self.tutorial.instruction_override(self.scene))

    def test_buttons_and_key_presses_alone_do_not_advance(self):
        self.input(ord("u"))
        for key in (ord("n"), ord("m"), ord("f")):
            self.input(key)
            self.ready()
        self.assertEqual(self.tutorial.state, "CREATE")
        self.assertFalse(self.scene.panels)
        # A failed small placement is not a PLACED event.
        self.tick(samples(True, (100, 100), (110, 110)))
        self.tick(samples())
        self.assertEqual(self.tutorial.state, "CREATE")
        self.assertFalse(self.scene.panels)

    def test_completion_feedback_and_welcome_do_not_reopen_after_clear(self):
        self.create()
        self.drag(60)
        self.ready()
        self.scene.toggle_frozen(preview_support.frame())
        self.tutorial.observe(self.scene, (640, 480), now=10)
        self.scene.reset()
        self.tutorial.observe(self.scene, (640, 480), now=10.1)
        self.assertFalse(self.tutorial.showing_card)
        self.assertEqual(self.tutorial.state, "FREE")
        self.assertIsNone(self.tutorial.instruction_override(self.scene))

    def test_move_requires_completed_displacement_at_named_relative_threshold(self):
        self.create()
        threshold = hypot(640, 480) * TUTORIAL_MOVE_MIN_FRAME_FRACTION
        self.drag(threshold - 1)
        self.assertEqual(self.tutorial.state, "MOVE")
        self.ready()
        center_x = (self.scene.rectangle.left + self.scene.rectangle.right) / 2
        self.tick(samples(False, (center_x, 200), (550, 300)))
        self.tick(samples(True, (center_x, 200), (550, 300)))
        with patch("interaction.DRAG_SMOOTHING", 1.0):
            self.tick(samples(True, (center_x + threshold, 200), (550, 300)))
        self.assertEqual(self.tutorial.state, "MOVE", "Holding a moved pinch is not completion")
        self.tick(samples(False, (center_x + threshold, 200), (550, 300)))
        self.assertEqual(self.tutorial.state, "FREEZE")

    def test_controller_loss_and_escape_rollback_do_not_complete_move(self):
        for cancel in ("LOSS", "ESCAPE"):
            self.setUp()
            self.create()
            self.ready()
            self.tick(samples(False, (200, 200), (500, 300)))
            self.tick(samples(True, (200, 200), (500, 300)))
            with patch("interaction.DRAG_SMOOTHING", 1.0):
                self.tick(samples(True, (280, 200), (500, 300)))
            if cancel == "LOSS":
                self.tick([])
            else:
                self.scene.cancel_edit()
                self.tutorial.observe(self.scene, (640, 480), now=10)
            self.assertEqual(self.tutorial.state, "MOVE")

    def test_failed_buffering_freeze_does_not_complete(self):
        panel = self.create()
        self.drag(60)
        self.ready()
        panel.source_mode = "DELAYED"
        self.assertFalse(self.scene.toggle_frozen(preview_support.frame()))
        self.tutorial.observe(self.scene, (640, 480), now=10)
        self.assertEqual(self.tutorial.state, "FREEZE")
        self.assertIsNone(panel.frozen_image)

    def test_existing_panels_are_never_cleared_or_replaced_by_start(self):
        panel = add_panel(self.scene)
        self.scene.toggle_frozen(preview_support.frame())
        frozen = panel.frozen_image
        self.assertFalse(self.tutorial.start(self.scene))
        self.assertEqual(self.scene.panels, [panel])
        self.assertIs(panel.frozen_image, frozen)
        self.assertIn("empty workspace", self.scene.notice)

    def test_welcome_fresh_pinch_arming_and_free_play_dismissal(self):
        box = Layout(640, 480).tutorial_buttons["START"]
        point = ((box.left + box.right) / 2, (box.top + box.bottom) / 2)
        self.assertIsNone(self.input(hands=samples(True, point)))
        self.input(hands=samples(False, (500, 200)))
        self.input(hands=samples(True, (500, 200)))
        self.assertIsNone(self.input(hands=samples(True, point)))
        self.input(hands=samples(False, point))
        self.assertEqual(self.input(hands=samples(True, point)), "CONSUMED")
        self.assertEqual(self.tutorial.state, "CREATE")
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.input(ord("g"))
        self.scene.reset()
        self.tutorial.observe(self.scene, (640, 480), now=10)
        self.assertEqual(self.tutorial.state, "FREE")

    def test_skip_cancels_draft_and_preserves_committed_movement_and_crop(self):
        self.tutorial.start(self.scene)
        self.ready()
        self.tick(samples(True))
        self.tutorial.skip(self.scene)
        self.assertFalse(self.scene.panels)
        self.assertFalse(self.scene.creation_mode)
        panel = self.create()
        self.ready()
        self.scene.toggle_frozen(preview_support.frame((10, 20, 30)))
        frozen = panel.frozen_image
        self.tick(samples(False, (200, 200), (500, 300)))
        self.tick(samples(True, (200, 200), (500, 300)))
        self.tick(samples(True, (280, 200), (500, 300)))
        current_box = panel.rectangle
        self.tutorial.skip(self.scene)
        self.assertEqual(self.tutorial.state, "FREE")
        self.assertEqual(panel.rectangle, current_box)
        self.assertIs(panel.frozen_image, frozen)
        self.assertEqual(self.scene.tool, "SELECT")
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")

    def test_help_pauses_events_and_resume_restores_the_step_tool(self):
        self.create()
        self.ready()
        self.tick(samples(False, (200, 200), (500, 300)))
        self.tick(samples(True, (200, 200), (500, 300)))
        with patch("interaction.DRAG_SMOOTHING", 1.0):
            self.tick(samples(True, (280, 200), (500, 300)))
        self.help.handle_key(ord("h"), self.scene, DelaySlider(), FilterToolbar(), FreezeController())
        self.tick(paused=True)
        self.assertEqual(self.tutorial.state, "MOVE")
        self.help.handle_key(ord("h"), self.scene, DelaySlider(), FilterToolbar(), FreezeController())
        self.ready()
        self.assertEqual(self.scene.tool, "MOVE")
        self.assertEqual(self.tutorial.state, "MOVE")

    def test_help_entry_uses_shared_hitbox_and_refuses_nonempty_workspace(self):
        panel = add_panel(self.scene)
        self.help.visible = True
        box = self.help.tutorial_buttons(640, 480)["START"]
        self.assertEqual(self.tutorial.buttons(640, 480, self.help)["START"], box)
        point = ((box.left + box.right) / 2, (box.top + box.bottom) / 2)
        self.input(hands=samples(False, point))
        self.input(hands=samples(True, point))
        self.assertTrue(self.help.visible)
        self.assertEqual(self.scene.panels, [panel])
        self.assertIn("empty workspace", self.help.notice)
        self.scene.reset()
        self.input(ord("u"))
        self.assertFalse(self.help.visible)
        self.assertEqual(self.tutorial.state, "CREATE")

    def test_skip_available_in_help_and_between_step_release_gates(self):
        panel = self.create()
        self.help.visible = True
        boxes = self.tutorial.buttons(640, 480, self.help)
        self.assertIn("SKIP", boxes)
        self.input(ord("g"))
        self.assertEqual(self.tutorial.state, "FREE")
        self.assertEqual(self.scene.panels, [panel])
        self.assertTrue(self.help.visible)
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")

    def test_recovery_keeps_step_or_restarts_creation_when_panel_is_cleared(self):
        panel = self.create()
        self.scene.prepare_camera_reconnect()
        self.tutorial.on_recovery(self.scene)
        self.scene.finish_camera_reconnect((640, 480), (640, 480))
        self.tutorial.on_recovery(self.scene)
        self.assertEqual(self.tutorial.state, "MOVE")
        self.assertEqual(self.scene.panels, [panel])
        self.ready()
        self.assertEqual(self.scene.tool, "MOVE")
        self.scene.finish_camera_reconnect((640, 480), (1280, 720))
        self.tutorial.on_recovery(self.scene)
        self.assertEqual(self.tutorial.state, "CREATE")
        self.assertIsNone(self.tutorial.panel_id)
        self.assertFalse(self.scene.panels)

    def test_stale_completed_events_are_not_replayed_after_help_or_start(self):
        self.create()
        self.ready()
        for hands in (samples(False, (200, 200), (500, 300)), samples(True, (200, 200), (500, 300))):
            self.scene.update(hands, 640, 480)
        with patch("interaction.DRAG_SMOOTHING", 1.0):
            self.scene.update(samples(True, (280, 200), (500, 300)), 640, 480)
        self.scene.update(samples(False), 640, 480)
        self.assertTrue(self.scene.events)
        self.tutorial.observe(self.scene, (640, 480), paused=True, now=10)
        self.tutorial.observe(self.scene, (640, 480), now=10)
        self.assertEqual(self.tutorial.state, "MOVE")


class TutorialPreviewTests(unittest.TestCase):
    def preview(self, scene, tutorial, keys, gestures, **kwargs):
        with patch("tutorial.Tutorial", return_value=tutorial):
            return preview_support.FrozenPreviewTests().preview(
                scene, [preview_support.frame((index, 40, 90)) for index in range(len(keys))],
                keys, gesture_frames=gestures, **kwargs)

    def journey(self):
        create_open = samples(False, (100, 120), (280, 260))
        create_pinch = samples(True, (100, 120), (280, 260))
        move_open = samples(False, (180, 180), (500, 300))
        move_pinch = samples(True, (180, 180), (500, 300))
        moved = samples(True, (250, 180), (500, 300))
        return [create_open] * 3 + [create_pinch, create_open] + [create_open] * 2 + [move_open, move_pinch, moved,
                                                                                               move_open, move_open, move_open]

    def test_complete_journey_uses_actual_freeze_button_and_clean_raw_sources(self):
        scene = PanelCollection()
        tutorial = Tutorial(scene)
        box = Layout(640, 480).tutorial_buttons["FREEZE"]
        point = ((box.left + box.right) / 2, (box.top + box.bottom) / 2)
        gestures = self.journey() + [samples(False, point), samples(True, point), samples(True, point)]
        keys = [ord("u")] + [-1] * (len(gestures) - 2) + [ord("q")]
        with patch("interaction.DRAG_SMOOTHING", 1.0):
            inputs, _, labels = self.preview(scene, tutorial, keys, gestures)
        self.assertEqual(tutorial.state, "FREE")
        self.assertEqual(len(scene.panels), 1)
        self.assertEqual(scene.tool, "SELECT")
        panel = scene.active_panel
        self.assertEqual(panel.content_mode, "FROZEN")
        self.assertTrue(np.all(panel.frozen_image == (14, 40, 90)))
        self.assertTrue(any("Tutorial complete!" in label for label in labels))
        for index, image in enumerate(inputs):
            self.assertTrue(np.all(image == (index, 40, 90)))
        self.assertFalse(scene.history.frames)

    def test_c_on_release_cannot_turn_a_recovery_cancellation_into_move_completion(self):
        scene = PanelCollection()
        tutorial = Tutorial(scene)
        gestures = self.journey()[:10] + [samples(), samples()]
        keys = [ord("u")] + [-1] * 9 + [ord("c"), ord("q")]
        pending = MagicMock(poll=MagicMock(return_value=None))
        def recover(camera, *args):
            camera.release()
            return pending
        with patch("interaction.DRAG_SMOOTHING", 1.0):
            self.preview(scene, tutorial, keys, gestures, recover=recover)
        self.assertEqual(tutorial.state, "MOVE")
        self.assertEqual(len(scene.panels), 1)
        self.assertFalse(scene.events)
        pending.close.assert_called_once()

    def test_irrelevant_keys_cannot_skip_steps_or_clear_the_tutorial_panel(self):
        scene = PanelCollection()
        tutorial = Tutorial(scene)
        gestures = self.journey()[:7] + [samples()] * 7
        keys = [ord("u")] + [-1] * 6 + [ord("f"), ord("r"), ord("n"), ord("s"), ord("1"), ord("t"), ord("q")]
        self.preview(scene, tutorial, keys, gestures)
        self.assertEqual(tutorial.state, "MOVE")
        self.assertEqual(len(scene.panels), 1)
        self.assertEqual(scene.active_panel.content_mode, "LIVE")
        self.assertEqual(scene.active_panel.filter_name, "ORIGINAL")

    def test_c_recovery_is_available_from_help_during_tutorial(self):
        scene = PanelCollection()
        tutorial = Tutorial(scene)
        pending = MagicMock(poll=MagicMock(return_value=None))
        def recover(camera, *args):
            camera.release()
            return pending
        self.preview(scene, tutorial, [ord("u"), ord("h"), ord("c"), ord("q")],
                     [samples()] * 4, recover=recover)
        pending.close.assert_called_once()
        self.assertEqual(tutorial.state, "CREATE")
        self.assertFalse(scene.panels)
        self.assertFalse(scene.history.frames)

    def test_g_skip_keeps_committed_drag_and_r_does_not_reopen_welcome(self):
        scene = PanelCollection()
        tutorial = Tutorial(scene)
        saved = {}
        original_reset = scene.reset
        def reset():
            saved["panels"] = list(scene.panels)
            original_reset()
        gestures = self.journey()[:10] + [samples(True, (250, 180), (500, 300))] + [samples()] * 3
        keys = [ord("u")] + [-1] * 9 + [ord("g"), -1, ord("r"), ord("q")]
        with patch("interaction.DRAG_SMOOTHING", 1.0), patch.object(scene, "reset", side_effect=reset):
            self.preview(scene, tutorial, keys, gestures)
        self.assertEqual(len(saved["panels"]), 1)
        self.assertEqual(saved["panels"][0].rectangle.left, 170)
        self.assertEqual(saved["panels"][0].content_mode, "LIVE")
        self.assertFalse(scene.panels)
        self.assertEqual(tutorial.state, "FREE")
        self.assertFalse(tutorial.showing_card)

    def test_no_tracking_never_initializes_tutorial(self):
        with patch("tutorial.Tutorial", side_effect=AssertionError("Tutorial initialized")):
            preview_support.FrozenPreviewTests().preview(None, [preview_support.frame()], [ord("q")], tracking=False)


if __name__ == "__main__":
    unittest.main()
