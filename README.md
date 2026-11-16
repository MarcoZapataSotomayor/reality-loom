# Reality Loom

A live OpenCV camera workspace with up to four independent panels. Explicit
SELECT, MOVE, RESIZE, and CREATE tools control panel selection and geometry.
Each panel keeps its filter, frozen crop, and rolling video delay independently.
No images, video, history, or session data are written to disk.

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
history buffer, or gesture imports. C and the exit controls remain available.

## Optional first-panel tutorial

An empty workspace starts with a compact **Create with your hands** card over
the usual bottom controls area. Freshly pinch **Start tutorial** or press **U**,
or choose **Free play** / **G**. Existing workspace keyboard shortcuts such as
N also dismiss the card into free play for experienced users. The camera stays
visible and live throughout. Nothing about this choice is persisted: the card
appears once per session and does not reopen after R, skipping, or completion.

The tutorial observes real workspace events and teaches three actions:

1. **Create:** the normal CREATE tool is prepared behind its release gate. Two
   static corner guides suggest a region; the actual rectangle preview follows
   the existing two-hand creation geometry. Only successful placement advances.
2. **Move:** the normal MOVE tool activates after release. Pinch inside the
   created panel, drag it, then release. Final displacement must be at least
   `TUTORIAL_MOVE_MIN_FRAME_FRACTION = 0.05` of the raw frame diagonal (40 pixels
   at 640x480, about 73 pixels at 1280x720). Merely starting a drag, moving too
   little, losing the controller, or canceling does not advance the step.
3. **Freeze:** return to SELECT, release, then activate the visible **Freeze**
   action or press **F**. Only a successful source-aware freeze completes the
   tutorial. Brief success feedback appears, the panel remains frozen in place,
   and normal free-play controls return after release.

Only step-relevant controls and an always-visible **Skip / G** action are shown.
Skipping preserves committed geometry/content, discards a draft or stops an
unfinished edit safely, and requires release before free-play gestures resume.
Fist activation and unrelated tool/filter/time/delete/clear actions are paused
during the tutorial; step 3 teaches the visible Freeze action and F alternative.
Every transition uses existing release gates, manipulation, and content logic.
The small action feed is bounded to 16 events and stores no images.

H pauses progression and safely cancels unfinished gestures. Close help to
resume the current step after release. Help includes a **Tutorial / U** entry
to start again, plus **Skip / G** while a tutorial is active. If any panels
already exist, starting explains the empty-workspace requirement and preserves
them. To replay, skip/finish, close help, clear with R in free play, then use
H → Tutorial or U. There are no automatic deletions or replacements.

Q still exits and C still reconnects, including from tutorial help. Recovery
cannot complete a drag or freeze step. A retained tutorial panel resumes its
step after release; if a size change clears it, guidance returns to Create.
Escape retains the existing edit/creation/exit semantics; use G to leave the
tutorial without exiting. `--no-tracking` never initializes or displays the
welcome card, tutorial, or tutorial controls.

## Controls

The preview must have keyboard focus. The top toolbar row selects a tool; the
second row contains actions for the active panel. Dim controls are unavailable.

| Keyboard / control | Action |
| --- | --- |
| V / Select | Select and raise a panel with a fresh pinch, without moving it. Default tool. |
| M / Move | Freshly pinch inside the active panel to drag it. Other panels are ignored. |
| S / Resize | Pinch diagonally opposite handles of the active panel. |
| N / New | Enter CREATE; use two pinches, move, then release either to place. |
| F / Freeze or Unfreeze | Freeze the displayed raw source, or return to the previous LIVE/DELAYED mode. |
| E / Effects | Open/close the existing four filter choices. |
| 1-4 | Original, Grayscale, Pixelate, Neon. Works with Effects closed too. |
| Y / Time | Open/close the Delay toggle and delay slider. |
| T / Delay | Toggle LIVE/DELAYED while keeping the panel's configured delay. Unfreeze first. |
| [ / ] | Adjust the idle DELAYED panel's delay by -/+ 0.1 s, even with Time closed. |
| Delete / Delete button | Delete only the active panel. |
| R | Clear all panels and frozen crops while idle, keeping the default filter and increasing session IDs. |
| H | Toggle compact help. Gestures and workspace keys pause while it is visible. |
| U / Tutorial | Start/replay the optional tutorial with an empty workspace; also available in help. |
| G / Skip or Free play | Dismiss the welcome card or safely leave an active tutorial. |
| D | Toggle landmark skeletons and per-hand debug labels; initially hidden. |
| C | Cancel pending work and reconnect the same selected camera. |
| Q / window close / Ctrl+C | Exit. Q always exits, including during help or an operation. |

