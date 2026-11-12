# Reality Loom

A simple live camera preview with hand landmarks from MediaPipe Tasks Hand
Landmarker. It detects up to two hands, draws their 21 landmarks and connections,
and displays `Hands: 0`, `Hands: 1`, or `Hands: 2`. Each hand also has an `OPEN`,
`PINCH`, `FIST`, or `NEUTRAL` label. Pinch with both hands to create one rectangle, then release either
hand to place it. A fresh one-hand pinch inside the placed rectangle lets you drag
it without resizing. Press F, or deliberately hold a fist outside the placed
rectangle, to freeze/unfreeze its image content in memory. Video outside it
remains live. It does not save images or video.

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
independent pinch state. While pinching, a thicker yellow line connects
the thumb tip and index fingertip. Two simultaneous pinches control rectangle
creation as described below.

`gestures.py` converts landmark coordinates to image pixels using both frame
dimensions. It divides the thumb/index distance by the palm size, measured from
the wrist to the middle-finger base knuckle. This ratio reduces sensitivity to
distance from the camera and avoids distortion from the frame's aspect ratio.

The named constants near the top of `gestures.py` are easy to adjust:

- `PINCH_CLOSE_THRESHOLD = 0.30`: a released pinch activates at or below this ratio.
- `PINCH_OPEN_THRESHOLD = 0.45`: a pinch releases at or above this
  ratio. Between the thresholds, the previous state is retained (hysteresis).
- `MIN_PALM_SIZE_PIXELS = 1.0`: smaller palm measurements reset to OPEN instead of
  dividing by a near-zero value.
- `MAX_HAND_MATCH_DISTANCE = 2.0`: the maximum movement for matching a hand between
  frames, in palm lengths.

Hand state follows nearby palm centers, rather than MediaPipe result positions
or left/right labels. For at most two hands, the detector checks all possible
associations, prefers the most valid matches, then the least total movement.
A hand absent from a frame loses its state immediately. A new or reappearing hand
starts with a released pinch and can immediately pinch if its fingertips are close enough.

Pinch release is separate from the explicit full-open pose used to rearm fist
activation. The OPEN label now means four extended fingers and an extended thumb.
FIST means folded fingers with the thumb near the palm. A released pinch that
meets neither pose is NEUTRAL. An extended-finger thumb/index pinch is PINCH,
not FIST. Existing pinch creation and drag/release behavior is unchanged.

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
4. A placed rectangle stays fixed until a fresh one-hand grab inside it. Use the
   drag controls below to move it, or press **R** to clear it. Two-hand creation
   is available only when no rectangle exists.
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
- `DRAG_SMOOTHING = 0.35`: position smoothing while dragging a placed rectangle.
  It starts fresh at each grab and does not change the width or height.

Smoothing follows each track ID before the corners are sorted. The release frame
does not move the rectangle because opening fingers can shift the midpoint.
All rendering uses the display copy; raw camera frames remain untouched.

## Drag the placed rectangle

1. Move one OPEN hand's thumb/index midpoint inside the placed rectangle, then
   pinch. The same track ID must have been seen OPEN on the previous frame.
   The label changes from **PLACED** to **DRAGGING**.
2. Move that pinched hand to translate the rectangle. The original grab offset
   is retained, so the rectangle does not snap to the hand. Light smoothing
   reduces jitter, and the entire rectangle stays within the frame bounds.
3. Release the pinch to drop it immediately at its current displayed position.
   Width and height do not change. Opening fingers does not move the rectangle.
4. To grab again, make another OPEN-to-PINCH transition inside the rectangle.
   Pinching outside and moving inside cannot start a drag. A hand appearing
   already pinched also cannot grab until it has been observed OPEN first.

Only one hand controls a drag. Other hands and MediaPipe result reordering do
not change ownership. If both hands make eligible grabs in the same frame, the
lowest track ID wins. This rule is deterministic and does not depend on which
result appears first.

