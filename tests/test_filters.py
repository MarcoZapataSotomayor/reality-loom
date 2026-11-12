"""Stateless filter behavior and panel-only compositing with synthetic pixels."""

from types import SimpleNamespace
import unittest

import cv2
import numpy as np

from filters import FILTER_NAMES, NEON_COLOR_BGR, apply_filter
from interaction import Rectangle, RectangleInteraction


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.source = np.random.default_rng(42).integers(0, 256, (24, 36, 3), dtype=np.uint8)

    def test_outputs_match_requested_bgr_shape_dtype_and_leave_source_unchanged(self):
        original = self.source.copy()
        self.source.setflags(write=False)
        for name in FILTER_NAMES:
            for size in ((1, 1), (2, 3), (36, 24), (57, 31)):
                with self.subTest(filter=name, size=size):
                    result = apply_filter(self.source, name, size)
                    self.assertEqual(result.shape, (size[1], size[0], 3))
                    self.assertEqual(result.dtype, np.uint8)
                    self.assertFalse(np.shares_memory(result, self.source))
                    np.testing.assert_array_equal(self.source, original)

    def test_original_is_pixel_identity_with_an_independent_output(self):
        result = apply_filter(self.source, "ORIGINAL", (36, 24))
        np.testing.assert_array_equal(result, self.source)
        result[:] = 0
        self.assertTrue(np.any(self.source))
        np.testing.assert_array_equal(apply_filter(self.source, "ORIGINAL", (18, 12)),
                                      cv2.resize(self.source, (18, 12)))

    def test_grayscale_has_expected_bgr_luminance_and_equal_channels(self):
        source = np.array([[[0, 0, 255], [0, 255, 0], [255, 0, 0]]], dtype=np.uint8)
        result = apply_filter(source, "GRAYSCALE", (3, 1))
        np.testing.assert_array_equal(result[0, :, 0], [76, 150, 29])
        np.testing.assert_array_equal(result[:, :, 0], result[:, :, 1])
        np.testing.assert_array_equal(result[:, :, 1], result[:, :, 2])

    def test_pixelate_replaces_high_frequency_detail_with_uniform_blocks(self):
        checker = ((np.indices((24, 24)).sum(axis=0) % 2) * 255).astype(np.uint8)
        source = np.repeat(checker[:, :, None], 3, axis=2)
        result = apply_filter(source, "PIXELATE", (24, 24))
        self.assertFalse(np.array_equal(result, source))
        self.assertTrue(np.all(np.abs(result.astype(float) - 127.5) <= 1))

    def test_neon_marks_edges_with_color_and_leaves_flat_regions_black(self):
        flat = np.full((48, 64, 3), 90, dtype=np.uint8)
        self.assertFalse(np.any(apply_filter(flat, "NEON", (64, 48))))
        source = np.zeros_like(flat)
        source[12:36, 16:48] = 255
        result = apply_filter(source, "NEON", (64, 48))
        colored = np.any(result != 0, axis=2)
        self.assertTrue(np.any(colored))
        self.assertLess(np.count_nonzero(colored), 200)
        self.assertTrue(np.all(result[colored] == NEON_COLOR_BGR))

    def test_noncontiguous_sources_and_invalid_requests(self):
        source = self.source[::2, ::2]
        for name in FILTER_NAMES:
            self.assertEqual(apply_filter(source, name, (9, 6)).shape, (6, 9, 3))
        for name, size in (("UNKNOWN", (1, 1)), ("ORIGINAL", (0, 1))):
            with self.assertRaises(ValueError):
                apply_filter(self.source, name, size)


class PanelFilterTests(unittest.TestCase):
    def setUp(self):
        self.interaction = RectangleInteraction()
        for pinching in (True, False):
            hands = [SimpleNamespace(track_id=1, pinch_point=(20, 30), is_pinching=pinching),
                     SimpleNamespace(track_id=2, pinch_point=(100, 90), is_pinching=pinching)]
            self.interaction.update(hands, 160, 120)
        self.raw = np.random.default_rng(7).integers(0, 256, (120, 160, 3), dtype=np.uint8)

    def test_only_panel_pixels_change_before_overlays_in_live_mode(self):
        original = self.raw.copy()
        preview = self.raw.copy()
        self.interaction.composite_panel(self.raw, preview, "GRAYSCALE")
        mask = np.zeros(self.raw.shape[:2], dtype=bool)
        mask[30:90, 20:100] = True
        np.testing.assert_array_equal(preview[~mask], original[~mask])
        self.assertFalse(np.array_equal(preview[mask], original[mask]))
        np.testing.assert_array_equal(preview[30:90, 20:100],
                                      apply_filter(original[30:90, 20:100], "GRAYSCALE", (80, 60)))
        np.testing.assert_array_equal(self.raw, original)

    def test_switching_filters_and_sizes_always_uses_untouched_frozen_source(self):
        self.interaction.toggle_frozen(self.raw)
        source = self.interaction.frozen_image
        original = source.copy()
        for size in ((80, 60), (50, 70), (100, 40), (80, 60)):
            self.interaction.rectangle = Rectangle(20, 30, 20 + size[0], 30 + size[1])
            for name in FILTER_NAMES:
                live = np.full_like(self.raw, 77)
                expected = live.copy()
                expected[30:30 + size[1], 20:20 + size[0]] = apply_filter(original, name, size)
                self.interaction.composite_panel(live, live, name)
                np.testing.assert_array_equal(live, expected)
                self.assertIs(self.interaction.frozen_image, source)
                np.testing.assert_array_equal(source, original)
        self.assertEqual(source.shape, (60, 80, 3))

    def test_live_source_is_current_frame_and_no_rectangle_changes_nothing(self):
        current = np.full_like(self.raw, (10, 80, 220))
        preview = current.copy()
        self.interaction.composite_panel(current, preview, "GRAYSCALE")
        expected = apply_filter(current[30:90, 20:100], "GRAYSCALE", (80, 60))
        np.testing.assert_array_equal(preview[30:90, 20:100], expected)
        self.interaction.reset()
        preview = current.copy()
        self.interaction.composite_panel(current, preview, "NEON")
        np.testing.assert_array_equal(preview, current)


if __name__ == "__main__":
    unittest.main()
