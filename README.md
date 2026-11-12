# Reality Loom

A live camera workspace with up to four independent panels. Create with two
pinches, select/drag with a fresh one-hand pinch, resize at opposite handles,
and toggle the active panel between LIVE and FROZEN with F or a deliberate fist.
Each panel owns its geometry, original frozen crop, and filter.

No images, video, panel history, or session state are saved to disk.

## Local setup

Use PowerShell from the project directory and the existing local environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Verified environment: Python 3.14.8, MediaPipe 1.2.2,
`opencv-contrib-python` 5.0.0.93 (`cv2` 5.0.0 with Windows GUI support),
and the already installed NumPy 2.5.4.

Keep only `opencv-contrib-python` installed: OpenCV distributions share the
`cv2` namespace. This environment already migrated from `opencv-python`.
If restoring an older environment with that package, uninstall it before
installing the requirements:

```powershell
.\.venv\Scripts\python.exe -m pip uninstall opencv-python
```

## Restore the model

The official HandLandmarker full float16 model comes from
[Google's model documentation](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker#models).
The application uses MediaPipe Tasks, not the legacy solutions API.

Download once, or restore after cloning:

```powershell
New-Item -ItemType Directory -Path .\models -Force | Out-Null
Invoke-WebRequest -Uri 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task' -OutFile '.\models\hand_landmarker.task'
```

The verified model has 7,819,105 bytes and SHA-256:

```text
fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1
```

Google's `latest` URL may change in future. Model binaries are ignored by Git.
The application never downloads a model at startup. A missing model produces
an actionable restore message. Its path is relative to `hand_tracking.py`.

## Run

Keep Camo Studio running on Windows with the iPad connected, and confirm its
own preview shows the feed. Then run:

```powershell
.\.venv\Scripts\python.exe .\main.py --camera 0 --debug-camera
```

Camera 0 is the currently reported Camo setup. Camera 1 is OBS Virtual Camera;
camera 2 is unavailable on this computer. Camera indices vary between computers.
The default is 0; `--camera 1` and `--camera 2` remain explicit alternatives.
The application never switches indices automatically.

```powershell
.\.venv\Scripts\python.exe .\main.py --help
.\.venv\Scripts\python.exe .\main.py --camera 0 --no-tracking --debug-camera
```

`--no-tracking` is a plain camera diagnostic preview: no model, panels, toolbar,
or gesture imports. C and the exit controls remain available.

## Controls

| Input in the focused preview | Action |
| --- | --- |
| Two pinches with no panels | Create the first panel. |
| New panel button / N | Begin explicit creation of another panel. |
| Fresh pinch inside a panel | Select it, bring it to front, and start dragging. |
| Both pinches at opposite active handles | Start resizing; can upgrade a drag. |
| Filter buttons / 1-4 | Change the active panel's filter, or the new-panel default if none is active. |
| F / deliberate fist hold | Toggle only the active panel's LIVE/FROZEN content. |
| Delete button / Delete key | Remove only the active panel. |
| R | Clear ALL panels and original crops; keep the default filter. |
| C | Reconnect the selected camera; cancel pending operations/creation. |
| Escape during new-panel creation with existing panels | Cancel the draft and keep existing panels. |
| Escape otherwise / Q / window close / Ctrl+C | Exit. Q always exits. |

New/Delete/filter actions are disabled during manipulation, explicit creation
with existing panels, recovery, or release-to-rearm. At the four-panel limit,
New is dimmed and attempts report the limit without adding or deleting anything.

## Create, select, and delete panels

`MAX_PANELS = 4` is defined in `panels.py`. Panels have stable session IDs, shown
on their borders. Bringing a panel forward does not change its ID. Deleted IDs
are not reused in the same run, including after clear-all or camera-size changes.

With no panels, the original two-hand workflow remains available. Both pinches
start a draft using their thumb/index midpoints as opposite corners. Move while
both pinches stay active, then release either while both tracks remain visible.
The last preview is committed if width and height are each at least 40 pixels.
Creation allows crossed corners by sorting them; invalid small drafts are discarded.

New panel enters an explicit creation mode. Existing panels remain visible but
cannot be selected, dragged, resized, filtered, frozen, or deleted during it.
The toolbar activation pinch is consumed: show two visible released pinches
before creating. A failed draft or tracking loss keeps existing panels and waits
for both releases before retrying. Escape cancels the draft when panels exist.
Without existing panels, Escape retains its normal exit behavior.

Successful creation adds and selects the new panel at the front. A fresh
OPEN-to-PINCH transition inside an existing panel selects the topmost panel
under that pointer and starts a no-snap drag. If hands select different panels
simultaneously, the lowest track ID wins. Only the active panel has resize handles.
An ongoing operation cannot transfer to another hand or another panel.

Delete removes only the active panel and selects the remaining topmost panel.
R is deliberately different: it clears the entire collection and every crop.
After New/Delete/filter actions, two visible released pinches are required before
another manipulation. Held action pinches cannot become delayed grabs or drafts.

## Drag and resize

One-hand dragging preserves the grab offset and size, with light position
smoothing reset at every grab. Pinching outside and entering the panel cannot
grab it. Release stops at the current position. Losing the owner stops movement
and requires visible hands to release before another grab; there is no takeover.

Two pinches within `RESIZE_HIT_RADIUS_PIXELS = 28.0` of diagonally opposite
active handles start RESIZING before an ordinary grab or fist activation.
A drag can upgrade if both current pointers meet those corner conditions.
Corner-to-pointer offsets prevent a jump, and each ID keeps its corner role.

Resizing stays in bounds and at least 40 pixels wide and high. Crossing pointers
stops at the minimum instead of swapping roles or flipping the image. Release
either pinch or lose a controlling track to keep the last valid geometry.
Both visible hands must release before another manipulation; it never falls
straight into dragging. One-hand dragging elsewhere still works.

Width and height change independently. Frozen content can stretch; there is no
aspect-ratio lock. Geometry settings in `interaction.py` include:

- `MIN_RECTANGLE_SIZE_PIXELS = 40.0`
- `POSITION_SMOOTHING = 0.35` for creation
- `DRAG_SMOOTHING = 0.35`
- `RESIZE_SMOOTHING = 0.35`
- `RESIZE_HIT_RADIUS_PIXELS = 28.0`

## Per-panel content and filters

LIVE samples the panel's region from the current raw live frame. FROZEN retains
one independent raw BGR crop captured with F or a valid fist activation.
Dragging transports that source; resizing always scales from the original crop.
Effects never accumulate into it, and no previously resized output is saved.

F is accepted only while PLACED. Raw capture excludes other panels, landmarks,
handles, toolbar, pointers, and instructions. Inference always receives live raw
pixels, even when frozen content visually covers a hand.

Panels composite back-to-front on a fresh frame copy. Each LIVE source comes
from raw input, never from a lower panel's composite. UI is drawn afterward.
The HUD shows count, active ID, operation, and active LIVE/FROZEN state. Toolbar
rows are separate from the top HUD and bottom fist feedback.

| Filter button / key | Effect |
| --- | --- |
| 1 ORIGINAL | Unfiltered source colors. |
| 2 GRAYSCALE | BGR luminance repeated in all three channels. |
| 3 PIXELATE | Coarse averaged blocks with sharp pixel boundaries. |
| 4 NEON | Colored edge outlines on black. |

Each panel keeps its own selected filter. Changing the active panel does NOT
change the default for future panels. With no active panel, filter selection
sets that default instead. New panels inherit the default, not the previously
active panel's filter. Clear-all keeps the default; deleted panel settings are gone.

Toolbar selection requires a fresh released-pinch-to-pinch transition inside
a button. Moving a held pinch onto it does not select. Newly appearing pinched
tracks must release first. The lowest track ID wins simultaneous button hits;
an explicit keyboard action wins a simultaneous gesture. A toolbar action
consumes the entire frame before panel operations or fist activation and cancels
pending fist progress. Keyboard shortcuts share the same action/rearm rules.

Small pointer rings show thumb/index midpoints (white released, yellow pinching).
Filters return independent uint8, three-channel BGR pixels at the panel size.
The implementations use only the existing OpenCV/NumPy packages. Named settings
in `filters.py` include `PIXEL_BLOCK_SIZE`, `NEON_EDGE_LOW`, `NEON_EDGE_HIGH`,
and `NEON_COLOR_BGR`.

## Deliberate fist toggle

Fully open the triggering hand while PLACED, then hold a closed fist with its
palm center outside the active panel for 0.8 seconds. Progress and activation
feedback appear near the bottom. The active panel alone toggles. Sustained fists
trigger once and require full-open rearming, not merely a released pinch.

Fist detection uses folded-finger distances relative to palm size; a thumb/index
pinch with the other fingers extended is not a fist. Hand labels are FIST, PINCH,
OPEN (fully extended fingers and thumb), or NEUTRAL. Existing drag/creation
release gates still use pinch release; full-open rearming is specific to fists.

Pose interruption or entering the active rectangle restarts the duration.
Hand loss/replacement requires a new OPEN observation. All ongoing fist holds
are consumed by one toggle so two fists cannot immediately undo each other.
F and the fist share one action per frame; F cancels pending fist progress.
Creation, dragging, resizing, toolbar actions, R, and C cancel holds and require
a new full-open observation before gesture activation resumes.

`FIST_HOLD_SECONDS = 0.8` uses a monotonic clock, never frame count. Other named
geometry thresholds in `gestures.py` are `FIST_FINGER_TIP_MAX`, `FIST_CURL_MARGIN`,
`FIST_THUMB_TIP_MAX`, `OPEN_FINGER_EXTENSION_MIN`, and `OPEN_THUMB_EXTENSION_MIN`.
`ACTIVATION_FEEDBACK_SECONDS = 1.2` is in `freeze_control.py`.

## Camera recovery and diagnostics

Windows capture still tries DirectShow first. Failure to open or read the first
usable frame releases that attempt before trying Media Foundation. No resolution,
codec, FPS, dependency, or global setting is changed by panel management.

C releases and reopens the same selected index in a worker. The window displays
Reconnecting camera... and still handles exit controls. Pending creation and
manipulation are canceled. All committed panels, original crops, filters, order,
and active ID survive if recovered dimensions match. A size change clears panels
safely but keeps the new-panel default and avoids reusing IDs. Both visible hands
must release before interaction resumes. A failed attempt allows C retry or exit.

Initial startup open failure still reports an error and exits. Read failures
pause with a retry message. Darkness alone never triggers failure or automatic
reconnection. `--debug-camera` logs raw backend, dimensions, dtype, and pixel
min/mean/max for five startup frames, then at most every two seconds. It restarts
the startup count after a successful reconnect; paused status frames are not logged.

To compare the black-preview regression, run camera-only mode, exit, then run
tracking mode with the same index. Compare both raw statistics and visible images:

```powershell
.\.venv\Scripts\python.exe .\main.py --camera 0 --no-tracking --debug-camera
.\.venv\Scripts\python.exe .\main.py --camera 0 --debug-camera
```

The report that switching indices restores the feed suggests a reopening issue
but does not prove the cause. No index-switch workaround is run automatically.
Check Camo/iPad connectivity, close other camera apps, and check Windows desktop
camera privacy settings if opening fails.

A driver call cannot be interrupted here. Exiting closes the UI and cancels
delivery; Python waits for a pending reopen to return so its capture is released.
Normal frame reading remains synchronous.

## Tests and intentional single-panel changes

`PanelCollection` stores panel data and uses one shared `RectangleInteraction`
for creation/drag/resize. Existing low-level geometry, gesture, filtering, frozen
content, and camera-recovery tests remain. Preview fixtures wrap their single
panel in a collection instead of constructing a controller for every panel.

Intentional preview-test changes:

- Toolbar actions now wait for both visible released pinches. Freeze-after-filter
  tests include that rearm frame instead of toggling immediately.
- Filter retention is per panel. Only no-active selection changes the new-panel
  default; R deletes active settings along with every panel.
- Status includes panel count/active ID instead of a single Rectangle heading.
- Window mocks use `waitKeyEx`, preserving full Delete-key codes on Windows.

New tests cover the panel limit, stable IDs, independent state, transactional
creation/cancellation, topmost hits, stacking and ownership, active resize
priority, selected-only actions, clear-all, overlapping raw-source rendering,
recovery, and consumed actions. All native camera/window/model entry points in
preview tests are mocked; other tests use synthetic landmarks and BGR arrays.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q .\main.py .\panels.py .\camera_recovery.py .\hand_tracking.py .\gestures.py .\freeze_control.py .\interaction.py .\filters.py .\filter_toolbar.py .\tests
.\.venv\Scripts\python.exe .\main.py --help
```

## Manual checks and limitations

1. Create the first panel, then use New/N. Keep pinches held and verify no draft
   starts until both release. Complete another panel; existing content must stay.
2. Cancel an in-progress new panel with Escape. Verify Q still exits, and Escape
   exits normally when not canceling a draft or when no panels exist.
3. Fill four panels. New must be dimmed and attempts must show the limit. Delete
   one and create again; remaining IDs must not change or be reused.
4. Overlap panels. Freshly pinch an overlap to select the topmost, or an exposed
   area of a lower panel to bring it forward. Check no snap or hand takeover.
5. Resize only the active handles, including drag-to-resize. Test release, loss
   of a hand, crossing, minimum size, bounds, and both-release rearming.
6. Give panels different filters and LIVE/FROZEN states. Move something in view;
   overlapping LIVE panels must remain live, even over frozen/effected panels.
7. Test F/fist, filters, Delete, and R. Only the active panel is affected until
   R explicitly clears all. Test a default filter before first creation and
   confirm new panels inherit it rather than an active panel's later changes.
8. Test toolbar overlap/held pinches, keyboard alternatives, busy-state disabling,
   C during creation/drag/resize, same-size recovery retention, and changed-size
   clearing. Repeat exit controls and plain `--no-tracking`.

Live testing remains manual. The 2D pose heuristics and spatial hand association
can miss poses or confuse IDs with occlusion, edge-on hands, or fast crossings.
Use good lighting and distinct, visible hands. Frozen width/height changes can
stretch images. Rendering cost grows with panel area/filter complexity; live
performance and camera recovery have not been tested by the automated checks.
