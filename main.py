"""Run the gesture-tool camera workspace without saving media."""

import argparse
import sys
import time

import cv2

from camera_recovery import CameraReconnect
from ui import draw_camera_status, draw_fist_feedback
from ui import draw_workspace as draw_rectangle_interaction


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


def main():
    parser = argparse.ArgumentParser(
        description="Show the Reality Loom camera workspace with explicit gesture tools."
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
    interaction = None
    slider = None
    try:
        if not args.no_tracking:
            # Import only when requested so camera-only mode never loads MediaPipe.
            from hand_tracking import HandTracker, draw_hand_landmarks
            from gestures import PinchDetector
            from panels import PanelCollection
            from freeze_control import FreezeController
            from filter_toolbar import FilterToolbar
            from delay_slider import DelaySlider
            from help_overlay import HelpOverlay

            # Check the model before opening the camera.
            tracker = HandTracker()
            pinch_detector = PinchDetector()
            interaction = PanelCollection()
            freeze_control = FreezeController()
            toolbar = FilterToolbar()
            slider = DelaySlider()
            help_overlay = HelpOverlay()
            debug_overlays = False
        camera, frame = open_camera(args.camera)
        if camera is None:
            print(
                "Could not start the preview. Keep Camo Studio running with your iPad "
                "connected, close other camera apps, and check your --camera index."
            )
            return 1

        cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
        print("C: reconnect | Q: exit | Escape: cancel an edit/creation, or exit in SELECT.")
        if tracker is not None:
            print("V: Select | M: Move | S: Resize | N: Create | E: Effects | Y: Time")
            print("T: toggle LIVE / DELAYED. Slider or [ / ]: delay 0.5-2.5 s (default 2.0 s).")
            print("F: freeze displayed source / return to previous mode.")
            print("Fist shortcut: idle SELECT with menus closed; open fully, then hold outside for 0.8 s.")
            print("Select a panel filter with the toolbar or keys 1-4 while idle / placed.")
            print("H: controls and gestures help (pauses gesture actions).")
            print("D: toggle landmark skeletons and hand debug labels.")
        debug_logger = CameraDebugLogger()
        camera_error = None

        while True:
            # Keep the captured BGR image intact for diagnostics and future reads.
            preview_frame = frame.copy()
            hand_gestures = []
            selection_consumed = False
            slider_consumed = False
            freeze_requested = False
            reset_blocked = False
            active = recovery is None and camera_error is None
            if active:
                if args.debug_camera:
                    debug_logger.report(camera, frame)
                if tracker is not None:
                    interaction.record_frame(frame)
                    # Inference always sees live input, even beneath panel effects.
                    result = tracker.detect(frame)
                    hand_gestures = pinch_detector.update(
                        result.hand_landmarks, frame.shape[1], frame.shape[0]
                    )

            # Read keyboard input before gesture arbitration so keys 1-4 have the
            # same priority as toolbar pinches, ahead of drag/resize starts.
            key = cv2.waitKeyEx(30 if not active else 1)
            escape_canceled = False
            help_consumed = False
            if tracker is not None:
                help_consumed = help_overlay.handle_key(key, interaction, slider, toolbar, freeze_control)
                if not help_consumed and key in (ord("d"), ord("D")):
                    debug_overlays = not debug_overlays
                if key == 27 and help_consumed:
                    escape_canceled = True
                elif key == 27 and active:
                    escape_canceled = (interaction.cancel_creation() if interaction.creation_mode
                                       else interaction.cancel_edit())
                    if escape_canceled:
                        freeze_control.reset()
                        toolbar.disable()
                        slider.cancel(interaction)
                toolbar.selected = interaction.selected_filter
                reset_blocked = key in (ord("r"), ord("R")) and interaction.operation_active
                control_key = key in (ord("q"), ord("Q"), 27, ord("r"), ord("R"), ord("c"), ord("C"))
                if reset_blocked:
                    control_key = False
                slider_consumed = slider.update(
                    toolbar.panel_hands(hand_gestures), frame.shape[1], frame.shape[0],
                    interaction, active and not help_consumed and not control_key, key)
                can_select = (active and not help_consumed and not control_key
                              and not slider_consumed and interaction.toolbar_enabled)
                selection_consumed = toolbar.update(
                    hand_gestures, frame.shape[1], frame.shape[0], can_select, key, interaction,
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
                    if help_consumed:
                        interaction.observe_pinches(hand_gestures)
                    elif slider_consumed:
                        interaction.observe_pinches(hand_gestures)
                        toolbar.disable()
                        freeze_control.reset()
                    elif selection_consumed:
                        freeze_requested = toolbar.action == "FREEZE"
                        interaction.apply_action(toolbar.action)
                        interaction.observe_pinches(hand_gestures)
                        freeze_control.reset()
                        if freeze_requested:
                            freeze_control.update([], interaction)
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
                    if debug_overlays:
                        draw_hand_landmarks(preview_frame, result, hand_gestures)
                    targets = toolbar.visible_buttons(frame.shape[1], frame.shape[0], interaction)
                    draw_rectangle_interaction(preview_frame, interaction, len(result.hand_landmarks),
                                               hand_gestures, active and not help_consumed, targets)
                    if interaction.rectangle is not None:
                        draw_fist_feedback(preview_frame, freeze_control.message)
            if tracker is not None:
                toolbar.selected = interaction.selected_filter
                toolbar.draw(preview_frame, hand_gestures,
                             active and not help_consumed and interaction.toolbar_enabled,
                             interaction.can_new, interaction.can_delete,
                             "default for new panels" if interaction.creation_mode else f"active panel #{interaction.active_id}",
                             can_delay=interaction.can_delay, delayed=interaction.content_mode == "DELAYED",
                             interaction=interaction)
                slider.draw(preview_frame, interaction,
                            active and not help_consumed and (interaction.can_adjust_delay or interaction.adjusting_delay))
                toolbar.draw_pointers(preview_frame, hand_gestures)
                help_overlay.draw(preview_frame)
            cv2.imshow(WINDOW_TITLE, preview_frame)
            if key in (ord("q"), ord("Q")) or (key == 27 and not escape_canceled):
                break
            if (tracker is not None and active and not help_consumed and not reset_blocked
                    and key in (ord("r"), ord("R"))):
                interaction.reset()
                freeze_control.reset()

            # Some backends raise an error when the user has closed the window.
            try:
                if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except cv2.error:
                break

            if not help_consumed and key in (ord("c"), ord("C")) and recovery is None:
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

            if (tracker is not None and not help_consumed and not slider_consumed
                    and (not selection_consumed or freeze_requested) and not escape_canceled):
                # Keyboard and fist requests share one raw-image action. C/R and
                # exit checks above cancel pending requests before this point.
                freeze_control.apply(interaction, frame, keyboard=freeze_requested or key in (ord("f"), ord("F")))

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
        if slider is not None:
            slider.cancel(interaction)
        if interaction is not None:
            interaction.history.clear()
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
