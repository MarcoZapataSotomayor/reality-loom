"""Show a live camera preview with hand landmarks without saving media."""

import argparse
import sys
import time

import cv2

from camera_recovery import CameraReconnect


WINDOW_TITLE = "Reality Loom"
DEBUG_FRAME_LIMIT = 5
DEBUG_LOG_INTERVAL_SECONDS = 2.0


def open_camera(camera_index):
    """Try each backend and return a camera with its first usable frame."""
    if sys.platform == "win32":
        backends = [
            ("DirectShow", cv2.CAP_DSHOW),
            ("Media Foundation", cv2.CAP_MSMF),
        ]
    else:
        backends = [("default backend", cv2.CAP_ANY)]

    for backend_name, backend in backends:
        camera = cv2.VideoCapture()
        ready = False
        try:
            print(f"Trying camera {camera_index} with {backend_name}...")
            if not camera.open(camera_index, backend):
                print(f"Could not open camera {camera_index} with {backend_name}.")
                continue

            success, frame = camera.read()
            if not success or frame is None or frame.size == 0:
                print(f"Camera opened with {backend_name}, but the first frame could not be read.")
                continue

            print(f"Camera {camera_index} opened with {backend_name}.")
            ready = True
            return camera, frame
        except cv2.error as error:
            print(f"Camera {camera_index} failed with {backend_name}: {error}")
        finally:
            # Failed attempts must release the device before trying another backend.
            if not ready:
                camera.release()

    return None, None


def log_camera_frame(camera, frame, frame_number):
    """Report the captured pixels before inference or drawing changes the preview."""
    try:
        backend_name = camera.getBackendName()
    except cv2.error:
        backend_name = "unknown"

    height, width = frame.shape[:2]
    print(
        f"[camera debug] Frame {frame_number}: backend={backend_name}, "
        f"width={width}, height={height}, dtype={frame.dtype}, "
        f"min={frame.min()}, mean={frame.mean():.2f}, max={frame.max()}"
    )


class CameraDebugLogger:
    """Log five startup frames, then at most one frame every two seconds."""

    def __init__(self):
        self._frame_number = 0
        self._last_log_time = None

    def report(self, camera, frame):
        self._frame_number += 1
        now = time.monotonic()
        if (self._frame_number <= DEBUG_FRAME_LIMIT
                or self._last_log_time is None
                or now - self._last_log_time >= DEBUG_LOG_INTERVAL_SECONDS):
            log_camera_frame(camera, frame, self._frame_number)
            self._last_log_time = now


def draw_camera_status(frame, message, instructions):
    """Clearly label the last image while live capture is paused."""
    for row, text in enumerate((message, instructions)):
        position = (12, 32 + row * 26)
        cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 1, cv2.LINE_AA)


def draw_rectangle_interaction(frame, interaction):
    """Render the rectangle and instructions only on the display copy."""
    rectangle = interaction.rectangle
    if rectangle is not None:
        color = (0, 255, 255) if interaction.state == "CREATING" else (255, 200, 0)
        cv2.rectangle(
            frame,
            (round(rectangle.left), round(rectangle.top)),
            (round(rectangle.right), round(rectangle.bottom)),
            color, 2, cv2.LINE_AA,
        )
    lines = (f"Rectangle: {interaction.state.replace('_', ' ')}", interaction.instructions)
    for row, text in enumerate(lines):
        position = (12, 60 + row * 24)
        cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (255, 255, 255), 1, cv2.LINE_AA)


