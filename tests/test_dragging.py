"""One-hand dragging checks using gesture samples, without a camera."""

from types import SimpleNamespace
from unittest.mock import patch
import unittest

from interaction import Rectangle, RectangleInteraction


WIDTH = 1280
HEIGHT = 720


def hand(track_id, point, pinching=False):
    return SimpleNamespace(track_id=track_id, pinch_point=point, is_pinching=pinching)


class RectangleDraggingTests(unittest.TestCase):
    def setUp(self):
        self.interaction = RectangleInteraction()
        self.update([hand(1, (200, 200), True), hand(2, (600, 500), True)])
        self.update([hand(1, (200, 200)), hand(2, (600, 500))])
        self.assertEqual(self.interaction.state, "PLACED")

    def update(self, hands):
        self.interaction.update(hands, WIDTH, HEIGHT)

    def grab(self, point=(350, 300)):
        self.update([hand(1, point, True)])
        self.assertEqual(self.interaction.state, "DRAGGING")

    def test_grab_requires_an_observed_open_to_pinch_transition_inside(self):
        original = self.interaction.rectangle
        self.update([hand(7, (350, 300), True)])
        self.assertEqual(self.interaction.state, "PLACED")
        self.update([hand(7, (350, 300))])
        self.update([hand(7, (350, 300), True)])
        self.assertEqual(self.interaction.state, "DRAGGING")
        self.assertEqual(self.interaction.rectangle, original)

    def test_pinching_outside_then_entering_does_not_grab(self):
        self.update([hand(1, (100, 300), True)])
        self.update([hand(1, (350, 300), True)])
        self.assertEqual(self.interaction.state, "PLACED")
        self.update([hand(1, (350, 300))])
        self.grab()

    def test_held_creation_pinch_cannot_immediately_become_a_grab(self):
        interaction = RectangleInteraction()
        interaction.update([hand(1, (200, 200), True), hand(2, (600, 500), True)], WIDTH, HEIGHT)
        interaction.update([hand(1, (200, 200)), hand(2, (600, 500), True)], WIDTH, HEIGHT)
        interaction.update([hand(2, (350, 300), True)], WIDTH, HEIGHT)
        self.assertEqual(interaction.state, "PLACED")

    def test_grab_preserves_offset_and_does_not_snap(self):
        original = self.interaction.rectangle
        self.grab((350, 300))
        self.assertEqual(self.interaction.rectangle, original)
        # Isolate offset geometry from smoothing: the grab offset is (150, 100).
        with patch("interaction.DRAG_SMOOTHING", 1.0):
            self.update([hand(1, (500, 400), True)])
        self.assertEqual(self.interaction.rectangle, Rectangle(350, 300, 750, 600))

    def test_drag_uses_light_position_smoothing(self):
        self.grab()
        self.update([hand(1, (450, 350), True)])
        box = self.interaction.rectangle
        self.assertTrue(200 < box.left < 300)
        self.assertTrue(200 < box.top < 250)

    def test_drag_preserves_dimensions_and_clamps_the_whole_rectangle(self):
        self.grab()
        with patch("interaction.DRAG_SMOOTHING", 1.0):
            self.update([hand(1, (-1000, -1000), True)])
            self.assertEqual(self.interaction.rectangle, Rectangle(0, 0, 400, 300))
            self.update([hand(1, (3000, 3000), True)])
            self.assertEqual(self.interaction.rectangle,
                             Rectangle(WIDTH - 401, HEIGHT - 301, WIDTH - 1, HEIGHT - 1))
        self.assertEqual(self.interaction.rectangle.width, 400)
        self.assertEqual(self.interaction.rectangle.height, 300)

    def test_release_keeps_current_position_without_smoothing_tail(self):
        self.grab()
        self.update([hand(1, (450, 350), True)])
        placed = self.interaction.rectangle
        self.update([hand(1, (1000, 600))])
        self.assertEqual(self.interaction.state, "PLACED")
        self.assertEqual(self.interaction.rectangle, placed)
        self.update([hand(1, (800, 400))])
        self.assertEqual(self.interaction.rectangle, placed)

    def test_each_new_grab_resets_smoothing_at_the_current_rectangle(self):
        self.grab()
        self.update([hand(1, (600, 500), True)])
        self.update([hand(1, (600, 500))])
        placed = self.interaction.rectangle
        new_point = (placed.left + 20, placed.top + 20)
        self.grab(new_point)
        self.update([hand(1, new_point, True)])
        self.assertEqual(self.interaction.rectangle, placed)

    def test_hand_loss_stops_without_movement_and_requires_release(self):
        self.grab()
        placed = self.interaction.rectangle
        self.update([hand(2, (400, 400), True)])
        self.assertEqual(self.interaction.state, "PLACED")
        self.assertEqual(self.interaction.rectangle, placed)
        self.update([hand(2, (450, 400), True)])
        self.assertEqual(self.interaction.state, "PLACED")
        self.assertEqual(self.interaction.rectangle, placed)
        self.update([])  # An absent hand is not evidence of release.
        self.update([hand(2, (450, 400), True)])
        self.assertEqual(self.interaction.state, "PLACED")
        self.update([hand(2, (450, 400))])
        self.update([hand(2, (450, 400), True)])
        self.assertEqual(self.interaction.state, "DRAGGING")

    def test_returning_controller_still_pinching_cannot_regrab(self):
        self.grab()
        self.update([])
        self.update([hand(1, (350, 300), True)])
        self.assertEqual(self.interaction.state, "PLACED")
        self.update([hand(1, (350, 300))])
        self.grab()

    def test_other_hand_cannot_take_over_an_active_or_just_released_drag(self):
        self.grab()
        placed = self.interaction.rectangle
        self.update([hand(1, (350, 300), True), hand(2, (450, 400))])
        self.update([hand(2, (500, 400), True), hand(1, (350, 300), True)])
        self.assertEqual(self.interaction.rectangle, placed)
        self.update([hand(1, (350, 300)), hand(2, (500, 400), True)])
        self.assertEqual(self.interaction.state, "PLACED")
        self.update([hand(2, (550, 450), True)])
        self.assertEqual(self.interaction.state, "PLACED")
        self.assertEqual(self.interaction.rectangle, placed)

    def test_result_reordering_preserves_drag_ownership(self):
        self.grab()
        with patch("interaction.DRAG_SMOOTHING", 1.0):
            self.update([hand(2, (450, 400), True), hand(1, (450, 350), True)])
        self.assertEqual(self.interaction.rectangle, Rectangle(300, 250, 700, 550))

    def test_simultaneous_grabs_choose_lowest_track_id_regardless_of_order(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                self.setUp()
                hands = [hand(1, (350, 300), True), hand(2, (450, 400), True)]
                self.update(hands[::-1] if reverse else hands)
                with patch("interaction.DRAG_SMOOTHING", 1.0):
                    self.update([hand(2, (450, 450), True), hand(1, (450, 300), True)])
                self.assertEqual(self.interaction.rectangle, Rectangle(300, 200, 700, 500))

    def test_r_clears_drag_and_requires_release_before_creation(self):
        self.grab()
        self.interaction.reset()
        self.update([hand(1, (350, 300), True), hand(2, (450, 400), True)])
        self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
        self.assertIsNone(self.interaction.rectangle)
        self.update([hand(1, (200, 200)), hand(2, (600, 500))])
        self.update([hand(1, (200, 200), True), hand(2, (600, 500), True)])
        self.assertEqual(self.interaction.state, "CREATING")

    def test_c_cancels_drag_preserves_size_and_requires_both_hands_open(self):
        self.grab()
        self.update([hand(1, (450, 350), True)])
        placed = self.interaction.rectangle
        self.interaction.prepare_camera_reconnect()
        self.interaction.finish_camera_reconnect((WIDTH, HEIGHT), (WIDTH, HEIGHT))
        self.update([hand(1, (450, 350), True)])
        self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
        self.assertEqual(self.interaction.rectangle, placed)
        self.update([hand(1, (450, 350))])
        self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
        self.update([hand(1, (450, 350)), hand(2, (600, 500))])
        self.assertEqual(self.interaction.state, "PLACED")
        self.assertEqual(self.interaction.rectangle, placed)
        self.grab((placed.left + 50, placed.top + 50))

    def test_c_still_clears_dragged_rectangle_if_frame_dimensions_change(self):
        self.grab()
        self.interaction.prepare_camera_reconnect()
        self.interaction.finish_camera_reconnect((WIDTH, HEIGHT), (640, 480))
        self.assertIsNone(self.interaction.rectangle)
        self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")

    def test_smaller_frame_translates_a_fitting_rectangle_without_resizing(self):
        self.interaction.update([], 1000, 600)
        self.interaction.update([], 500, 400)
        self.assertEqual(self.interaction.rectangle, Rectangle(99, 99, 499, 399))
        self.assertEqual(self.interaction.rectangle.width, 400)
        self.assertEqual(self.interaction.rectangle.height, 300)


if __name__ == "__main__":
    unittest.main()
