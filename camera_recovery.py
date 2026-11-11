"""Reopen the selected camera without blocking the preview's event loop."""

from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Thread


@dataclass
class ReconnectResult:
    camera: object
    frame: object
    error: str | None = None


class CameraReconnect:
    """Own the old capture until release, then hand back a replacement capture."""

    def __init__(self, camera, camera_index, opener):
        self._results = Queue()
        self._cancelled = Event()
        self._thread = Thread(
            target=self._run, args=(camera, camera_index, opener),
            name="camera-reconnect", daemon=False,
        )
        try:
            self._thread.start()
        except RuntimeError:
            if camera is not None:
                camera.release()
            raise

    def _run(self, old_camera, camera_index, opener):
        try:
            if old_camera is not None:
                old_camera.release()
            if self._cancelled.is_set():
                return
            # Reuse the same opener, including its backend fallback and cleanup.
            camera, frame = opener(camera_index)
            error = None if camera is not None else f"Could not reopen camera {camera_index}."
            result = ReconnectResult(camera, frame, error)
        except Exception as error:
            result = ReconnectResult(None, None, f"Camera reconnection failed: {error}")

        self._results.put(result)
        # close() can run while the OS is still opening the camera. Publishing
        # before this check makes either close() or this worker release the result.
        if self._cancelled.is_set():
            self._discard_pending()

    def poll(self):
        """Return a completed attempt, or None while it is still running."""
        try:
            return self._results.get_nowait()
        except Empty:
            return None

    def _discard_pending(self):
        result = self.poll()
        if result is not None and result.camera is not None:
            result.camera.release()

    def close(self):
        """Cancel delivery; a pending OS call finishes and releases its capture."""
        self._cancelled.set()
        self._discard_pending()
