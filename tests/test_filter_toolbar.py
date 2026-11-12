"""Fresh-pinch and keyboard selection without camera access."""

from types import SimpleNamespace
import unittest

from filter_toolbar import DELETE_KEYS, FilterToolbar
from filters import FILTER_NAMES


WIDTH, HEIGHT = 640, 480


def hand(track_id, point, pinching=False):
    return SimpleNamespace(track_id=track_id, pinch_point=point, is_pinching=pinching)


class FilterToolbarTests(unittest.TestCase):
    def setUp(self):
        self.toolbar = FilterToolbar()

    def point(self, index):
        button = self.toolbar.buttons(WIDTH, HEIGHT)[index]
        return ((button.left + button.right) / 2, (button.top + button.bottom) / 2)

    def update(self, hands, enabled=True, key=-1):
        return self.toolbar.update(hands, WIDTH, HEIGHT, enabled, key)

    def test_fresh_pinch_selects_once_and_release_rearms(self):
        self.update([hand(1, self.point(1))])
        self.assertTrue(self.update([hand(1, self.point(1), True)]))
        self.assertEqual(self.toolbar.selected, "GRAYSCALE")
        self.assertFalse(self.update([hand(1, self.point(3), True)]))
        self.assertEqual(self.toolbar.selected, "GRAYSCALE")
        self.update([hand(1, self.point(3))])
        self.assertTrue(self.update([hand(1, self.point(3), True)]))
        self.assertEqual(self.toolbar.selected, "NEON")

    def test_unknown_or_already_pinching_hand_cannot_activate_by_entering_button(self):
        self.assertFalse(self.update([hand(1, self.point(1), True)]))
        self.update([hand(1, (500, 200))])
        self.assertFalse(self.update([hand(1, (500, 200), True)]))
        self.assertFalse(self.update([hand(1, self.point(1), True)]))
        self.assertEqual(self.toolbar.selected, "ORIGINAL")

    def test_disabled_state_requires_a_released_observation_after_returning_idle(self):
        self.update([hand(1, self.point(1))])
        self.update([hand(1, self.point(1))], enabled=False)
        self.assertFalse(self.update([hand(1, self.point(1), True)]))
        self.assertFalse(self.update([hand(1, self.point(1), True)], enabled=False, key=ord("4")))
        self.update([hand(1, self.point(1))])
        self.assertTrue(self.update([hand(1, self.point(1), True)]))

    def test_loss_or_replacement_does_not_inherit_arming(self):
        self.update([hand(1, self.point(1))])
        self.update([])
        self.assertFalse(self.update([hand(1, self.point(1), True)]))
        self.assertFalse(self.update([hand(2, self.point(1), True)]))

    def test_simultaneous_selection_uses_lowest_track_id_regardless_of_order(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                self.toolbar = FilterToolbar()
                released = [hand(1, self.point(3)), hand(2, self.point(2))]
                self.update(released)
                pressed = [hand(1, self.point(3), True), hand(2, self.point(2), True)]
                self.assertTrue(self.update(pressed[::-1] if reverse else pressed))
                self.assertEqual(self.toolbar.selected, "NEON")
                self.assertEqual(self.toolbar.panel_hands(pressed), [])

    def test_selecting_pinches_stay_consumed_until_release(self):
        released = [hand(1, self.point(1)), hand(2, (300, 280))]
        pressed = [hand(1, self.point(1), True), hand(2, (300, 280), True)]
        self.update(released)
        self.update(pressed)
        self.update(pressed)
        self.assertEqual(self.toolbar.panel_hands(pressed), [])
        released_first = [released[0], pressed[1]]
        self.update(released_first)
        self.assertEqual(self.toolbar.panel_hands(released_first), [released[0]])

    def test_keys_use_the_same_choice_and_disabled_keys_do_nothing(self):
        for index, name in enumerate(FILTER_NAMES):
            self.assertTrue(self.update([], key=ord(str(index + 1))))
            self.assertEqual(self.toolbar.selected, name)
        self.assertFalse(self.update([], enabled=False, key=ord("1")))
        self.assertEqual(self.toolbar.selected, "NEON")
        self.toolbar.disable()
        self.assertEqual(self.toolbar.selected, "NEON")

    def test_keyboard_wins_a_simultaneous_pinch_and_same_filter_still_consumes(self):
        self.update([hand(1, self.point(1))])
        self.assertTrue(self.update([hand(1, self.point(1), True)], key=ord("4")))
        self.assertEqual(self.toolbar.selected, "NEON")
        self.assertTrue(self.update([], key=ord("4")))

    def test_buttons_fit_common_frame_sizes_and_do_not_overlap(self):
        for width in (320, 640, 1280):
            buttons = self.toolbar.buttons(width, HEIGHT)
            self.assertTrue(all(0 <= button.left < button.right < width for button in buttons))
            self.assertTrue(all(first.right < second.left for first, second in zip(buttons, buttons[1:])))

    def test_new_delete_buttons_and_keys_share_fresh_pinch_consumption(self):
        for index, action in enumerate(("NEW", "DELETE")):
            with self.subTest(action=action):
                self.toolbar = FilterToolbar()
                button = self.toolbar.action_buttons(WIDTH, HEIGHT)[index]
                point = ((button.left + button.right) / 2, (button.top + button.bottom) / 2)
                self.update([hand(1, point)])
                self.assertTrue(self.update([hand(1, point, True)]))
                self.assertEqual(self.toolbar.action, action)
                self.assertEqual(self.toolbar.panel_hands([hand(1, point, True)]), [])
                self.assertFalse(self.update([hand(1, point, True)]))
        for key in (ord("n"), ord("N"), *DELETE_KEYS):
            self.assertTrue(self.update([], key=key))
            self.assertEqual(self.toolbar.action, "NEW" if key in (ord("n"), ord("N")) else "DELETE")
            self.assertFalse(self.update([], enabled=False, key=key))


if __name__ == "__main__":
    unittest.main()
