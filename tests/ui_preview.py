"""Render synthetic release UI images; no camera, model, or real media needed."""

from pathlib import Path
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


def render(width, height):
    yy, xx = np.indices((height, width))
    raw = np.empty((height, width, 3), np.uint8)
    raw[:, :, 0] = 100 + xx * 90 // width
    raw[:, :, 1] = 110 + yy * 90 // height
    raw[:, :, 2] = 150 + ((xx // 48 + yy // 48) % 2) * 60
    scene = PanelCollection()
    regions = ((0.05, 0.24, 0.36, 0.60), (0.42, 0.30, 0.75, 0.66), (0.77, 0.22, 0.97, 0.50))
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
    display = raw.copy()
    scene.composite(raw, display)
    draw_workspace(display, scene, 2)
    draw_fist_feedback(display, "Fist hold: 0.4 / 0.8 s")
    toolbar = FilterToolbar()
    toolbar.draw(display, [], True, True, True, "active panel #2", True, True)
    DelaySlider().draw(display, scene, True)
    help_image = display.copy()
    help_overlay = HelpOverlay()
    help_overlay.visible = True
    help_overlay.draw(help_image)
    reconnect = raw.copy()
    draw_camera_status(reconnect, "Reconnecting camera...", "Capture paused. Q: exit | H: help")
    return {"workspace": display, "help": help_image, "reconnecting": reconnect}


if __name__ == "__main__":
    output = ROOT / ".tmp" / "ui-previews"
    output.mkdir(parents=True, exist_ok=True)
    for width, height in ((1280, 720), (640, 480)):
        for name, image in render(width, height).items():
            path = output / f"{width}x{height}-{name}.png"
            if not cv2.imwrite(str(path), image):
                raise RuntimeError(f"Could not write {path}")
            print(path)