Losing the controlling track stops dragging without moving the rectangle. Held
pinches cannot take over. Show the currently visible hands OPEN before trying a
new grab; no visible hands does not count as a release. A single visible OPEN
hand can rearm dragging after hand loss. The existing spatial tracking can still
confuse identities when hands overlap or cross quickly.

**R** clears the rectangle and all interaction history, then requires both hands
OPEN before another two-hand creation. **C** stops a drag and keeps its current
rectangle provisionally, using the existing camera recovery rules: unchanged
dimensions retain it, changed dimensions clear it, and both hands must be OPEN
before interaction resumes. `--no-tracking` keeps the plain camera preview.

If a normal frame-size change leaves room for the placed rectangle, it is moved
inside the new bounds without resizing. If its fixed size cannot fit, it is
cleared safely and both hands must be OPEN before creating again.

## Toggle LIVE and FROZEN content

Press **F** while the rectangle is **PLACED** to switch its content from **LIVE**
to **FROZEN**, or back again. Content mode is shown on a separate line from the
PLACED/DRAGGING interaction state. F is ignored when there is no placed rectangle,
while dragging, during camera recovery/rearming, or while capture is paused with
an error. It is also ignored in `--no-tracking` mode.

- **LIVE:** the rectangle shows the current camera image at its current location.
  Dragging moves its outline; it does not carry an earlier live crop.
- **FROZEN:** F copies the current rectangle region from the raw BGR camera frame,
  before any overlays are applied to those pixels. This independent crop is the
  only retained image. Nothing is saved to disk and no temporal history is kept.
  Dragging carries that exact image, without recapturing or resizing it.

The rest of the preview stays live in either mode. Hand inference always uses
the live raw camera image, even when frozen content visually covers a hand.
The frozen image is composited onto the display copy before landmarks, borders,
labels, and instructions are drawn, so those overlays remain visible and never
become part of the captured image.

Press F again after dropping a frozen rectangle to return to LIVE and release
the stored crop. A later F captures new raw content at the rectangle's current
position. **R** clears both geometry and the image. **C** cancels dragging and
preserves frozen content only if its rectangle survives recovery with unchanged
frame dimensions. Changed dimensions or any other rectangle reset clear both.
Failed reconnect attempts retain the provisional rectangle and crop, and both
hands must still be OPEN after recovery before interaction resumes.

## Toggle content with a deliberate fist

1. Place a rectangle and keep the hand you will use outside it. Show that hand
   fully OPEN first, with all four fingers extended and the thumb extended.
2. Close it into a fist with the thumb near the palm. Keep the palm center outside
   the rectangle and hold the pose continuously for **0.8 seconds**.
3. The bottom of the preview shows hold progress, then a brief LIVE/FROZEN activation
   message. The same action and raw-image capture are used by F and the fist.
4. Holding the fist longer does not toggle again. Fully open the triggering hand
   before starting another hold; a neutral pose or a released pinch is not enough.

Both hands have independent timers tied to their tracked IDs. A pose interruption
or moving the palm inside the rectangle cancels progress and restarts the full
hold duration when the fist is valid again. Hand loss or replacement also cancels
progress and requires a new full-open observation. A hand first appearing as a
fist cannot activate until it has been seen OPEN.

If both hands qualify, content toggles once. All ongoing fist holds are consumed
by a toggle, so two fists cannot immediately undo each other; each must open before
its next activation. F remains available without the gesture, but using it cancels
and disarms pending fist holds. If F and a fist qualify in the same frame, there
is only one toggle.

Creation, dragging, recovery, and rearming disable fist activation and require a
full-open observation after returning to PLACED. A valid pinch grab is processed
first and wins over a fist activation in the same frame. R and C clear pending
holds and rearm state. Pinching itself never requests a content toggle; it keeps
its existing creation/dragging role. `--no-tracking` loads no gesture logic.

The geometry and timing settings are named near the top of `gestures.py`:

