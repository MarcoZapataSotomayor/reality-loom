"""Timestamp, budget, and coordinate checks using synthetic raw BGR frames."""

from unittest.mock import patch
import unittest

import numpy as np

from interaction import Rectangle
from temporal_history import MAX_FRAMES, MAX_IMAGE_BYTES, TemporalHistory


class TemporalHistoryTests(unittest.TestCase):
    def test_irregular_samples_choose_latest_at_or_before_target(self):
        history = TemporalHistory()
        for stamp, value in ((10.0, 10), (10.1, 20), (10.8, 30), (11.9, 40)):
            history.record(np.full((20, 30, 3), value, np.uint8), stamp)
        self.assertIsNone(history.at(9.999))
        for target, expected in ((10, 10), (10.79, 20), (10.8, 30), (11.89, 30), (12, 40)):
            self.assertTrue(np.all(history.at(target) == expected))

    def test_warm_up_never_uses_a_future_frame(self):
        history = TemporalHistory()
        image = np.zeros((90, 160, 3), np.uint8)
        box = Rectangle(0, 0, 80, 40)
        history.record(image, 5)
        self.assertIsNone(history.delayed_crop(box, (160, 90), 6.999))
        self.assertIsNotNone(history.delayed_crop(box, (160, 90), 7))

    def test_sampling_rate_retention_and_independent_images(self):
        history = TemporalHistory()
        raw = np.full((360, 640, 3), 27, np.uint8)
        self.assertTrue(history.record(raw, 0))
        raw[:] = 90
        self.assertFalse(history.record(raw, 0.03))
        self.assertFalse(np.shares_memory(history.at(0), raw))
        self.assertTrue(np.all(history.at(0) == 27))
        for index in range(1, 501):
            history.record(raw, index / 100)
        stamps = [stamp for stamp, _ in history.frames]
        self.assertTrue(all(b - a >= 1 / 15 for a, b in zip(stamps, stamps[1:])))
        self.assertGreaterEqual(stamps[0], 2)
        self.assertLessEqual(len(stamps), MAX_FRAMES)
        self.assertLessEqual(history.image_bytes, MAX_IMAGE_BYTES)
        self.assertEqual(history.image_bytes, sum(image.nbytes for _, image in history.frames))

    def test_hard_frame_cap_even_if_sampling_configuration_changes(self):
        history = TemporalHistory()
        with patch("temporal_history.SAMPLE_INTERVAL", 0):
            for index in range(60):
                history.record(np.full((2, 2, 3), index, np.uint8), index / 100)
        self.assertEqual(len(history.frames), 48)
        self.assertTrue(np.all(history.frames[0][1] == 12))

    def test_byte_budget_evicts_oldest_and_rejects_oversized_sample(self):
        history = TemporalHistory()
        raw = np.zeros((10, 10, 3), np.uint8)
        with patch("temporal_history.MAX_IMAGE_BYTES", 600):
            for stamp in (0, 0.1, 0.2):
                history.record(raw, stamp)
            self.assertEqual(history.image_bytes, 600)
            self.assertEqual([stamp for stamp, _ in history.frames], [0.1, 0.2])
        history.clear()
        with patch("temporal_history.MAX_IMAGE_BYTES", 299):
            self.assertFalse(history.record(raw, 1))
        self.assertEqual(history.image_bytes, 0)
        self.assertEqual(len(history.frames), 0)

    def test_mapping_and_aspect_ratio_for_landscape_portrait_and_square(self):
        for width, height, stored_size in ((1280, 720, (640, 360)), (640, 480, (480, 360)),
                                           (720, 1280, (202, 360)), (800, 800, (360, 360)),
                                           (160, 90, (160, 90))):
            with self.subTest(size=(width, height)):
                raw = np.zeros((height, width, 3), np.uint8)
                raw[:height // 2, :width // 2] = (10, 20, 30)
                raw[height // 2:, width // 2:] = (100, 150, 200)
                history = TemporalHistory()
                history.record(raw, 0)
                self.assertEqual(history.frames[0][1].shape[:2], stored_size[::-1])
                self.assertFalse(np.shares_memory(history.frames[0][1], raw))
                crop = history.delayed_crop(Rectangle(width / 2, height / 2, width, height),
                                            (width, height), 2)
                np.testing.assert_array_equal(crop[crop.shape[0] // 2, crop.shape[1] // 2], (100, 150, 200))
                self.assertEqual(crop.shape[1], stored_size[0] - stored_size[0] // 2)
                self.assertEqual(crop.shape[0], stored_size[1] - stored_size[1] // 2)

    def test_size_change_and_clear_remove_old_history(self):
        history = TemporalHistory()
        history.record(np.zeros((360, 640, 3), np.uint8), 0)
        history.record(np.ones((480, 640, 3), np.uint8), 2.1)
        self.assertEqual(len(history.frames), 1)
        self.assertIsNone(history.delayed_crop(Rectangle(0, 0, 40, 40), (640, 480), 2.1))
        self.assertIsNone(history.delayed_crop(Rectangle(0, 0, 40, 40), (640, 360), 4.1))
        history.clear()
        self.assertIsNone(history.frame_size)
        self.assertEqual(history.image_bytes, 0)
        self.assertFalse(history.frames)


if __name__ == "__main__":
    unittest.main()
