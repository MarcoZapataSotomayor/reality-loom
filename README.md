# Reality Loom

A simple live camera preview with hand landmarks from MediaPipe Tasks Hand
Landmarker. It detects up to two hands, draws their 21 landmarks and connections,
and displays `Hands: 0`, `Hands: 1`, or `Hands: 2`. Each hand also has an `OPEN` or
`PINCH` label. Pinch with both hands to create one rectangle, then release either
hand to place it. It does not save images or video.

## Set up the local environment

Run these commands from the project directory in PowerShell. Use the existing
`.venv`; activation is optional because the commands call its Python directly.

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Verified with Python **3.14.8**, MediaPipe **1.2.2**, and
`opencv-contrib-python` **5.0.0.93** (`cv2` reports **5.0.0**, with Windows GUI
support). The direct dependencies are pinned in `requirements.txt`; pip installs
their dependencies automatically.

MediaPipe requires `opencv-contrib-python`, which includes desktop GUI support.
Only one OpenCV distribution should be installed because they share the `cv2`
namespace. This environment was migrated from `opencv-python` by uninstalling it
before installing the requirements. If restoring an older environment that still
has `opencv-python`, run this command **before** installing the requirements:

```powershell
.\.venv\Scripts\python.exe -m pip uninstall opencv-python
```

Do not install another OpenCV variant alongside `opencv-contrib-python`.

## Download or restore the model