- `FIST_HOLD_SECONDS = 0.8`: continuous hold duration, measured with a monotonic
  clock, independent of frame count.
- `FIST_FINGER_TIP_MAX = 0.85`: maximum fingertip distance from the palm center,
  divided by palm size, for each folded finger.
- `FIST_CURL_MARGIN = 0.10`: allowed radial margin beyond the finger's middle joint
  when comparing tip/joint distances from the wrist, in palm lengths.
- `FIST_THUMB_TIP_MAX = 0.85`: maximum thumb-tip distance from the palm center,
  divided by palm size.
- `OPEN_FINGER_EXTENSION_MIN = 0.25`: minimum extra wrist distance of each tip
  beyond its middle joint, in palm lengths, for the full-open pose.
- `OPEN_THUMB_EXTENSION_MIN = 0.20`: minimum thumb extension away from the
  little-finger knuckle, in palm lengths. OPEN also requires released tip separation.

`freeze_control.py` combines keyboard/gesture requests into one toggle per frame.
Its `ACTIVATION_FEEDBACK_SECONDS = 1.2` controls the brief confirmation message.

These are simple 2D landmark heuristics, not a trained pose classifier. Keep the
palm visible, fingers clearly folded or extended, and use good lighting. Edge-on
hands, occluded fingertips, unusual thumb positions, or overlapping hands can
produce missed or incorrect poses. The existing spatial hand matching can also
confuse IDs during crossings. Thresholds are starting values to check on your
live feed; pinch release alone deliberately does not rearm the fist gesture.

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
saved placed rectangle or its frozen image. If the rectangle is cleared, its
image is released as well. After success, two visible OPEN hands are required before
interaction resumes. A retained rectangle can then be grabbed with a fresh pinch
or cleared with R; an interrupted drag never resumes automatically.
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
- Press **F** while PLACED to toggle LIVE/FROZEN content. Drop a dragged rectangle
  before toggling. No images are written to disk.
- Or fully open a hand, then hold a closed fist outside the PLACED rectangle for
  0.8 seconds. Fully open that hand again before another activation.

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
zero hands. Inference uses RGB input converted from the live raw BGR frame;
OpenCV composites content and draws results on a separate display copy. Timestamps
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
and replacement hands. Dragging tests cover fresh grab transitions, outside
pinches, offsets, fixed dimensions, smoothing resets, bounds, release, hand loss,
ownership, simultaneous grabs, and R/C resets. The camera-only mode remains
independent of interaction.

Frozen-content tests use synthetic BGR images and mocked camera/window calls.
They cover independent copies, raw pixels without overlays, LIVE/FROZEN toggling,
unchanged image identity and dimensions while moving, fractional positions, reset,
and recovery retention/clearing. Preview-loop checks verify inference sees live
input, overlays stay above the frozen composite, and F is ignored during recovery
and in camera-only mode. No camera or MediaPipe model is initialized by these tests.

Fist tests cover palm-relative geometry, full-open versus pinch/neutral poses,
scale/aspect-ratio changes, monotonic timing at different frame intervals, single
activation per hold, interruptions, lost/replaced/reordered IDs, simultaneous fists,
drag priority, and keyboard deduplication. Preview tests also check that R/C cancel
completed holds before they toggle, and that the existing raw frozen content remains
independent of overlays and later frames.

Recovery tests use fake captures, controlled worker threads, mocked window calls,
and synthetic pixels. They check release-before-reopen, same-index retries,
failed reconnections, exit controls while pending, eventual capture cleanup,
gesture/rectangle resets, dimension-dependent placement retention, and periodic
debug logging. These checks do not access a camera or initialize a model.

To repeat the checks without opening a camera:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q .\main.py .\camera_recovery.py .\hand_tracking.py .\gestures.py .\freeze_control.py .\interaction.py .\tests
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
   open hands or holding a pinch from creation does not change the rectangle.
4. Press R while both hands are pinching. Check WAITING FOR RELEASE and that held
   pinches cannot restart creation. Show both hands OPEN, then pinch to try again.
