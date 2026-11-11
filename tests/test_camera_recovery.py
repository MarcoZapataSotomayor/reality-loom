"""Camera recovery checks using fake captures and synthetic frames only."""

from contextlib import ExitStack, redirect_stdout
from io import StringIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import unittest

import cv2
import numpy as np

from camera_recovery import CameraReconnect, ReconnectResult
import main


class CameraReconnectTests(unittest.TestCase):
    def finish(self, job):
        job._thread.join(timeout=3)
        self.assertFalse(job._thread.is_alive(), "Recovery worker did not finish")
        return job.poll()

    def test_release_happens_before_reopening_the_same_index(self):
        old, new = MagicMock(), MagicMock()
        frame = object()

        def opener(index):
            old.release.assert_called_once()
            self.assertEqual(index, 0)
            return new, frame

        job = CameraReconnect(old, 0, opener)
        result = self.finish(job)
        self.assertIs(result.camera, new)
        self.assertIs(result.frame, frame)
        self.assertIsNone(result.error)
        job.close()
        new.release.assert_not_called()  # The consumer now owns this capture.

    def test_failed_reconnection_returns_an_error_and_can_be_retried(self):
        old, new = MagicMock(), MagicMock()
        opener = MagicMock(side_effect=[(None, None), (new, object())])
        failed = CameraReconnect(old, 0, opener)
        result = self.finish(failed)
        self.assertIsNone(result.camera)
        self.assertIn("Could not reopen camera 0", result.error)
        failed.close()
        retry = CameraReconnect(None, 0, opener)
        self.assertIs(self.finish(retry).camera, new)
        self.assertEqual([call.args for call in opener.call_args_list], [(0,), (0,)])
        old.release.assert_called_once()
        retry.close()

    def test_opener_exception_is_reported(self):
        old = MagicMock()
        job = CameraReconnect(old, 0, MagicMock(side_effect=RuntimeError("Device busy")))
        self.assertIn("Device busy", self.finish(job).error)
        old.release.assert_called_once()
        job.close()

    def test_exit_while_opening_releases_the_eventual_capture(self):
        entered, unblock = Event(), Event()
        old, new = MagicMock(), MagicMock()

        def opener(index):
            entered.set()
            if not unblock.wait(timeout=3):
                raise RuntimeError("Test did not unblock the opener")
            return new, object()

        job = CameraReconnect(old, 0, opener)
        try:
            self.assertTrue(entered.wait(timeout=3))
            self.assertIsNone(job.poll())
            job.close()  # Must return without waiting for the blocked opener.
            self.assertTrue(job._thread.is_alive())
        finally:
            unblock.set()
            self.finish(job)
        old.release.assert_called_once()
        new.release.assert_called_once()

    def test_exit_releases_a_completed_unclaimed_capture(self):
        new = MagicMock()
        job = CameraReconnect(None, 0, lambda index: (new, object()))
        job._thread.join(timeout=3)
        self.assertFalse(job._thread.is_alive())
        job.close()
        new.release.assert_called_once()
        self.assertIsNone(job.poll())

    def test_exit_during_release_skips_opening_a_new_capture(self):
        entered, unblock = Event(), Event()
        old, opener = MagicMock(), MagicMock()

        def release():
            entered.set()
            unblock.wait(timeout=3)

        old.release.side_effect = release
        job = CameraReconnect(old, 0, opener)
        try:
            self.assertTrue(entered.wait(timeout=3))
            job.close()
        finally:
            unblock.set()
            self.finish(job)
        opener.assert_not_called()


