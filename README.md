# Reality Loom

A simple live camera preview with hand landmarks from MediaPipe Tasks Hand
Landmarker. It detects up to two hands, draws their 21 landmarks and connections,
and displays `Hands: 0`, `Hands: 1`, or `Hands: 2`. Each hand also has an `OPEN` or
`PINCH` label. It does not save images or video.

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
the thumb tip and index fingertip. These are visual indicators only; pinching
does not trigger an action.

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
No smoothing filters are applied. `--no-tracking` disables gesture detection and
all hand overlays along with MediaPipe.

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
minimum/mean/maximum pixel values for up to the first five successfully captured
frames. Statistics come from the original BGR image before inference or drawing.
Overlays are drawn on a separate preview copy. No frames or recordings are saved.

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

## Controls

- With the **Reality Loom** window focused, press **Q** or **Escape** to exit.
- Closing the preview window also exits.
- Press **Ctrl+C** in the terminal to stop the program.

## Troubleshooting

- If the camera cannot open, check Camo Studio and the iPad connection, then try
  another camera index.
- Close other applications that may be using the camera.
- Check Windows camera privacy settings and allow camera access for desktop apps.
- On Windows, the program tries DirectShow first. If opening the camera or reading
  its first frame fails, it releases the device and tries Media Foundation.
- If frames stop arriving, the program exits with a message. Check the connection
  and restart the preview.
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

To repeat the checks without opening a camera:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m py_compile .\main.py .\hand_tracking.py .\gestures.py .\tests\test_gestures.py
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
8. If the camera connection is interrupted, check for a clear failure message and
   that the program exits.
9. Run with `--no-tracking --debug-camera` and confirm the plain preview and
   limited camera logs still work without hand or gesture overlays.

The live camera preview, Camo compatibility, hand tracking, and pinch thresholds
still require your manual confirmation. Automated checks did not access the camera.
