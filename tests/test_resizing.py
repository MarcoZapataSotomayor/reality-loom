"""Resize geometry and content checks using synthetic hands and BGR frames."""

from types import SimpleNamespace
from unittest.mock import patch
import unittest

import cv2
import numpy as np

from freeze_control import FreezeController
from interaction import MIN_RECTANGLE_SIZE_PIXELS, RESIZE_HIT_RADIUS_PIXELS, Rectangle, RectangleInteraction


WIDTH, HEIGHT = 640, 480


def hand(track_id, point, pinching=True, fist=False):
    return SimpleNamespace(track_id=track_id, pinch_point=point, is_pinching=pinching,
                           center=(50, 50), is_fist=fist, is_open_hand=not pinching and not fist)


def corners(pinching=True):
    return [hand(1, (100, 120), pinching), hand(2, (300, 280), pinching)]


class RectangleResizingTests(unittest.TestCase):
    def setUp(self):
        self.interaction = RectangleInteraction()
        self.update(corners())
        self.update(corners(False))
        self.assertEqual(self.interaction.state, "PLACED")

    def update(self, hands):
        self.interaction.update(hands, WIDTH, HEIGHT)

    def start_resize(self, hands=None):
        self.update(corners() if hands is None else hands)
        self.assertEqual(self.interaction.state, "RESIZING")

    def test_both_diagonal_pairs_activate_and_beat_drag_start(self):
        for points in (((100, 120), (300, 280)), ((300, 120), (100, 280))):
            with self.subTest(points=points):
                self.setUp()
                original = self.interaction.rectangle
                self.start_resize([hand(1, points[0]), hand(2, points[1])])
                self.assertEqual(self.interaction.rectangle, original)

    def test_hit_radius_accepts_nearby_pointers_but_not_distant_ones(self):
        radius = RESIZE_HIT_RADIUS_PIXELS
        self.update([hand(1, (100 - radius - 1, 120)), hand(2, (300, 280))])
        self.assertNotEqual(self.interaction.state, "RESIZING")
        self.setUp()
        self.start_resize([hand(1, (100 - radius, 120)), hand(2, (300 + radius, 280))])

    def test_adjacent_corners_or_one_released_pinch_do_not_resize(self):
        self.update([hand(1, (100, 120)), hand(2, (300, 120))])
        self.assertNotEqual(self.interaction.state, "RESIZING")
        self.setUp()
        self.update([hand(1, (100, 120)), hand(2, (300, 280), False)])
        self.assertEqual(self.interaction.state, "DRAGGING")

    def test_drag_can_upgrade_without_moving_the_rectangle_on_entry(self):
        self.update([hand(1, (106, 126)), hand(2, (294, 274), False)])
        self.assertEqual(self.interaction.state, "DRAGGING")
        original = self.interaction.rectangle
        self.update([hand(2, (294, 274)), hand(1, (106, 126))])
        self.assertEqual(self.interaction.state, "RESIZING")
        self.assertEqual(self.interaction.rectangle, original)
        with patch("interaction.RESIZE_SMOOTHING", 1.0):
            self.update([hand(1, (96, 116)), hand(2, (314, 294))])
        self.assertEqual(self.interaction.rectangle, Rectangle(90, 110, 320, 300))

    def test_drag_elsewhere_does_not_upgrade_when_only_second_pointer_hits_corner(self):
        self.update([hand(1, (180, 190)), hand(2, (300, 280), False)])
        self.update([hand(1, (180, 190)), hand(2, (300, 280))])
        self.assertEqual(self.interaction.state, "DRAGGING")

    def test_resize_preserves_corner_offsets_and_has_no_initial_jump(self):
        original = self.interaction.rectangle
        self.start_resize([hand(1, (106, 124)), hand(2, (296, 274))])
        self.assertEqual(self.interaction.rectangle, original)
        self.update([hand(1, (106, 124)), hand(2, (296, 274))])
        self.assertEqual(self.interaction.rectangle, original)
        with patch("interaction.RESIZE_SMOOTHING", 1.0):
            self.update([hand(1, (96, 114)), hand(2, (326, 294))])
        self.assertEqual(self.interaction.rectangle, Rectangle(90, 110, 330, 300))

    def test_resizing_uses_light_smoothing(self):
        self.start_resize()
        self.update([hand(1, (80, 100)), hand(2, (400, 400))])
        box = self.interaction.rectangle
        self.assertTrue(80 < box.left < 100)
        self.assertTrue(300 < box.right < 400)
        self.assertTrue(280 < box.bottom < 400)

    def test_corner_roles_stay_bound_through_result_reordering(self):
        self.start_resize([hand(2, (100, 280)), hand(1, (300, 120))])
        with patch("interaction.RESIZE_SMOOTHING", 1.0):
            self.update([hand(1, (400, 100)), hand(2, (80, 350))])
        self.assertEqual(self.interaction.rectangle, Rectangle(80, 100, 400, 350))

    def test_bounds_and_independent_width_height_changes(self):
        self.start_resize()
        with patch("interaction.RESIZE_SMOOTHING", 1.0):
            self.update([hand(1, (-100, -100)), hand(2, (2000, 2000))])
            self.assertEqual(self.interaction.rectangle, Rectangle(0, 0, WIDTH - 1, HEIGHT - 1))
            self.update([hand(1, (100, 120)), hand(2, (180, 400))])
        self.assertEqual(self.interaction.rectangle.width, 80)
        self.assertEqual(self.interaction.rectangle.height, 280)

    def test_crossing_stops_at_minimum_without_flipping_roles(self):
        self.start_resize()
        with patch("interaction.RESIZE_SMOOTHING", 1.0):
            self.update([hand(1, (400, 400)), hand(2, (0, 0))])
            box = self.interaction.rectangle
            self.assertEqual(box.width, MIN_RECTANGLE_SIZE_PIXELS)
            self.assertEqual(box.height, MIN_RECTANGLE_SIZE_PIXELS)
            self.assertTrue(0 <= box.left < box.right < WIDTH)
            self.assertTrue(0 <= box.top < box.bottom < HEIGHT)
            self.update([hand(1, (80, 100)), hand(2, (400, 350))])
        self.assertEqual(self.interaction.rectangle, Rectangle(80, 100, 400, 350))

    def test_releasing_either_hand_keeps_last_geometry_and_blocks_drag_fallback(self):
        for released_id in (1, 2):
            with self.subTest(released_id=released_id):
                self.setUp()
                self.start_resize()
                self.update([hand(1, (90, 110)), hand(2, (310, 290))])
                last = self.interaction.rectangle
                self.update([hand(1, (0, 0), released_id != 1),
                             hand(2, (500, 400), released_id != 2)])
                self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
                self.assertEqual(self.interaction.rectangle, last)
                self.update(corners())
                self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")

    def test_loss_or_replacement_keeps_geometry_and_requires_both_released(self):
        for hands in ([], [hand(1, (100, 120))], [hand(1, (100, 120)), hand(3, (300, 280))]):
            with self.subTest(ids=[sample.track_id for sample in hands]):
                self.setUp()
                self.start_resize()
                last = self.interaction.rectangle
                self.update(hands)
                self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
                self.assertEqual(self.interaction.rectangle, last)
                self.update([hand(1, (100, 120), False)])
                self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
                self.update(corners(False))
                self.assertEqual(self.interaction.state, "PLACED")
                self.start_resize()

    def test_valid_resize_cancels_a_ready_fist_and_ignores_f(self):
        controller = FreezeController()
        raw = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        controller.update(corners(False), self.interaction, now=0.0)
        holding = [hand(1, (50, 50), False, fist=True), hand(2, (300, 280), False)]
        self.update(holding)
        controller.update(holding, self.interaction, now=1.0)
        self.start_resize([hand(1, (100, 120), fist=True), hand(2, (300, 280))])
        controller.update([hand(1, (100, 120), fist=True), hand(2, (300, 280))],
                          self.interaction, now=1.81)
        self.assertFalse(controller.apply(self.interaction, raw, keyboard=True))
        self.assertIsNone(self.interaction.frozen_image)
        self.assertFalse(self.interaction.toggle_frozen(raw))
        self.assertIn("RESIZING", self.interaction.state)

    def test_r_clears_resize_and_requires_rearming_before_creation(self):
        self.start_resize()
        self.interaction.reset()
        self.assertIsNone(self.interaction.rectangle)
        self.update(corners())
        self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
        self.update(corners(False))
        self.update(corners())
        self.assertEqual(self.interaction.state, "CREATING")

    def test_c_preserves_resized_geometry_and_original_crop_only_at_same_frame_size(self):
        raw = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        self.interaction.toggle_frozen(raw)
        original = self.interaction.frozen_image
        self.start_resize()
        self.update([hand(1, (80, 100)), hand(2, (400, 350))])
        last = self.interaction.rectangle
        self.interaction.prepare_camera_reconnect()
        self.interaction.finish_camera_reconnect((WIDTH, HEIGHT), (WIDTH, HEIGHT))
        self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
        self.assertEqual(self.interaction.rectangle, last)
        self.assertIs(self.interaction.frozen_image, original)
        self.interaction.finish_camera_reconnect((WIDTH, HEIGHT), (1280, 720))
        self.assertIsNone(self.interaction.rectangle)
        self.assertIsNone(self.interaction.frozen_image)


