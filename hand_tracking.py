"""Detect hands with MediaPipe Tasks and draw results with OpenCV."""

from pathlib import Path
import time

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from gestures import INDEX_TIP, THUMB_TIP


MODEL_PATH = Path(__file__).resolve().parent / "models" / "hand_landmarker.task"


class HandTracker:
    """Own one landmarker and process frames in order using VIDEO mode."""

    def __init__(self, model_path=MODEL_PATH):
        model_path = Path(model_path)
        if not model_path.is_file():
            raise FileNotFoundError(
                f"Missing hand landmark model: {model_path}. "
                "Restore models/hand_landmarker.task using the download command in README.md."
            )

        self._start_ns = time.monotonic_ns()
        self._last_timestamp_ms = -1
        options = vision.HandLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)

    def detect(self, bgr_frame):
        """Detect up to two hands using a separate RGB array; leave BGR unchanged."""
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        elapsed_ms = (time.monotonic_ns() - self._start_ns) // 1_000_000
        # Two calls can share a clock millisecond; MediaPipe needs distinct times.
        timestamp_ms = max(elapsed_ms, self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        return self._landmarker.detect_for_video(image, timestamp_ms)

    def close(self):
        """Release MediaPipe resources when the preview stops."""
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None


def draw_hand_landmarks(bgr_frame, result, hand_gestures=None):
    """Draw in place on a BGR preview copy supplied by the caller."""
    height, width = bgr_frame.shape[:2]
    for hand_index, hand in enumerate(result.hand_landmarks):
        # MediaPipe coordinates are normalized; convert them to image pixels.
        points = [
            (
                max(0, min(width - 1, int(landmark.x * width))),
                max(0, min(height - 1, int(landmark.y * height))),
            )
            for landmark in hand
        ]
        for connection in vision.HandLandmarksConnections.HAND_CONNECTIONS:
            cv2.line(
                bgr_frame, points[connection.start], points[connection.end],
                (0, 255, 0), 2, cv2.LINE_AA,
            )
        gesture = hand_gestures[hand_index] if hand_gestures is not None else None
        if gesture is not None and gesture.is_pinching:
            cv2.line(
                bgr_frame, points[THUMB_TIP], points[INDEX_TIP],
                (0, 255, 255), 4, cv2.LINE_AA,
            )
        for point in points:
            cv2.circle(bgr_frame, point, 4, (0, 180, 255), -1, cv2.LINE_AA)

        if gesture is not None:
            if gesture.is_fist:
                gesture_label = "FIST"
            elif gesture.is_pinching:
                gesture_label = "PINCH"
            elif gesture.is_open_hand:
                gesture_label = "OPEN"
            else:
                gesture_label = "NEUTRAL"
            color = (0, 255, 255) if gesture.is_pinching else (255, 255, 255)
            text_size, _ = cv2.getTextSize(gesture_label, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
            label_position = (
                min(points[0][0], max(0, width - text_size[0] - 5)),
                max(text_size[1] + 5, points[0][1] - 12),
            )
            cv2.putText(bgr_frame, gesture_label, label_position,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(bgr_frame, gesture_label, label_position,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)

    label = f"Hands: {len(result.hand_landmarks)}"
    # A dark outline keeps the count readable over light camera backgrounds.
    cv2.putText(bgr_frame, label, (12, 32), cv2.FONT_HERSHEY_SIMPLEX,
                0.8, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(bgr_frame, label, (12, 32), cv2.FONT_HERSHEY_SIMPLEX,
                0.8, (255, 255, 255), 2, cv2.LINE_AA)
