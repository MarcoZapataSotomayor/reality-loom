"""Collection behavior, ownership, and raw-source rendering without a camera."""

from types import SimpleNamespace
from unittest.mock import patch
import unittest

import numpy as np

from filters import apply_filter
from interaction import Rectangle
from panels import MAX_PANELS, PanelCollection


WIDTH, HEIGHT = 640, 480


def hand(track_id, point, pinching=False):
    return SimpleNamespace(track_id=track_id, pinch_point=point, is_pinching=pinching)


def pair(first=(100, 100), second=(300, 300), pinching=False):
    return [hand(1, first, pinching), hand(2, second, pinching)]


class PanelCollectionTests(unittest.TestCase):
    def setUp(self):
        self.scene = PanelCollection()

    def update(self, hands):
        self.scene.update(hands, WIDTH, HEIGHT)

    def release(self):
        self.update(pair())

    def create(self, first=(100, 100), second=(300, 300)):
        if self.scene.panels:
            self.assertTrue(self.scene.begin_creation())
            self.release()
        self.update(pair(first, second, True))
        self.assertEqual(self.scene.state, "CREATING")
        self.update(pair(first, second))
        self.assertEqual(self.scene.state, "PLACED")
        return self.scene.active_panel

    def test_limit_stable_ids_and_one_shared_controller(self):
        controller = self.scene.controller
        ids = [self.create().panel_id for _ in range(MAX_PANELS)]
        self.assertEqual(ids, [1, 2, 3, 4])
        self.assertFalse(self.scene.begin_creation())
        self.assertIn("Limit: 4", self.scene.notice)
        self.assertEqual(len(self.scene.panels), MAX_PANELS)
        self.release()
        self.assertTrue(self.scene.delete_active())
        self.release()
        self.assertEqual(self.create().panel_id, 5)
        self.assertIs(self.scene.controller, controller)

    def test_creation_requires_release_and_preserves_committed_panels(self):
        old = self.create()
        old_geometry = old.rectangle
        self.scene.begin_creation()
        self.update(pair((350, 100), (550, 300), True))
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.assertIsNone(self.scene.rectangle)
        self.release()
        self.update(pair((350, 100), (550, 300), True))
        self.assertEqual(self.scene.state, "CREATING")
        self.assertEqual(old.rectangle, old_geometry)
        self.update(pair((350, 100), (550, 300)))
        self.assertEqual(len(self.scene.panels), 2)
        self.assertEqual(self.scene.active_id, 2)

    def test_escape_cancellation_keeps_existing_geometry_content_and_order(self):
        old = self.create()
        raw = np.full((HEIGHT, WIDTH, 3), 80, dtype=np.uint8)
        self.scene.toggle_frozen(raw)
        original = old.frozen_image
        self.scene.begin_creation()
        self.release()
        self.update(pair((350, 100), (550, 300), True))
        self.assertTrue(self.scene.cancel_creation())
        self.assertEqual([panel.panel_id for panel in self.scene.panels], [old.panel_id])
        self.assertIs(old.frozen_image, original)
        self.assertEqual(self.scene.active_id, old.panel_id)
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.assertFalse(self.scene.cancel_creation())
        self.assertFalse(PanelCollection().cancel_creation())

    def test_failed_creation_or_tracking_loss_does_not_delete_existing_panels(self):
        old = self.create()
        for lose_hand in (False, True):
            with self.subTest(lose_hand=lose_hand):
                self.scene.begin_creation()
                self.release()
                self.update(pair((350, 100), (360, 110), True))
                self.update([] if lose_hand else pair((350, 100), (360, 110)))
                self.assertEqual(self.scene.panels, [old])
                self.assertTrue(self.scene.creation_mode)
                self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
                self.scene.cancel_creation()
                self.release()

    def test_topmost_hit_selects_and_lower_visible_hit_raises_without_jump(self):
        lower = self.create((50, 50), (300, 300))
        upper = self.create((150, 150), (400, 400))
        self.update([hand(7, (200, 200))])
        self.update([hand(7, (200, 200), True)])
        self.assertEqual(self.scene.active_id, upper.panel_id)
        self.assertEqual(self.scene.state, "DRAGGING")
        self.update([hand(7, (200, 200))])
        self.update([hand(7, (80, 80))])
        before = lower.rectangle
        self.update([hand(7, (80, 80), True)])
        self.assertEqual(self.scene.active_id, lower.panel_id)
        self.assertEqual([panel.panel_id for panel in self.scene.panels], [upper.panel_id, lower.panel_id])
        self.assertEqual(lower.rectangle, before)

    def test_operation_owner_stays_stable_and_other_panel_does_not_take_over(self):
        lower = self.create((50, 50), (250, 250))
        upper = self.create((350, 100), (550, 300))
        self.update([hand(1, (400, 180)), hand(2, (100, 100))])
        self.update([hand(1, (400, 180), True), hand(2, (100, 100))])
        before_lower = lower.rectangle
        with patch("interaction.DRAG_SMOOTHING", 1.0):
            self.update([hand(2, (100, 100), True), hand(1, (430, 200), True)])
        self.assertEqual(self.scene.active_id, upper.panel_id)
        self.assertEqual(lower.rectangle, before_lower)
        last_upper = upper.rectangle
        self.update([hand(2, (100, 100), True)])
        self.assertEqual(self.scene.state, "PLACED")
        self.update([hand(2, (120, 120), True)])
        self.assertEqual(self.scene.active_id, upper.panel_id)
        self.assertEqual(upper.rectangle, last_upper)

    def test_active_resize_priority_and_id_roles_survive_reordering(self):
        lower = self.create((50, 50), (550, 400))
        upper = self.create((150, 150), (350, 350))
        self.update(pair((150, 150), (350, 350), True))
        self.assertEqual(self.scene.state, "RESIZING")
        self.assertEqual(self.scene.active_id, upper.panel_id)
        with patch("interaction.RESIZE_SMOOTHING", 1.0):
            self.update([hand(2, (400, 380), True), hand(1, (120, 100), True)])
        self.assertEqual(upper.rectangle, Rectangle(120, 100, 400, 380))
        self.assertEqual(lower.rectangle, Rectangle(50, 50, 550, 400))

    def test_default_filter_inheritance_and_selected_only_filter_and_freeze(self):
        self.assertTrue(self.scene.select_filter("PIXELATE"))
        self.release()
        first = self.create()
        self.assertEqual(first.filter_name, "PIXELATE")
        raw = np.full((HEIGHT, WIDTH, 3), 30, dtype=np.uint8)
        self.scene.toggle_frozen(raw)
        first_image = first.frozen_image
        self.assertTrue(self.scene.select_filter("NEON"))
        self.release()
        second = self.create((350, 100), (550, 300))
        self.assertEqual(second.filter_name, "PIXELATE")
        self.assertEqual(first.filter_name, "NEON")
        self.assertEqual(second.content_mode, "LIVE")
        raw[:] = 90
        self.scene.toggle_frozen(raw)
        self.assertEqual(first.content_mode, "FROZEN")
        self.assertFalse(np.shares_memory(first_image, second.frozen_image))
        self.scene.toggle_frozen(raw)
        self.assertEqual(second.content_mode, "LIVE")
        self.assertIs(first.frozen_image, first_image)
        self.assertTrue(np.all(first_image == 30))

    def test_delete_selects_remaining_topmost_and_r_clears_all_not_default_or_ids(self):
        first = self.create()
        second = self.create()
        self.assertTrue(self.scene.delete_active())
        self.assertEqual(self.scene.active_id, first.panel_id)
        self.assertNotIn(second, self.scene.panels)
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.scene.default_filter = "GRAYSCALE"
        self.scene.reset()
        self.assertEqual(self.scene.panels, [])
        self.assertIsNone(self.scene.active_panel)
        self.assertEqual(self.scene.default_filter, "GRAYSCALE")
        self.release()
        self.assertEqual(self.create().panel_id, 3)

    def test_actions_require_both_releases_and_cannot_immediately_drag_or_resize(self):
        self.create()
        self.scene.apply_action("GRAYSCALE")
        self.update(pair(pinching=True))
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.update([hand(1, (100, 100))])
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.release()
        self.assertEqual(self.scene.state, "PLACED")
        self.assertTrue(self.scene.begin_creation())
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")

    def test_c_cancels_creation_and_operations_preserving_all_data_when_size_matches(self):
        first = self.create()
        second = self.create((350, 100), (550, 300))
        raw = np.full((HEIGHT, WIDTH, 3), 100, dtype=np.uint8)
        self.scene.toggle_frozen(raw)
        crop = second.frozen_image
        self.scene.begin_creation()
        self.release()
        self.update(pair((80, 80), (400, 350), True))
        self.scene.prepare_camera_reconnect()
        self.scene.finish_camera_reconnect((WIDTH, HEIGHT), (WIDTH, HEIGHT))
        self.assertFalse(self.scene.creation_mode)
        self.assertEqual(self.scene.panels, [first, second])
        self.assertIs(second.frozen_image, crop)
        self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
        self.scene.finish_camera_reconnect((WIDTH, HEIGHT), (1280, 720))
        self.assertEqual(self.scene.panels, [])
        self.assertTrue(self.scene.creation_mode)

    def test_c_cancels_drag_or_resize_at_latest_geometry_without_losing_other_panels(self):
        for resize in (False, True):
            with self.subTest(resize=resize):
                self.scene = PanelCollection()
                old = self.create((50, 50), (250, 250))
                active = self.create((350, 100), (550, 300))
                raw = np.full((HEIGHT, WIDTH, 3), 40, dtype=np.uint8)
                self.scene.toggle_frozen(raw)
                image = active.frozen_image
                if resize:
                    hands = pair((350, 100), (550, 300), True)
                    self.update(hands)
                    self.update(pair((330, 80), (570, 330), True))
                    self.assertEqual(self.scene.state, "RESIZING")
                else:
                    self.update([hand(1, (400, 200))])
                    hands = [hand(1, (400, 200), True)]
                    self.update(hands)
                    self.update([hand(1, (430, 220), True)])
                    self.assertEqual(self.scene.state, "DRAGGING")
                last = active.rectangle
                self.scene.prepare_camera_reconnect()
                self.scene.finish_camera_reconnect((WIDTH, HEIGHT), (WIDTH, HEIGHT))
                self.update(hands)
                self.assertEqual(self.scene.state, "WAITING_FOR_RELEASE")
                self.assertEqual(active.rectangle, last)
                self.assertIs(active.frozen_image, image)
                self.assertEqual(old.rectangle, Rectangle(50, 50, 250, 250))

    def test_simultaneous_panel_grabs_choose_lowest_track_id(self):
        left = self.create((50, 50), (250, 250))
        right = self.create((350, 100), (550, 300))
        self.update([hand(7, (100, 100)), hand(3, (450, 200))])
        self.update([hand(7, (100, 100), True), hand(3, (450, 200), True)])
        self.assertEqual(self.scene.active_id, right.panel_id)
        self.assertEqual(self.scene.panels[0], left)
        self.assertEqual(self.scene.state, "DRAGGING")


