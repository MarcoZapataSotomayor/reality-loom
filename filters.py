"""Stateless panel effects using the existing OpenCV and NumPy packages."""

import cv2
import numpy as np


FILTER_NAMES = ("ORIGINAL", "GRAYSCALE", "PIXELATE", "NEON")
PIXEL_BLOCK_SIZE = 12
NEON_EDGE_LOW = 60
NEON_EDGE_HIGH = 140
NEON_COLOR_BGR = (255, 80, 220)


def apply_filter(source, name, size):
    """Return independent uint8 BGR pixels at (width, height), leaving source intact."""
    width, height = size
    if width < 1 or height < 1:
        raise ValueError("Panel width and height must be positive.")
    if (source.dtype != np.uint8 or source.ndim != 3 or source.shape[2] != 3
            or source.shape[0] < 1 or source.shape[1] < 1):
        raise ValueError("Panel source must be a non-empty uint8 three-channel BGR image.")
    if name not in FILTER_NAMES:
        raise ValueError(f"Unknown panel filter: {name}")

    image = (source.copy() if source.shape[:2] == (height, width)
             else cv2.resize(source, (width, height), interpolation=cv2.INTER_LINEAR))
    if name == "ORIGINAL":
        return image
    if name == "GRAYSCALE":
        return cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    if name == "PIXELATE":
        small = cv2.resize(image, (max(1, width // PIXEL_BLOCK_SIZE),
                                   max(1, height // PIXEL_BLOCK_SIZE)), interpolation=cv2.INTER_AREA)
        return cv2.resize(small, (width, height), interpolation=cv2.INTER_NEAREST)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, NEON_EDGE_LOW, NEON_EDGE_HIGH)
    neon = np.zeros_like(image)
    neon[edges != 0] = NEON_COLOR_BGR
    return neon
