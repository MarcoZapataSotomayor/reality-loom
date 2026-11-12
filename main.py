"""Show a live camera preview with hand landmarks without saving media."""

import argparse
import sys
import time

import cv2

from camera_recovery import CameraReconnect


WINDOW_TITLE = "Reality Loom"
DEBUG_FRAME_LIMIT = 5
DEBUG_LOG_INTERVAL_SECONDS = 2.0
CORNER_HANDLE_RADIUS_PIXELS = 4


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
    """Draw every border, but only the active panel's handles, above composites."""
    for panel in interaction.panels:
        box = panel.rectangle
        active_panel = panel.panel_id == interaction.active_id and not interaction.creation_mode
        color = (255, 200, 0) if active_panel else (170, 170, 170)
        cv2.rectangle(frame, (round(box.left), round(box.top)),
                      (round(box.right), round(box.bottom)), color, 1, cv2.LINE_AA)
        cv2.putText(frame, f"#{panel.panel_id}", (round(box.left) + 7, round(box.top) + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
    rectangle = interaction.rectangle
    if rectangle is not None:
        color = (0, 255, 255) if interaction.state in ("CREATING", "RESIZING") else (255, 200, 0)
        cv2.rectangle(
            frame,
            (round(rectangle.left), round(rectangle.top)),
            (round(rectangle.right), round(rectangle.bottom)),
            color, 2, cv2.LINE_AA,
        )
        if interaction.state in ("PLACED", "DRAGGING", "RESIZING"):
            for point in rectangle.corner_points().values():
                cv2.circle(frame, (round(point[0]), round(point[1])),
                           CORNER_HANDLE_RADIUS_PIXELS, color, -1, cv2.LINE_AA)
    lines = [interaction.status_text]
    if rectangle is not None:
        lines.append(f"Content: {interaction.content_mode} | F: toggle when placed")
    lines.append(interaction.instructions)
    height, width = frame.shape[:2]
    start_y, line_height = (60, 24) if height >= 360 else (50, 16)
    for row, text in enumerate(lines):
        position = (12, start_y + row * line_height)
        base_scale = 0.55 if width >= 640 else 0.35
        text_width = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, base_scale, 1)[0][0]
        scale = base_scale * min(1.0, (width - 24) / max(1, text_width))
        cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                    scale, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX,
                    scale, (255, 255, 255), 1, cv2.LINE_AA)


def draw_fist_feedback(frame, message):
    position = (12, frame.shape[0] - 16)
    cv2.putText(frame, message, position, cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(frame, message, position, cv2.FONT_HERSHEY_SIMPLEX,
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
            from panels import PanelCollection
            from freeze_control import FreezeController
            from filter_toolbar import FilterToolbar

            # Check the model before opening the camera.
            tracker = HandTracker()
            pinch_detector = PinchDetector()
            interaction = PanelCollection()
            freeze_control = FreezeController()
            toolbar = FilterToolbar()
        camera, frame = open_camera(args.camera)
        if camera is None:
            print(
                "Could not start the preview. Keep Camo Studio running with your iPad "
                "connected, close other camera apps, and check your --camera index."
            )
            return 1

        cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
        print("C: reconnect | Q: exit | Escape: cancel new panel, or exit outside creation.")
        if tracker is not None:
            print("Pinch both hands to create. N: New panel | Delete: active panel | R: clear ALL panels")
            print("Press F while placed to toggle LIVE / FROZEN content.")
            print("Or open a hand fully, then hold a fist outside the placed rectangle for 0.8 s.")
            print("Select a panel filter with the toolbar or keys 1-4 while idle / placed.")
        debug_logger = CameraDebugLogger()
        camera_error = None

        while True:
            # Keep the captured BGR image intact for diagnostics and future reads.
            preview_frame = frame.copy()
            hand_gestures = []
            selection_consumed = False
            active = recovery is None and camera_error is None
            if active:
                if args.debug_camera:
                    debug_logger.report(camera, frame)
                if tracker is not None:
                    # Inference always sees live input, even beneath panel effects.
                    result = tracker.detect(frame)
                    hand_gestures = pinch_detector.update(
                        result.hand_landmarks, frame.shape[1], frame.shape[0]
                    )

            # Read keyboard input before gesture arbitration so keys 1-4 have the
            # same priority as toolbar pinches, ahead of drag/resize starts.
            key = cv2.waitKeyEx(30 if not active else 1)
            escape_canceled = False
            if tracker is not None:
                if key == 27 and active:
                    escape_canceled = interaction.cancel_creation()
                    if escape_canceled:
                        freeze_control.reset()
                        toolbar.disable()
                toolbar.selected = interaction.selected_filter
                control_key = key in (ord("q"), ord("Q"), 27, ord("r"), ord("R"), ord("c"), ord("C"))
                can_select = active and not control_key and interaction.toolbar_enabled
                selection_consumed = toolbar.update(
                    hand_gestures, frame.shape[1], frame.shape[0], can_select, key,
                )

            if recovery is not None:
                draw_camera_status(preview_frame, "Reconnecting camera...", "Q / Escape: exit")
            elif camera_error is not None:
                draw_camera_status(
                    preview_frame, camera_error,
                    "Check Camo Studio / iPad. C: retry | Q / Escape: exit",
                )
            else:
                if tracker is not None:
                    if selection_consumed:
                        interaction.apply_action(toolbar.action)
                        interaction.observe_pinches(hand_gestures)
                        freeze_control.reset()
                    elif escape_canceled:
                        interaction.observe_pinches(hand_gestures)
                    else:
                        panel_hands = toolbar.panel_hands(hand_gestures)
                        interaction.update(panel_hands, frame.shape[1], frame.shape[0])
                        freeze_control.update(panel_hands, interaction)
                    if not interaction.toolbar_enabled:
                        toolbar.disable()
                    interaction.composite(frame, preview_frame)
                    # Draw every overlay above the composite, never into the raw frame.
                    draw_hand_landmarks(preview_frame, result, hand_gestures)
                    draw_rectangle_interaction(preview_frame, interaction)
                    if interaction.rectangle is not None:
                        draw_fist_feedback(preview_frame, freeze_control.message)
            if tracker is not None:
                toolbar.selected = interaction.selected_filter
                toolbar.draw(preview_frame, hand_gestures,
                             active and interaction.toolbar_enabled,
                             interaction.can_new, interaction.can_delete,
                             "default for new panels" if interaction.creation_mode else f"active panel #{interaction.active_id}")
            cv2.imshow(WINDOW_TITLE, preview_frame)
            if key in (ord("q"), ord("Q")) or (key == 27 and not escape_canceled):
                break
            if tracker is not None and key in (ord("r"), ord("R")):
                interaction.reset()
                freeze_control.reset()

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
                    freeze_control.reset()
                    toolbar.disable()
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

            if tracker is not None and not selection_consumed and not escape_canceled:
                # Keyboard and fist requests share one raw-image action. C/R and
                # exit checks above cancel pending requests before this point.
                freeze_control.apply(interaction, frame, keyboard=key in (ord("f"), ord("F")))

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