class PanelRenderingTests(unittest.TestCase):
    def scene_with_two(self, second_filter="ORIGINAL"):
        scene = PanelCollection()
        scene.update(pair((40, 40), (220, 220), True), WIDTH, HEIGHT)
        scene.update(pair((40, 40), (220, 220)), WIDTH, HEIGHT)
        first = scene.active_panel
        scene.begin_creation()
        scene.update(pair(), WIDTH, HEIGHT)
        scene.update(pair((120, 120), (300, 300), True), WIDTH, HEIGHT)
        scene.update(pair((120, 120), (300, 300)), WIDTH, HEIGHT)
        scene.active_panel.filter_name = second_filter
        return scene, first, scene.active_panel

    def test_overlapping_live_panels_each_sample_raw_not_lower_composite(self):
        scene, lower, upper = self.scene_with_two()
        lower.filter_name = "NEON"
        raw = np.full((HEIGHT, WIDTH, 3), (10, 80, 200), dtype=np.uint8)
        display = raw.copy()
        scene.composite(raw, display)
        np.testing.assert_array_equal(display[120:300, 120:300], raw[120:300, 120:300])
        self.assertFalse(np.any(display[50:100, 50:100]))
        np.testing.assert_array_equal(raw, np.full_like(raw, (10, 80, 200)))

    def test_frozen_lower_and_live_upper_remain_independent_and_overlays_are_not_captured(self):
        scene, lower, upper = self.scene_with_two("GRAYSCALE")
        original = np.full((180, 180, 3), (30, 100, 200), dtype=np.uint8)
        lower.frozen_image = original.copy()
        raw = np.full((HEIGHT, WIDTH, 3), (80, 20, 10), dtype=np.uint8)
        display = raw.copy()
        scene.composite(raw, display)
        np.testing.assert_array_equal(display[50:100, 50:100], original[10:60, 10:60])
        np.testing.assert_array_equal(display[120:300, 120:300],
                                      apply_filter(raw[120:300, 120:300], "GRAYSCALE", (180, 180)))
        display[:] = 255  # Simulated overlays must never enter a later capture.
        scene.toggle_frozen(raw)
        np.testing.assert_array_equal(upper.frozen_image, raw[120:300, 120:300])
        np.testing.assert_array_equal(lower.frozen_image, original)

    def test_existing_panels_render_while_new_draft_is_in_progress(self):
        scene, lower, upper = self.scene_with_two()
        lower.frozen_image = np.full((180, 180, 3), 70, dtype=np.uint8)
        scene.begin_creation()
        scene.update(pair(), WIDTH, HEIGHT)
        scene.update(pair((350, 100), (550, 300), True), WIDTH, HEIGHT)
        raw = np.full((HEIGHT, WIDTH, 3), 20, dtype=np.uint8)
        display = raw.copy()
        scene.composite(raw, display)
        self.assertEqual(len(scene.panels), 2)
        self.assertEqual(scene.state, "CREATING")
        self.assertTrue(np.all(display[50:100, 50:100] == 70))


if __name__ == "__main__":
    unittest.main()