class ResizedContentTests(unittest.TestCase):
    def test_crossed_pointers_do_not_flip_the_frozen_image(self):
        interaction = RectangleInteraction()
        for pinching in (True, False):
            interaction.update(corners(pinching), WIDTH, HEIGHT)
        raw = np.arange(HEIGHT * WIDTH * 3, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3)
        interaction.toggle_frozen(raw)
        original = interaction.frozen_image
        interaction.update(corners(), WIDTH, HEIGHT)
        with patch("interaction.RESIZE_SMOOTHING", 1.0):
            interaction.update([hand(1, (400, 400)), hand(2, (0, 0))], WIDTH, HEIGHT)
        box = interaction.rectangle
        self.assertEqual(box.pixel_size(), (40, 40))
        preview = np.zeros_like(raw)
        interaction.composite_frozen(preview)
        left, top = round(box.left), round(box.top)
        np.testing.assert_array_equal(preview[top:top + 40, left:left + 40],
                                      cv2.resize(original, (40, 40)))

    def test_every_scale_uses_original_crop_and_never_recaptures(self):
        interaction = RectangleInteraction()
        for pinching in (True, False):
            interaction.update(corners(pinching), WIDTH, HEIGHT)
        raw = np.arange(HEIGHT * WIDTH * 3, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3)
        interaction.toggle_frozen(raw)
        original = interaction.frozen_image
        original_pixels = original.copy()
        interaction.update(corners(), WIDTH, HEIGHT)
        with patch("interaction.RESIZE_SMOOTHING", 1.0), \
                patch.object(cv2, "resize", wraps=cv2.resize) as resizing:
            for size in ((300, 200), (80, 240), (200, 160)):
                interaction.update([hand(1, (100, 120)), hand(2, (100 + size[0], 120 + size[1]))],
                                   WIDTH, HEIGHT)
                live = np.full_like(raw, 77)
                expected = live.copy()
                expected[120:120 + size[1], 100:100 + size[0]] = cv2.resize(original_pixels, size)
                interaction.composite_frozen(live)
                np.testing.assert_array_equal(live, expected)
                self.assertIs(interaction.frozen_image, original)
            # Calls from expected-image construction use original_pixels; actual
            # rendering calls must always use the one retained original object.
            render_sources = [call.args[0] for call in resizing.call_args_list
                              if call.args[0] is not original_pixels]
            self.assertEqual(len(render_sources), 2)
            self.assertTrue(all(source is original for source in render_sources))
        np.testing.assert_array_equal(original, original_pixels)

    def test_live_resize_keeps_current_frame_pixels_at_the_new_location(self):
        interaction = RectangleInteraction()
        for pinching in (True, False):
            interaction.update(corners(pinching), WIDTH, HEIGHT)
        interaction.update(corners(), WIDTH, HEIGHT)
        with patch("interaction.RESIZE_SMOOTHING", 1.0):
            interaction.update([hand(1, (80, 100)), hand(2, (400, 350))], WIDTH, HEIGHT)
        live = np.full((HEIGHT, WIDTH, 3), (70, 80, 90), dtype=np.uint8)
        preview = live.copy()
        interaction.composite_frozen(preview)
        self.assertIsNone(interaction.frozen_image)
        np.testing.assert_array_equal(preview, live)


if __name__ == "__main__":
    unittest.main()