class CameraPreviewRecoveryTests(unittest.TestCase):
    def preview(self, keys, recovery_factory, opener, visible=1, tracking=False):
        """Replace every native window/camera entry point used by the preview."""
        with ExitStack() as stack:
            output = stack.enter_context(redirect_stdout(StringIO()))
            arguments = ["main.py", "--camera", "0"]
            if not tracking:
                arguments.append("--no-tracking")
            stack.enter_context(patch.object(main.sys, "argv", arguments))
            opening = stack.enter_context(patch.object(main, "open_camera", side_effect=opener))
            recovery = stack.enter_context(patch.object(main, "CameraReconnect", side_effect=recovery_factory))
            stack.enter_context(patch.object(cv2, "namedWindow"))
            stack.enter_context(patch.object(cv2, "imshow"))
            stack.enter_context(patch.object(cv2, "waitKey", side_effect=keys))
            if isinstance(visible, list):
                stack.enter_context(patch.object(cv2, "getWindowProperty", side_effect=visible))
            else:
                stack.enter_context(patch.object(cv2, "getWindowProperty", return_value=visible))
            destroy = stack.enter_context(patch.object(cv2, "destroyAllWindows"))
            status = stack.enter_context(patch.object(main, "draw_camera_status", wraps=main.draw_camera_status))
            self.assertEqual(main.main(), 0)
            destroy.assert_called_once()
        return opening, recovery, status, output.getvalue()

    def test_failed_reconnect_shows_retry_and_accepts_c_again(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        old, new = MagicMock(), MagicMock()
        calls = []

        def opener(index):
            calls.append(index)
            if len(calls) == 1:
                return old, frame
            old.release.assert_called_once()
            return (None, None) if len(calls) == 2 else (new, frame)

        def recover(capture, index, opening):
            if capture is not None:
                capture.release()
            camera, first_frame = opening(index)
            result = ReconnectResult(camera, first_frame, None if camera is not None else "Device busy")
            return MagicMock(poll=MagicMock(return_value=result))

        opening, recovery, status, output = self.preview(
            [ord("c"), -1, ord("C"), -1, ord("q")], recover, opener,
        )
        self.assertEqual(calls, [0, 0, 0])
        self.assertEqual(recovery.call_count, 2)
        messages = [call.args[1] for call in status.call_args_list]
        self.assertIn("Reconnecting camera...", messages)
        self.assertIn("Camera reconnection failed.", messages)
        self.assertIn("press C to retry", output)
        new.release.assert_called_once()
        self.assertFalse(np.any(frame))  # Display/status drawing left raw pixels intact.

    def test_exit_controls_still_work_while_reconnection_is_pending(self):
        for control in ("q", "Q", "escape", "window", "Ctrl+C"):
            with self.subTest(control=control):
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                old = MagicMock()
                job = MagicMock(poll=MagicMock(return_value=None))

                def recover(capture, index, opening):
                    capture.release()
                    return job

                second_key = {"q": ord("q"), "Q": ord("Q"), "escape": 27,
                              "window": -1, "Ctrl+C": KeyboardInterrupt()}[control]
                self.preview([ord("c"), second_key], recover,
                             lambda index: (old, frame),
                             visible=[1, 0] if control == "window" else 1)
                job.close.assert_called_once()
                old.release.assert_called_once()

    def test_read_failure_allows_exit_without_automatic_reconnect(self):
        camera = MagicMock()
        camera.read.return_value = (False, None)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        opening, recovery, status, output = self.preview(
            [-1, ord("q")], MagicMock(), lambda index: (camera, frame),
        )
        opening.assert_called_once_with(0)
        recovery.assert_not_called()
        self.assertEqual(status.call_args.args[1], "Could not read a camera frame.")
        camera.release.assert_called_once()

    def test_dark_frames_do_not_trigger_failure_or_reconnection(self):
        camera = MagicMock()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        camera.read.return_value = (True, frame)
        opening, recovery, status, output = self.preview(
            [-1, ord("q")], MagicMock(), lambda index: (camera, frame),
        )
        recovery.assert_not_called()
        status.assert_not_called()
        camera.release.assert_called_once()

    def test_tracking_pipeline_resets_and_checks_recovered_dimensions(self):
        first_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        recovered_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        old, new, tracker, pinch, interaction = [MagicMock() for _ in range(5)]
        tracker.detect.return_value = SimpleNamespace(hand_landmarks=[])
        pinch.update.return_value = []
        tracking_module = SimpleNamespace(
            HandTracker=MagicMock(return_value=tracker), draw_hand_landmarks=MagicMock(),
        )

        def recover(capture, index, opener):
            capture.release()
            camera, frame = opener(index)
            return MagicMock(poll=MagicMock(return_value=ReconnectResult(camera, frame)))

        with patch.dict(main.sys.modules, {"hand_tracking": tracking_module}), \
                patch("gestures.PinchDetector", return_value=pinch), \
                patch("interaction.RectangleInteraction", return_value=interaction), \
                patch.object(main, "draw_rectangle_interaction"):
            self.preview([ord("c"), -1, ord("q")], recover,
                         MagicMock(side_effect=[(old, first_frame), (new, recovered_frame)]),
                         tracking=True)
        pinch.reset.assert_called_once()
        interaction.prepare_camera_reconnect.assert_called_once()
        interaction.finish_camera_reconnect.assert_called_once_with((640, 480), (1280, 720))
        tracker.close.assert_called_once()
        old.release.assert_called_once()
        new.release.assert_called_once()


class CameraDebugLoggerTests(unittest.TestCase):
    def test_periodic_statistics_have_a_bounded_rate(self):
        logger = main.CameraDebugLogger()
        times = [0.0] * 5 + [0.1, 1.9, 2.0, 2.1, 4.0]
        with patch.object(main.time, "monotonic", side_effect=times), \
                patch.object(main, "log_camera_frame") as report:
            for _ in times:
                logger.report(object(), object())
        self.assertEqual([call.args[2] for call in report.call_args_list], [1, 2, 3, 4, 5, 8, 10])


if __name__ == "__main__":
    unittest.main()
