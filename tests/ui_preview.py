"""Render synthetic release UI images; no camera, model, or real media needed."""

from pathlib import Path
from types import SimpleNamespace
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from delay_slider import DelaySlider
from filter_toolbar import FilterToolbar
from help_overlay import HelpOverlay
from interaction import Rectangle
from panels import Panel, PanelCollection
from ui import draw_camera_status, draw_fist_feedback, draw_workspace
from ui import Layout
from tutorial import Tutorial


def render_tutorial(width, height):
    """Drive the same actions as the app; guides are not simulated hand tracking."""
    raw = np.full((height, width, 3), (150, 180, 190), np.uint8)
    cv2.line(raw, (0, height // 2), (width - 1, height // 2), (165, 195, 205), 2)
    scene = PanelCollection()
    tutorial = Tutorial(scene)
    toolbar = FilterToolbar()
    output = {}
    first, second = Layout(width, height).tutorial_corners

    def hands(pinching=False, a=first, b=second):
        return [SimpleNamespace(track_id=index + 1, pinch_point=point, is_pinching=pinching)
                for index, point in enumerate((a, b))]

    def tick(poses):
        tutorial.ensure_tool(scene)
        scene.update(poses, width, height)
        tutorial.observe(scene, (width, height), now=1)

    def snapshot(name):
        display = raw.copy()
        scene.composite(raw, display)
        draw_workspace(display, scene, instruction=tutorial.instruction_override(scene))
        if not tutorial.showing_card:
            toolbar.draw(display, [], scene.toolbar_enabled, interaction=scene)
        tutorial.draw(display, scene)
        output[name] = display

    snapshot("welcome")
    tutorial.start(scene)
    for _ in range(4):
        tick(hands())
    snapshot("tutorial-create")
    tick(hands(True))
    snapshot("tutorial-create-preview")
    tick(hands())
    for _ in range(4):
        tick(hands())
    snapshot("tutorial-move")
    center = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
    other = (width * 0.9, height * 0.3)
    tick(hands(False, center, other))
    tick(hands(True, center, other))
    moved = (center[0] + width * 0.12, center[1])
    for _ in range(6):
        tick(hands(True, moved, other))
    tick(hands(False, moved, other))
    for _ in range(4):
        tick(hands())
    snapshot("tutorial-freeze")
    help_image = output["tutorial-freeze"].copy()
    help_overlay = HelpOverlay()
    help_overlay.visible = True
    help_overlay.draw(help_image, tutorial_active=True)
    output["tutorial-help"] = help_image
    scene.toggle_frozen(raw)
    tutorial.observe(scene, (width, height), now=1)
    snapshot("tutorial-complete")
    return output


def render(width, height):
    yy, xx = np.indices((height, width))
    raw = np.empty((height, width, 3), np.uint8)
    raw[:, :, 0] = 100 + xx * 90 // width
    raw[:, :, 1] = 110 + yy * 90 // height
    raw[:, :, 2] = 150 + ((xx // 48 + yy // 48) % 2) * 60
    scene = PanelCollection()
    regions = ((0.05, 0.24, 0.36, 0.60), (0.42, 0.30, 0.75, 0.58), (0.77, 0.22, 0.97, 0.50))
    for panel_id, (left, top, right, bottom) in enumerate(regions, 1):
        box = Rectangle(round(left * width), round(top * height), round(right * width), round(bottom * height))
        panel = Panel(panel_id, box)
        if panel_id == 1:
            panel.filter_name = "GRAYSCALE"
        elif panel_id == 2:
            panel.source_mode = "DELAYED"
            panel.delay_seconds = 1.5
        else:
            panel.frozen_image = raw[round(box.top):round(box.bottom), round(box.left):round(box.right)].copy()
            panel.filter_name = "PIXELATE"
        scene.panels.append(panel)
    scene.active_id = 2
    scene.creation_mode = False
    scene._load_active()
    scene.record_frame(raw, 0)
    toolbar = FilterToolbar()
    hands = [SimpleNamespace(pinch_point=(width * 0.15, height * 0.4), is_pinching=False),
             SimpleNamespace(pinch_point=(width * 0.83, height * 0.63), is_pinching=True)]

    def workspace():
        display = raw.copy()
        scene.composite(raw, display)
        targets = toolbar.visible_buttons(width, height, scene)
        draw_workspace(display, scene, 2, hands, True, targets)
        if scene.fist_enabled:
            draw_fist_feedback(display, "Fist hold: 0.4 / 0.8 s")
        toolbar.draw(display, hands, True, interaction=scene)
        DelaySlider().draw(display, scene, scene.can_adjust_delay)
        toolbar.draw_pointers(display, hands)
        return display

    display = workspace()
    scene.submenu = "EFFECTS"
    effects = workspace()
    scene.submenu = "TIME"
    time_image = workspace()
    scene.submenu = None
    scene.tool = "RESIZE"
    resize = workspace()
    scene.tool = "SELECT"
    help_image = display.copy()
    help_overlay = HelpOverlay()
    help_overlay.visible = True
    help_overlay.draw(help_image)
    reconnect = raw.copy()
    draw_camera_status(reconnect, "Reconnecting camera...", "Capture paused. Q: exit | H: help")
    return {"workspace": display, "effects": effects, "time": time_image, "resize": resize,
            "help": help_image, "reconnecting": reconnect}


if __name__ == "__main__":
    output = ROOT / ".tmp" / "ui-previews"
    output.mkdir(parents=True, exist_ok=True)
    for width, height in ((1280, 720), (640, 480)):
        previews = render(width, height)
        previews.update(render_tutorial(width, height))
        for name, image in previews.items():
            path = output / f"{width}x{height}-{name}.png"
            if not cv2.imwrite(str(path), image):
                raise RuntimeError(f"Could not write {path}")
            print(path)