Escape depends on context:

- Inside help, close help.
- During a MOVE/RESIZE operation, restore its starting geometry and return to
  SELECT. An idle MOVE/RESIZE tool also returns to SELECT without exiting.
- During slider capture, restore its starting delay and return to SELECT.
- During CREATE with existing panels, discard the draft and keep those panels.
- During CREATE without existing panels, or idle SELECT, exit as before.

Use E or Y again to close a contextual submenu, or switch tools. Escape in idle
SELECT retains exit behavior even when a contextual submenu is open.

## Tools and interaction priorities

Startup is SELECT with no panels. Two pinches alone no longer create a panel:
choose New/N first. CREATE blocks competing panel actions. A valid draft needs
at least 40 pixels in each dimension. Tracking loss or a too-small draft discards
only that draft and waits for release; existing panels survive. Successful
creation activates the new panel and returns to SELECT.

SELECT uses fresh released-pinch-to-pinch transitions. The topmost panel wins
in overlaps. Selecting an exposed part of a lower panel raises it without
changing geometry. Simultaneous selection uses the lowest stable hand track ID.
MOVE never implicitly selects a different panel. RESIZE only operates on the
active panel, with fixed hand/corner roles, minimum size, bounds, and crossing
protection from the existing geometry controller. There is no automatic
MOVE-to-RESIZE upgrade. Only RESIZE displays corner handles.

Tool switches, creation completion, panel selection, and toolbar actions require
release before gestures resume. When prompted, show both visible hands with
released pinches. A held pinch cannot become a delayed grab, creation, or button
press. The controlling track ID owns movement/resize until release or loss;
there is no automatic hand takeover. Losing a controller keeps the last valid
geometry and displays tracking-loss feedback. Escape only rolls back a currently
active edit, not one that already ended on release/loss.

During an active edit or slider capture, competing tool, content, filter, delete,
and creation controls are blocked. H and C safely stop unfinished work, keeping
committed content and the last valid geometry. R is an explicit idle clear-all
and is blocked during creation, manipulation, slider capture, help, or recovery.
Q always exits. Normal release completes movement in the current tool.

## Contextual panel actions

Freeze/Unfreeze, Effects, Time, and Delete are shown in the second toolbar row;
they are disabled without an active panel. Effects and Time are mutually
exclusive. While either submenu is open, canvas selection/manipulation and the
fist shortcut are paused. Toolbar gestures consume every currently pinched hand
before any panel action, so UI selections cannot also grab or resize a panel.

Each panel owns ORIGINAL, GRAYSCALE, PIXELATE, or NEON filtering. Filters operate
on raw source pixels and never accumulate into the saved crop or history.
Keys 1-4 with no active panel retain the existing new-panel default-filter
behavior; panel-only controls remain dim. New panels inherit that default and
always start LIVE with a configured delay of 2.0 seconds. Selecting/changing
another panel does not change its neighbors' filters or modes.

LIVE samples the current raw screen region. DELAYED samples that panel's current
screen region from a shared historical frame: moving/resizing resamples the
region, rather than transporting a fixed video crop. F/Freeze and a valid fist
capture whichever raw source was displayed, before filters and UI. FROZEN
transports its original independent crop, and resizing always scales that crop.
Unfreezing restores the previous LIVE or DELAYED mode and configured delay.

Time reveals the Delay toggle and its slider. A fresh pinch on the track starts
capture with one stable hand owner. Horizontal movement maps to 0.5-2.5 seconds,
clamped and rounded to 0.1-second steps (half steps round upward). Capture
continues outside the track until release/loss. Another hand cannot take over.
The video continues advancing at that rolling offset; this is not timeline
scrubbing or paused playback. Bracket keys work without visible hands; if a step
coincides with pinches, the release gate consumes them. LIVE/FROZEN, creation,
manipulation, help, and recovery disable delay adjustment. Buffering panels show
`Buffering...` and reject freezing with feedback until history is available.