5. Create a rectangle narrower or shorter than 40 pixels and release. Check that
   it is discarded and requires both hands to open before retrying.
6. During creation, move one hand out of view. Check that the unfinished rectangle
   disappears. Bring it back while pinching; creation must remain blocked until
   both hands are shown OPEN.
7. Repeat Q, Escape, window closing, and Ctrl+C exit checks. Also verify that
   `--no-tracking --debug-camera` shows the plain camera feed without interaction.

For the dragging manual test, use the same run command above:

1. Place a rectangle. Move an OPEN hand inside, then pinch. Check DRAGGING and
   that the rectangle does not jump to the hand at grab time.
2. Move slowly toward all frame edges. Check light smoothing, unchanged dimensions,
   and that the whole rectangle stays visible. Release to drop it without drift.
3. Pinch outside and move inside while holding the pinch. Check that it stays
   PLACED. Open and pinch again inside to grab.
4. Drag with one hand while the other pinches and moves. Check that ownership
   stays with the original hand. Move the controlling hand out of view; the
   rectangle must stop, with no takeover by an already-pinching hand.
5. Show visible hands OPEN, then make a new grab. A returning hand still pinching
   should not automatically resume dragging.
6. During a drag, press R and check clearing/rearming. Place another rectangle,
   drag it, and press C. Check recovery preservation and that both hands must be
   OPEN before any fresh grab.
7. Confirm two-hand creation cannot resize or replace a placed rectangle, and
   verify Q, Escape, window closing, Ctrl+C, and `--no-tracking` still work.

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

For the frozen-content manual test, use:

```powershell
.\.venv\Scripts\python.exe .\main.py --camera 0 --debug-camera
```

1. Place a rectangle and press F. Check separate PLACED and FROZEN labels. Move
   something in view: the crop stays still while the surrounding video stays live.
2. Grab and drag the frozen rectangle. Check that the same image moves with it,
   at the same size. Press F during dragging and confirm it has no effect.
3. Move a hand behind the frozen image. Check that live landmarks and pinch/drag
   interaction still follow it and appear above the frozen pixels.
4. Drop the rectangle, press F to return to LIVE, then drag it. Check that its
   content follows the camera image at the current location rather than carrying
   a previously viewed crop. Press F again to capture new content there.
5. Press R and check that rectangle and image disappear. Create again and check
   the initial content mode is LIVE.
6. Freeze again and press C. With unchanged dimensions, check that the same crop
   returns after recovery and both-OPEN rearming; a dimension change must clear
   both rectangle and image. Pressing F during recovery must do nothing.
7. Check F with no rectangle and with `--no-tracking`, and repeat Q, Escape,
   window closing, and Ctrl+C exit checks.

For the fist manual test, use the same run command above:

1. Place a rectangle, show one fully OPEN hand outside it, then hold a closed fist.
   Check the hold progress and a single toggle after about 0.8 seconds.
2. Keep holding. Check there are no repeated toggles. Try a neutral hand or a
   released pinch; neither should rearm it. Fully open, then hold a fist again.
3. Make a thumb/index pinch while extending the other fingers. Check it does not
   activate the fist toggle. Try the fist palm center inside the rectangle as well.
4. Interrupt a partial hold or move the hand out of view. Reintroduce it as a fist;
   check it must be opened again before a new complete hold.
5. Arm both hands and hold two fists. Check only one toggle occurs and both need
   to open again. Press F near the end of a hold; check no immediate second toggle.
6. Try a pinch grab as another hand's hold completes. Check dragging wins. Test
   creation, dragging, R, and C; held fists must not activate until a full-open
   observation is made again while PLACED.
7. Repeat the existing frozen-image, inference, exit-control, recovery, diagnostic,
   and `--no-tracking` checks. No camera behavior or dependency changes are needed.

Live fist recognition and its interaction with frozen content require your
manual confirmation. Automated checks did not access the camera.