def main():
    parser = argparse.ArgumentParser(
        description="Show the Reality Loom camera preview with hand landmarks."
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=0,
        help="camera index to open (default: 0)",
    )
    parser.add_argument(
        "--no-tracking",
        action="store_true",
        help="show the camera preview without importing MediaPipe or loading its model",
    )
    parser.add_argument(
        "--debug-camera",
        action="store_true",
        help="log raw camera statistics for five frames, then at most every two seconds",
    )
    args = parser.parse_args()

    camera = None
    tracker = None
    recovery = None
    try:
        if not args.no_tracking:
            # Import only when requested so camera-only mode never loads MediaPipe.
            from hand_tracking import HandTracker, draw_hand_landmarks
            from gestures import PinchDetector
            from interaction import RectangleInteraction

            # Check the model before opening the camera.
            tracker = HandTracker()
            pinch_detector = PinchDetector()
            interaction = RectangleInteraction()
        camera, frame = open_camera(args.camera)
        if camera is None:
            print(
                "Could not start the preview. Keep Camo Studio running with your iPad "
                "connected, close other camera apps, and check your --camera index."
            )
            return 1

        cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
        print("Press C to reconnect this camera. Press Q or Escape, or close the window, to exit.")
        if tracker is not None:
            print("Pinch both hands to create a rectangle. Press R to clear it.")
        debug_logger = CameraDebugLogger()
        camera_error = None

        while True:
            # Keep the captured BGR image intact for diagnostics and future reads.
            preview_frame = frame.copy()
            if recovery is not None:
                draw_camera_status(preview_frame, "Reconnecting camera...", "Q / Escape: exit")
            elif camera_error is not None:
                draw_camera_status(
                    preview_frame, camera_error,
                    "Check Camo Studio / iPad. C: retry | Q / Escape: exit",
                )
            else:
                if args.debug_camera:
                    debug_logger.report(camera, frame)
                if tracker is not None:
                    result = tracker.detect(preview_frame)
                    hand_gestures = pinch_detector.update(
                        result.hand_landmarks, frame.shape[1], frame.shape[0]
                    )
                    interaction.update(hand_gestures, frame.shape[1], frame.shape[0])
                    draw_hand_landmarks(preview_frame, result, hand_gestures)
                    draw_rectangle_interaction(preview_frame, interaction)
            cv2.imshow(WINDOW_TITLE, preview_frame)
            key = cv2.waitKey(30 if recovery is not None or camera_error else 1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
            if tracker is not None and key in (ord("r"), ord("R")):
                interaction.reset()

            # Some backends raise an error when the user has closed the window.
            try:
                if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except cv2.error:
                break

            if key in (ord("c"), ord("C")) and recovery is None:
                previous_frame_size = (frame.shape[1], frame.shape[0])
                if tracker is not None:
                    pinch_detector.reset()
                    interaction.prepare_camera_reconnect()
                old_camera = camera
                camera = None  # Ownership moves to the worker until it publishes a result.
                recovery = CameraReconnect(old_camera, args.camera, open_camera)
                camera_error = None
                continue

            if recovery is not None:
                # Display/pump events before polling, so even fast attempts show status.
                result = recovery.poll()
                if result is not None:
                    recovery = None
                    camera = result.camera
                    if result.error is not None:
                        print(f"{result.error} Check Camo Studio and the iPad; press C to retry.")
                        camera_error = "Camera reconnection failed."
                    else:
                        frame = result.frame
                        if tracker is not None:
                            interaction.finish_camera_reconnect(
                                previous_frame_size, (frame.shape[1], frame.shape[0])
                            )
                        debug_logger = CameraDebugLogger()
                        print("Camera reconnected. Show both hands OPEN to resume gestures."
                              if tracker is not None else "Camera reconnected.")
                continue

            if camera_error is not None:
                continue

            try:
                success, next_frame = camera.read()
            except cv2.error as error:
                print(f"Camera read failed: {error}")
                success, next_frame = False, None
            if not success or next_frame is None or next_frame.size == 0:
                camera_error = "Could not read a camera frame."
                print(
                    "Could not read a camera frame. Check Camo Studio and the iPad; "
                    "press C to reconnect or Q / Escape to exit."
                )
            else:
                frame = next_frame

        return 0
    except KeyboardInterrupt:
        print("\nPreview stopped with Ctrl+C.")
        return 0
    except cv2.error as error:
        print(f"OpenCV could not continue the preview: {error}")
        return 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Could not continue the preview: {error}")
        return 1
    finally:
        try:
            if recovery is not None:
                recovery.close()
        finally:
            try:
                if tracker is not None:
                    tracker.close()
            finally:
                try:
                    if camera is not None:
                        camera.release()
                finally:
                    cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