The fist shortcut is only eligible in idle SELECT, with no contextual submenu.
Fully open the hand, then hold a fist outside the active panel for 0.8 seconds.
Progress remains visible. A hold triggers once and requires a new full-open
observation; releasing a pinch is insufficient. CREATE, MOVE, RESIZE, slider
capture, submenus, help, and recovery cancel holds and require full-open rearming.
F and the fist share one source-aware toggle per frame.

## Pointer, overlays, and help

Small thumb/index midpoint pointers are always drawn while tracking: released
pointers are hollow white, pinching pointers are filled yellow. Eligible buttons,
panels, or resize handles under a pointer highlight. Disabled targets do not
highlight. One concise instruction describes the current action. The active
panel has a stronger cyan border; compact bounded tags identify panel ID, mode,
and filter. The HUD shows the tool, active panel, temporal mode, and delay.

Landmark skeletons and per-hand debug labels are hidden by default; D toggles
these independently of `--debug-camera`, which only logs raw camera statistics.
The tracker always runs on current raw live frames, even with debug overlays off.

H opens a compact list of actual controls. H/Escape close it, Q exits, and the
Tutorial entry/U can start guidance. G can skip active guidance; C stays available
while the welcome card/tutorial is showing. Other workspace actions pause.
Live inference and bounded history
sampling continue when capture is available; existing recovery also continues.
Help discards drafts, cancels slider/fist progress, and stops edits at their last
valid geometry. Committed panels, crops, modes, filters, delay values, and stacking
are preserved. Closing help consumes that frame, returns to SELECT, and requires
both visible hands to release before gesture actions resume.

`ui.py` owns shared frame-sized layout rectangles and dark translucent drawing
helpers. Drawing and gesture targets use the same geometry. The layout targets
1280x720 and 640x480 without changing camera resolution, crop, or aspect ratio.
Below 480x360, controls/hitboxes are hidden with a concise notice; keyboard
alternatives remain available under their usual state rules. Increasing only
the OpenCV window size does not change the underlying frame size.

## Shared bounded video history

`temporal_history.py` owns one timestamped raw BGR buffer shared by all panels.
It records before inference, compositing, filters, or UI. No history is written
to disk and no per-panel copy of the video history exists. Inference always uses
the current full-resolution raw live frame, regardless of panel mode.

Samples use monotonic time and are captured at no more than 15 FPS, downscaled
to fit within 640x360 with aspect ratio preserved (subject to pixel rounding).
Smaller input is not enlarged. The buffer retains approximately three seconds,
evicting oldest samples to enforce both **48 frames** and **40 MiB of image
data** as hard limits. At the maximum stored resolution, 48 BGR uint8 frames
occupy about 31.6 MiB. The budget excludes Python overhead, live/preview frames,
temporary rendering arrays, and independent frozen crops.

For each delayed panel, the latest stored frame at or before
`now - panel.delay_seconds` is selected, with a tolerance of the input timestamps'
floating-point precision to handle subtraction at sample boundaries. If that
target predates available history,
the panel displays `Buffering...`. At a steady 15 FPS, the selected image can
be approximately one sample interval (67 ms) older than the configured target.
Slower input or processing makes these gaps larger; timing is based on elapsed
time, not a fixed frame count. Timestamps are taken when the app processes each
raw input; camera/backend latency adds to what is visible in real time.

Panel coordinates are mapped into the historical image using the live/stored
width and height ratios, rounding crop bounds outward to cover the region.
The crop is scaled to the panel size before applying its filter. Downscaling,
resampling, and the lower sample rate can reduce sharpness and smoothness;
frozen delayed content retains that reduced source quality.

C/reconnection clears history immediately, even if reopening fails. Retained
DELAYED panels buffer again after recovery. A raw frame-size change also clears
history, and exiting clears it on normal and error paths. R deletes all panels
and frozen crops; the single bounded history continues sampling while tracking
is active. `--no-tracking` never creates a history buffer.

## Camera recovery and cleanup

Windows capture tries DirectShow, then Media Foundation after releasing failed
attempts. No resolution, codec, FPS, package, or global setting is changed.
C reopens the same index in a worker; capture failure pauses with a retry
message rather than switching indices or treating darkness as failure. Exit
controls remain available during recovery. A pending native driver call cannot
be interrupted; cleanup releases its eventual camera result.

