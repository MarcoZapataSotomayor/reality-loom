"""Test rectangle transitions and geometry without a camera or MediaPipe."""

from types import SimpleNamespace
import unittest

from interaction import MIN_RECTANGLE_SIZE_PIXELS, Rectangle, RectangleInteraction


WIDTH = 1280
HEIGHT = 720


def hand(track_id, point, pinching=True):
    return SimpleNamespace(track_id=track_id, pinch_point=point, is_pinching=pinching)


def pair(pinching=True):
    return [hand(1, (200, 200), pinching), hand(2, (600, 500), pinching)]


class RectangleInteractionTests(unittest.TestCase):
    def setUp(self):
        self.interaction = RectangleInteraction()

    def update(self, hands):
        self.interaction.update(hands, WIDTH, HEIGHT)

    def test_creation_requires_two_pinching_hands(self):
        for hands in ([], [hand(1, (200, 200))],
                      [hand(1, (200, 200)), hand(2, (600, 500), False)]):
            self.update(hands)
            self.assertEqual(self.interaction.state, "READY")
            self.assertIsNone(self.interaction.rectangle)
        self.update(pair())
        self.assertEqual(self.interaction.state, "CREATING")
        self.assertEqual(self.interaction.rectangle, Rectangle(200, 200, 600, 500))

    def test_movement_is_smoothed_and_release_keeps_last_preview(self):
        self.update(pair())
        self.update([hand(1, (300, 250)), hand(2, (800, 600))])
        preview = self.interaction.rectangle
        self.assertTrue(200 < preview.left < 300)
        self.assertTrue(600 < preview.right < 800)
        # Release locations must not move the already previewed rectangle.
        self.update([hand(1, (0, 0), False), hand(2, (1200, 700))])
        self.assertEqual(self.interaction.state, "PLACED")
        self.assertEqual(self.interaction.rectangle, preview)

    def test_placed_rectangle_stays_until_reset(self):
        self.update(pair())
        self.update(pair(False))
        placed = self.interaction.rectangle
        for hands in ([], pair(), [hand(7, (0, 0)), hand(8, (1000, 600))]):
            self.update(hands)
            self.assertEqual(self.interaction.state, "PLACED")
            self.assertEqual(self.interaction.rectangle, placed)

    def test_reset_requires_both_hands_visibly_released_before_rearming(self):
        self.update(pair())
        self.update(pair(False))
        self.interaction.reset()
        self.assertIsNone(self.interaction.rectangle)
        for hands in (pair(), [], [hand(1, (200, 200), False)],
                      [hand(1, (200, 200), False), hand(2, (600, 500))]):
            self.update(hands)
            self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
            self.assertIsNone(self.interaction.rectangle)
        self.update(pair(False))
        self.assertEqual(self.interaction.state, "READY")
        self.assertIsNone(self.interaction.rectangle)
        self.update(pair())
        self.assertEqual(self.interaction.state, "CREATING")

    def test_reset_during_creation_cancels_and_blocks_held_pinches(self):
        self.update(pair())
        self.interaction.reset()
        self.update(pair())
        self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
        self.assertIsNone(self.interaction.rectangle)

    def test_rectangle_below_minimum_width_or_height_is_discarded(self):
        minimum = MIN_RECTANGLE_SIZE_PIXELS
        for width, height in ((minimum - 1, 100), (100, minimum - 1)):
            with self.subTest(width=width, height=height):
                self.interaction = RectangleInteraction()
                self.update([hand(1, (200, 200)), hand(2, (200 + width, 200 + height))])
                self.update(pair(False))
                self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
                self.assertIsNone(self.interaction.rectangle)
                self.update(pair())
                self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")

    def test_rectangle_at_minimum_size_is_placed(self):
        minimum = MIN_RECTANGLE_SIZE_PIXELS
        self.update([hand(1, (200, 200)), hand(2, (200 + minimum, 200 + minimum))])
        self.update(pair(False))
        self.assertEqual(self.interaction.state, "PLACED")

    def test_crossed_corners_never_produce_negative_dimensions(self):
        self.assertEqual(Rectangle.from_corners((600, 500), (200, 200), WIDTH, HEIGHT),
                         Rectangle(200, 200, 600, 500))
        self.update(pair())
        for _ in range(8):
            self.update([hand(1, (600, 500)), hand(2, (200, 200))])
            self.assertGreaterEqual(self.interaction.rectangle.width, 0)
            self.assertGreaterEqual(self.interaction.rectangle.height, 0)
        self.update(pair(False))
        self.assertEqual(self.interaction.state, "PLACED")

    def test_corners_are_clamped_to_frame_bounds(self):
        self.update([hand(1, (-50, -20)), hand(2, (2000, 1000))])
        self.assertEqual(self.interaction.rectangle, Rectangle(0, 0, WIDTH - 1, HEIGHT - 1))
        for _ in range(8):
            self.update([hand(1, (2000, -100)), hand(2, (-100, 2000))])
            box = self.interaction.rectangle
            self.assertTrue(0 <= box.left <= box.right < WIDTH)
            self.assertTrue(0 <= box.top <= box.bottom < HEIGHT)

    def test_placed_rectangle_stays_in_bounds_after_frame_size_change(self):
        self.update(pair())
        self.update(pair(False))
        self.interaction.update([], 320, 240)
        self.assertEqual(self.interaction.state, "PLACED")
        self.assertEqual(self.interaction.rectangle, Rectangle(200, 200, 319, 239))

    def test_missing_hand_cancels_instead_of_placing(self):
        for remaining in ([], [hand(1, (200, 200))], [hand(1, (200, 200), False)]):
            with self.subTest(remaining=len(remaining)):
                self.interaction = RectangleInteraction()
                self.update(pair())
                self.update(remaining)
                self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
                self.assertIsNone(self.interaction.rectangle)
                self.update(pair())
                self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
                self.update(pair(False))
                self.assertEqual(self.interaction.state, "READY")

    def test_replacement_hand_cancels_even_when_it_is_open(self):
        for pinching in (False, True):
            with self.subTest(pinching=pinching):
                self.interaction = RectangleInteraction()
                self.update(pair())
                self.update([hand(1, (200, 200)), hand(3, (600, 500), pinching)])
                self.assertEqual(self.interaction.state, "WAITING_FOR_RELEASE")
                self.assertIsNone(self.interaction.rectangle)

    def test_result_order_changes_do_not_swap_corner_smoothing(self):
        self.update(pair())
        original = self.interaction.rectangle
        self.update(list(reversed(pair())))
        self.assertEqual(self.interaction.state, "CREATING")
        self.assertEqual(self.interaction.rectangle, original)


if __name__ == "__main__":
    unittest.main()
