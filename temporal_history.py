"""Bounded, shared raw-video history kept only in memory."""

from collections import deque
from math import ceil, floor
from time import monotonic

import cv2


DELAY_SECONDS = 2.0
RETENTION_SECONDS = 3.0
SAMPLE_INTERVAL = 1.0 / 15
MAX_FRAMES = 48
MAX_IMAGE_BYTES = 40 * 1024 * 1024


class TemporalHistory:
    def __init__(self):
        self.clear()

    def clear(self):
        self.frames = deque()
        self.image_bytes = 0
        self.frame_size = None

    def _evict_oldest(self):
        _, image = self.frames.popleft()
        self.image_bytes -= image.nbytes

    def record(self, raw_frame, now=None):
        """Sample at most 15 FPS; own independent, aspect-preserving BGR pixels."""
        now = monotonic() if now is None else now
        height, width = raw_frame.shape[:2]
        if self.frame_size != (width, height):
            self.clear()
            self.frame_size = (width, height)
        while self.frames and self.frames[0][0] < now - RETENTION_SECONDS:
            self._evict_oldest()
        if self.frames and now - self.frames[-1][0] < SAMPLE_INTERVAL:
            return False
        scale = min(1.0, 640 / width, 360 / height)
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = (cv2.resize(raw_frame, size, interpolation=cv2.INTER_AREA)
                 if size != (width, height) else raw_frame.copy())
        # Evict before appending, keeping even the insertion within the budget.
        while self.frames and (len(self.frames) >= MAX_FRAMES
                               or self.image_bytes + image.nbytes > MAX_IMAGE_BYTES):
            self._evict_oldest()
        if image.nbytes > MAX_IMAGE_BYTES:
            return False
        self.frames.append((now, image))
        self.image_bytes += image.nbytes
        return True

    def at(self, timestamp):
        """Latest sample at or before the target; no future-frame fallback."""
        return next((image for stamp, image in reversed(self.frames)
                     if stamp <= timestamp), None)

    def delayed_crop(self, rectangle, live_size, now):
        """Map the current screen region into the downscaled historical frame."""
        if self.frame_size != live_size:
            return None
        image = self.at(now - DELAY_SECONDS)
        if image is None:
            return None
        live_width, live_height = live_size
        height, width = image.shape[:2]
        left, top = round(rectangle.left), round(rectangle.top)
        crop_width, crop_height = rectangle.pixel_size()
        x0 = max(0, min(width - 1, floor(left * width / live_width)))
        y0 = max(0, min(height - 1, floor(top * height / live_height)))
        x1 = max(x0 + 1, min(width, ceil((left + crop_width) * width / live_width)))
        y1 = max(y0 + 1, min(height, ceil((top + crop_height) * height / live_height)))
        return image[y0:y1, x0:x1]