Same-size recovery preserves committed panels, frozen crops, filters, delays,
order, and active ID, returns to SELECT, closes submenus, and waits for release.
A changed frame size clears panels safely while retaining the default filter
and never reusing session IDs. Retained delayed panels buffer again after C.
`--debug-camera` logs the first five raw frames and then at most once every two
seconds; logging restarts after recovery. `--no-tracking` remains a plain camera
preview without model, panels, history, help, tools, pointers, or D overlays.
C and normal exit controls still work there.

## Validation and synthetic previews

Tests use synthetic landmarks/BGR arrays and mocked native camera/window/model
entry points. Low-level geometry tests retain the standalone geometry API;
workspace tests explicitly choose CREATE/MOVE/RESIZE and open contextual menus
when their gesture controls are needed. Tests cover ownership, priorities,
release gates, Escape rollback, UI consumption, overlay toggling, source-aware
freezing, panel stacking, irregular timestamps, budgets, recovery, and help.
Tutorial checks cover real-event progression, meaningful completed movement,
failed actions, fresh-pinch entry, skip/release gates, paused help, recovery,
preserved panels, clean raw inference/capture, and plain diagnostic mode.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q .\main.py .\panels.py .\interaction.py .\filter_toolbar.py .\delay_slider.py .\ui.py .\help_overlay.py .\tutorial.py .\freeze_control.py .\hand_tracking.py .\gestures.py .\filters.py .\temporal_history.py .\camera_recovery.py .\tests
.\.venv\Scripts\python.exe .\main.py --help
.\.venv\Scripts\python.exe .\tests\ui_preview.py
git diff --check
```

Synthetic previews use synthetic pixels only, saved into the Git-ignored
`.tmp/ui-previews/` directory at 1280x720 and 640x480, including welcome, each
tutorial step, the actual creation preview, tutorial help, and completion. They do not demonstrate
live gesture usability or performance.

## Manual walkthrough and limitations

First try U from the welcome card: create, release, drag visibly and release,
then Freeze. Try a tiny drag, hand loss, and help; none should falsely advance.
Repeat and use G while creating/moving. Committed panels must survive. Check
C, Q, and replay refusal with existing panels; after G/completion and R, the
welcome card must stay dismissed. Then continue in free play:

1. Choose G or use N from the welcome card. Choose New/N, release both hands, create with two pinches,
   then release. Confirm SELECT returns and the new panel is active.
2. Create another overlapping panel. Freshly pinch to select the topmost or an
   exposed lower region; neither should move. Choose Move/M, release, then drag
   only the active panel. Pinching another panel must not select it.
3. Choose Resize/S, release, and pinch diagonal active handles. Verify release,
   hand loss, crossing, bounds, and minimum size. Try Escape mid-move/mid-resize:
   starting geometry must return and SELECT must resume after release.
4. Use Effects/E and Time/Y; only one should be open. Try filters, T, slider,
   F/Freeze, Delete, and keyboard alternatives. Give panels different modes,
   delays, and effects. Freeze delayed content, then unfreeze back to its mode.
5. Confirm UI pinches never grab panels beneath them. Fists should work only
   after a full-open observation in idle SELECT with closed submenus. Held
   pinches must not become actions after tool switches or controller loss.
6. Toggle D and compare skeleton/debug labels with the always-visible pointers.
   Check eligible hover highlights, instructions, progress, and buffering.
7. Exercise H, C, R, Q, and Escape during edits/creation/slider capture. Help
   must gate controls; closing must require release. Recovery must preserve
   same-size panel content while delayed sources buffer again.
8. Check native 1280x720 and 640x480 layouts, small-frame keyboard access,
   `--no-tracking`, and an extended session's responsiveness/memory yourself.

Live usability and performance are intentionally left for manual assessment.
Pose heuristics may miss edge-on/occluded hands or confuse IDs during fast
crossings. Use distinct visible hands and good lighting. Frozen resizing can
stretch images. Delayed sampling reduces detail and smoothness; native camera
latency and processing gaps add to visible delay. Rendering costs grow with
panel area and effect complexity. No recording, export, templates, or session
persistence is implemented.