The official model is the **HandLandmarker (full), float16** bundle linked in
[Google's Hand Landmarker model documentation](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker#models).
The application uses the [MediaPipe Tasks Python API](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker?tab=Python),
not the legacy solutions API.

The model is stored locally at `models/hand_landmarker.task`. Download it once,
or restore it after cloning the project:

```powershell
New-Item -ItemType Directory -Path .\models -Force | Out-Null
Invoke-WebRequest -Uri 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task' -OutFile '.\models\hand_landmarker.task'
```

The downloaded model is **7,819,105 bytes**, with SHA-256:

```text
fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1
```

The source URL uses Google's `latest` model, so a future download may have a
different hash. Model binaries are excluded from Git. The application never
downloads a model at startup; it shows a restore instruction if the file is
missing. The model path is resolved relative to `hand_tracking.py`.

## Run the preview

Keep Camo Studio running on Windows with your iPad connected. Make sure Camo
Studio shows the iPad feed before starting the preview.

From the project directory in PowerShell, run:

```powershell
.\.venv\Scripts\python.exe .\main.py
```

The default camera index is `0`. Try these commands one at a time to find the
camera provided by Camo Studio; camera indices depend on your computer:

```powershell
.\.venv\Scripts\python.exe .\main.py --camera 0
.\.venv\Scripts\python.exe .\main.py --camera 1
.\.venv\Scripts\python.exe .\main.py --camera 2
```

For command help:

```powershell
.\.venv\Scripts\python.exe .\main.py --help
```

## Pinch detection

Bring your thumb tip and index fingertip together to pinch. Each hand has an
independent `OPEN` or `PINCH` state. While pinching, a thicker yellow line connects
the thumb tip and index fingertip. Two simultaneous pinches control rectangle
creation as described below.

`gestures.py` converts landmark coordinates to image pixels using both frame
dimensions. It divides the thumb/index distance by the palm size, measured from
the wrist to the middle-finger base knuckle. This ratio reduces sensitivity to
distance from the camera and avoids distortion from the frame's aspect ratio.

The named constants near the top of `gestures.py` are easy to adjust:

- `PINCH_CLOSE_THRESHOLD = 0.30`: an open hand enters PINCH at or below this ratio.
- `PINCH_OPEN_THRESHOLD = 0.45`: a pinched hand returns to OPEN at or above this
  ratio. Between the thresholds, the previous state is retained (hysteresis).
- `MIN_PALM_SIZE_PIXELS = 1.0`: smaller palm measurements reset to OPEN instead of
  dividing by a near-zero value.
- `MAX_HAND_MATCH_DISTANCE = 2.0`: the maximum movement for matching a hand between
  frames, in palm lengths.

Hand state follows nearby palm centers, rather than MediaPipe result positions
or left/right labels. For at most two hands, the detector checks all possible
associations, prefers the most valid matches, then the least total movement.
A hand absent from a frame loses its state immediately. A new or reappearing hand
starts OPEN and can immediately enter PINCH if its fingertips are close enough.

Simple spatial matching can confuse identities when hands overlap, cross, or
move very quickly. Perspective and a hand turned edge-on can also change the 2D
palm measurement. Thresholds are starting values to verify with your live feed.
No smoothing is applied to pinch states. Rectangle corner positions use light
smoothing. `--no-tracking` disables gesture detection, rectangle interaction, and
all hand overlays along with MediaPipe.

## Create one rectangle

The preview shows the current rectangle state and a short instruction:

1. **READY:** pinch with both tracked hands to start. Each thumb/index midpoint
   becomes one opposite corner of the rectangle.
2. **CREATING:** keep both hands pinching and move them to resize the yellow
   rectangle. Corners stay inside the image, and crossing them cannot create
   negative width or height.
3. Release either pinch while both hands are still tracked. The last preview is
   kept as **PLACED** if its width and height are each at least 40 pixels.
   A smaller rectangle is discarded.
4. A placed rectangle remains fixed even when hands move or disappear. Press
   **R** to clear it; only one rectangle can exist.
5. After R, a discarded small rectangle, or tracking loss during creation, the
   state is **WAITING FOR RELEASE**. Show two visible OPEN hands to return to
   READY, then pinch both again. Missing hands do not count as released hands.

During creation, losing either original track ID or seeing a replacement ID
cancels the unfinished rectangle instead of placing it. The existing spatial
hand matching still has limits when hands overlap or cross quickly.

`interaction.py` contains the rectangle geometry and state, without OpenCV or
MediaPipe dependencies. Named settings near the top are:

- `MIN_RECTANGLE_SIZE_PIXELS = 40.0`: minimum width **and** height for placement.
- `POSITION_SMOOTHING = 0.35`: how much each new corner position contributes per
  frame; smaller values reduce jitter but add lag, and `1.0` disables smoothing.

Smoothing follows each track ID before the corners are sorted. The release frame
does not move the rectangle because opening fingers can shift the midpoint.
All rendering uses the display copy; raw camera frames remain untouched. There
is no dragging, freezing of frames, or recording.

## Diagnose a black preview

Run these commands separately, closing the preview between runs. Both use the
same camera index, backend fallback, capture settings, and display loop.

First, disable tracking entirely. This mode does not import MediaPipe or load
the model, and it shows the camera image without hand overlays:

```powershell
.\.venv\Scripts\python.exe .\main.py --camera 0 --no-tracking --debug-camera
```

Then run with tracking enabled (the default):

```powershell
.\.venv\Scripts\python.exe .\main.py --camera 0 --debug-camera
```

For the currently reported setup, camera `0` previously worked through
DirectShow, camera `1` is OBS Virtual Camera, and camera `2` is unavailable. Keep
camera `0` for this comparison. The program never changes indices automatically.

`--debug-camera` prints the actual backend, frame width and height, data type, and
minimum/mean/maximum pixel values for the first five successfully captured frames,
then at most once every two seconds. The startup count restarts after a successful
reconnection. Statistics come from the original BGR image before inference or
drawing; paused/recovery status images are not counted as new frames. Overlays
are drawn on a separate preview copy. No frames or recordings are saved.

Code inspection found no full-frame clearing or replacement in inference or
drawing. Inference creates a separate RGB array. Drawing previously modified the
captured BGR image in place with landmarks and text; it now modifies only the
preview copy. Camera initialization still calls `VideoCapture()` followed by
`open(index, backend)` and does not set resolution, codec, FPS, or other capture
properties. These findings do not establish the cause of the black preview.

Compare whether both runs show the image and whether their raw pixel statistics
differ. All-zero statistics show that those captured frames contain black pixels,
but darkness alone is not considered a camera failure and does not trigger a
backend switch. Nonzero statistics also do not prove that the image displays
correctly. The live cause remains uncertain until the two runs are compared;
packages have not been changed for this diagnosis.

## Reconnect the selected camera

Press **C** in the preview to release and reopen the camera selected by
`--camera`. For `--camera 0`, recovery only opens index `0`; it never opens OBS
or another index as a workaround. It uses the existing DirectShow-first,
Media-Foundation-second fallback without changing capture format settings.

The window shows **Reconnecting camera...** while a worker releases the old
capture and attempts to open a replacement. The main thread continues handling
Q, Escape, window closing, and Ctrl+C. The last raw image is used only as a
clearly labeled status background; hand inference and interaction are paused.
Repeated C presses do not start overlapping attempts.

If reconnection fails, the window displays a failure message and instructions
to check Camo Studio and the iPad connection. Press C to retry the same index,
or Q/Escape to exit. A camera read failure also pauses the preview with a retry
message. The program does not automatically reconnect, including when frames
are completely black. Failure to open the camera at initial startup still
reports an error and exits as before.

Each reconnect attempt forgets gesture hand associations and pinch history, and
cancels unfinished rectangle creation. A placed rectangle is retained only if
the next successfully captured frame has exactly the same width and height.
A dimension change clears it. Failed attempts do not discard the provisionally
saved placed rectangle. After success, two visible OPEN hands are required before
interaction resumes. A retained rectangle then remains placed until R clears it.
Recovery also works with `--no-tracking`, without importing MediaPipe or a model.

Camera release/open calls depend on the driver. They run off the UI thread during
reconnection. If you exit during an attempt, the window closes and its result is
canceled; Python waits for the pending driver call to return so the worker can
release any newly opened capture. Normal frame reading remains synchronous.

The report that switching indices restores the feed suggests a reopening issue,
but does not prove the cause. C provides an explicit same-index retry to test it;
it is not a confirmed fix for the black-frame regression.

## Controls

- With the **Reality Loom** window focused, press **Q** or **Escape** to exit.
- Closing the preview window also exits.
- Press **Ctrl+C** in the terminal to stop the program.
- Press **C** to reconnect the current camera, or retry a failed reconnection.
- With tracking enabled, press **R** to clear or cancel the rectangle. Show both
  hands OPEN before starting another rectangle.

## Troubleshooting

- If the camera cannot open, check Camo Studio and the iPad connection, then try
  another camera index.
- Close other applications that may be using the camera.
- Check Windows camera privacy settings and allow camera access for desktop apps.
- On Windows, the program tries DirectShow first. If opening the camera or reading
  its first frame fails, it releases the device and tries Media Foundation.
- If a camera read fails, the preview pauses with a message. Check the connection
  and press C to retry, or exit. If frames are black but reads succeed, press C
  explicitly and compare the debug statistics; darkness alone is not a failure.
- If the model is missing, run the model download command above. If MediaPipe
  cannot load it, download the model again and check the dependency installation.
- If hands are not detected, keep the whole hand visible with good lighting and
  move it farther from the camera.

## Validation and manual checks

Syntax, imports, dependency consistency, and `--help` were checked. The model
initialized and processed three blank synthetic frames in `VIDEO` mode, reporting
zero hands. Inference uses RGB input converted from a BGR preview copy;
OpenCV draws the results on that copy and preserves the captured image. Timestamps
come from a monotonic clock and increase by at least one millisecond per frame.

MediaPipe printed native diagnostic warnings about feedback tensors and landmark
projection during the synthetic check; initialization and inference completed.

The gesture tests use synthetic landmarks and the standard-library `unittest`
runner, without importing OpenCV, MediaPipe, or a camera. They cover activation,
release, hysteresis, image/hand scales, result reordering, spatial association,
missing-hand resets, and degenerate palm size.

Rectangle tests also run without a camera or MediaPipe. They cover creation and
placement, midpoint coordinates, position smoothing, release-to-rearm, R resets,
minimum dimensions, crossed corners, bounds, result reordering, tracking loss,
and replacement hands. The camera-only mode remains independent of interaction.

Recovery tests use fake captures, controlled worker threads, mocked window calls,
and synthetic pixels. They check release-before-reopen, same-index retries,
failed reconnections, exit controls while pending, eventual capture cleanup,
gesture/rectangle resets, dimension-dependent placement retention, and periodic
debug logging. These checks do not access a camera or initialize a model.

To repeat the checks without opening a camera:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q .\main.py .\camera_recovery.py .\hand_tracking.py .\gestures.py .\interaction.py .\tests
.\.venv\Scripts\python.exe -c "import cv2, mediapipe, main, hand_tracking; print('Imports OK')"
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe .\main.py --help
```

For the live manual test:

1. Start Camo Studio, connect the iPad, and run the preview with the correct camera
   index.
2. With no hands visible, check that the label reads `Hands: 0`.
3. Show one hand, then two hands. Check the count and the landmarks and connections
   on each hand. Try moving your hands slowly.
4. Pinch with one hand, then release. Check the PINCH/OPEN label and yellow
   thumb/index connection. Make small fingertip movements near the boundary to
   check that the label does not rapidly flicker.
5. Keep both hands visible; pinch one while the other stays open, then swap.
   Move them slowly while keeping them apart to check that states stay with each
   hand. Repeat at different distances from the camera.
6. Remove a pinching hand while keeping the other visible. Reintroduce it with
   separated fingers and check that it is OPEN and the other hand retains its
   state. Expect a reset if tracking temporarily loses a hand.
7. Test Q, Escape, closing the window, and Ctrl+C in separate runs. Restart after
   each test to check that the camera was released.
8. If a camera read fails, check for a clear message, then retry with C or exit.
9. Run with `--no-tracking --debug-camera` and confirm the plain preview and
   limited camera logs still work without hand or gesture overlays.

For the rectangle manual test, run:

```powershell
.\.venv\Scripts\python.exe .\main.py --camera 0 --debug-camera
```

1. Pinch both hands while keeping them visible and separated. Check CREATING and
   move both hands to resize the yellow rectangle.
2. Move the corners across each other and toward the frame edges. Check that the
   outline stays in bounds and never flips into negative dimensions. If tracking
   loses a hand, expect cancellation instead.
3. Release either pinch with both hands still visible. Check PLACED and that moving
   or pinching again does not change the rectangle.
4. Press R while both hands are pinching. Check WAITING FOR RELEASE and that held
   pinches cannot restart creation. Show both hands OPEN, then pinch to try again.
5. Create a rectangle narrower or shorter than 40 pixels and release. Check that
   it is discarded and requires both hands to open before retrying.
6. During creation, move one hand out of view. Check that the unfinished rectangle
   disappears. Bring it back while pinching; creation must remain blocked until
   both hands are shown OPEN.
7. Repeat Q, Escape, window closing, and Ctrl+C exit checks. Also verify that
   `--no-tracking --debug-camera` shows the plain camera feed without interaction.

For the recovery manual test, use the same run command above:

1. With camera 0 selected, press C. Check the Reconnecting camera... status and
   that terminal messages mention only index 0, with the usual backend fallback.
2. If the preview is black, compare raw debug statistics before and after C. Let
   it run for several seconds to see the bounded periodic logs. Do not assume
   a successful reopen guarantees a visible image.
3. During rectangle creation, press C. Check that the unfinished rectangle is
   canceled, and held pinches cannot create another until both hands are OPEN.
4. Place a rectangle and press C again. If dimensions are unchanged, it should
   remain in place and resume in PLACED after both hands are OPEN. If dimensions
   change, it should be cleared. The program does not request a size change.
5. If a retry fails, restore Camo/iPad availability and press C again. Check that
   the window allows retry or exit. Repeat Q, Escape, window close, and Ctrl+C
   during recovery and after a failure in separate runs.
6. Repeat with `--no-tracking --debug-camera`; reconnection should remain usable
   without hand overlays, rectangle interaction, or model loading.

Live recovery and its effect on the intermittent black preview require your
manual confirmation. Automated checks did not access the camera.
