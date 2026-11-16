"""Shared screen geometry and OpenCV drawing, independent of camera capture."""

from dataclasses import dataclass

import cv2


BACKGROUND = (29, 25, 23)
TEXT = (242, 240, 235)
MUTED = (183, 177, 168)
ACCENT = (235, 204, 72)
FONT = cv2.FONT_HERSHEY_SIMPLEX
GAP = 8
BUTTON_HEIGHT = 36
BUTTON_WIDTH = 160
MARGIN = 12


@dataclass(frozen=True)
class Box:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self):
        return self.right - self.left

    def contains(self, point):
        return self.left <= point[0] <= self.right and self.top <= point[1] <= self.bottom


class Layout:
    """All drawing and gesture targets use these same frame-sized rectangles."""

    def __init__(self, width, height):
        self.width, self.height = width, height
        self.scale = 1.25 if width >= 1000 and height >= 600 else 1.0
        self.margin = round(MARGIN * self.scale)
        self.gap = round(GAP * self.scale)
        m, g = self.margin, self.gap
        self.header = Box(m, m, max(m, width - m - 1), min(height - 1, round(108 * self.scale)))
        self.footer = Box(m, max(0, height - m - round(32 * self.scale)), width - m - 1, height - m - 1)
        self.filters = []
        self.actions = []
        self.toolbar = None
        self.slider = None
        # Hiding targets also removes their hitboxes; keyboard shortcuts remain.
        if width < 480 or height < 360:
            return
        button_width = min(round(BUTTON_WIDTH * self.scale), (width - 2 * m - 3 * g) // 4)
        button_height = round(BUTTON_HEIGHT * self.scale)
        caption_height = round(24 * self.scale)
        bottom = self.footer.top - g
        top = bottom - (caption_height + 2 * button_height + 3 * g)
        right = m + 4 * button_width + 3 * g
        self.toolbar = Box(m, top, right, bottom)
        action_top = top + caption_height + g
        filter_top = action_top + button_height + g
        self.actions = [Box(m + i * (button_width + g), action_top,
                            m + i * (button_width + g) + button_width, action_top + button_height)
                        for i in range(3)]
        self.filters = [Box(m + i * (button_width + g), filter_top,
                            m + i * (button_width + g) + button_width, filter_top + button_height)
                        for i in range(4)]
        slider_bottom = top - g
        self.slider = Box(m, slider_bottom - round(52 * self.scale), right, slider_bottom)

    @property
    def slider_track(self):
        if self.slider is None:
            return None
        box = self.slider
        return (box.left + self.gap, box.right - self.gap, box.bottom - round(14 * self.scale))


def surface(frame, left, top, right, bottom, color=BACKGROUND, opacity=0.88):
    """Blend only the clipped UI region; never modify raw capture sources."""
    height, width = frame.shape[:2]
    left, top = max(0, left), max(0, top)
    right, bottom = min(width - 1, right), min(height - 1, bottom)
    if right < left or bottom < top:
        return
    region = frame[top:bottom + 1, left:right + 1]
    tint = region.copy()
    tint[:] = color
    cv2.addWeighted(tint, opacity, region, 1 - opacity, 0, dst=region)


def card(frame, box):
    surface(frame, box.left, box.top, box.right, box.bottom)


def text(frame, value, position, width, scale=0.45, color=TEXT):
    """Render one clean pass, clipping long labels with an ellipsis."""
    value = str(value)
    height, frame_width = frame.shape[:2]
    x, y = position
    (_, text_height), baseline = cv2.getTextSize("Ag", FONT, scale, 1)
    if height < text_height + baseline + 4:
        return
    x = max(2, min(frame_width - 2, x))
    y = max(text_height + 2, min(height - baseline - 2, y))
    width = min(width, frame_width - x - 2)
    if width <= 0:
        return
    if cv2.getTextSize(value, FONT, scale, 1)[0][0] > width:
        while value and cv2.getTextSize(value + "...", FONT, scale, 1)[0][0] > width:
            value = value[:-1]
        value = value.rstrip() + "..." if value else ""
    cv2.putText(frame, value, (x, y), FONT, scale, color, 1, cv2.LINE_AA)


def badge(frame, value, position, color=ACCENT):
    x, y = position
    height, frame_width = frame.shape[:2]
    if height < 24 or frame_width < 24:
        return Box(0, 0, 0, 0)
    width = min(frame_width - 4, cv2.getTextSize(value, FONT, 0.4, 1)[0][0] + 12)
    x = max(2, min(x, frame_width - width - 2))
    y = max(16, min(y, height - 7))
    surface(frame, x, y - 14, x + width, y + 5)
    text(frame, value, (x + 6, y), width - 12, 0.4, color)
    return Box(x, y - 14, x + width, y + 5)


def draw_camera_status(frame, message, instructions):
    layout = Layout(frame.shape[1], frame.shape[0])
    card(frame, layout.header)
    x = layout.header.left + layout.gap
    text(frame, message, (x, layout.header.top + 28), layout.header.width - 16, 0.55, ACCENT)
    text(frame, instructions, (x, layout.header.top + 54), layout.header.width - 16, 0.42)


def draw_workspace(frame, interaction, hand_count=0):
    """Panel feedback and application status, separate from interactive controls."""
    height, width = frame.shape[:2]
    layout = Layout(width, height)
    for panel in interaction.panels:
        box = panel.rectangle
        active = panel.panel_id == interaction.active_id and not interaction.creation_mode
        color = ACCENT if active else MUTED
        cv2.rectangle(frame, (round(box.left), round(box.top)), (round(box.right), round(box.bottom)),
                      color, 3 if active else 1, cv2.LINE_AA)
        badge(frame, f"#{panel.panel_id} {panel.content_mode} / {panel.filter_name}",
              (round(box.left) + 7, round(box.top) + 15), color)
    rectangle = interaction.rectangle
    if rectangle is not None:
        color = (0, 255, 255) if interaction.state in ("CREATING", "RESIZING") else ACCENT
        if interaction.creation_mode:
            cv2.rectangle(frame, (round(rectangle.left), round(rectangle.top)),
                          (round(rectangle.right), round(rectangle.bottom)), color, 2, cv2.LINE_AA)
        elif interaction.state in ("PLACED", "DRAGGING", "RESIZING"):
            for point in rectangle.corner_points().values():
                cv2.circle(frame, (round(point[0]), round(point[1])), 4, color, -1, cv2.LINE_AA)
    if height < 220 or width < 300:
        surface(frame, 0, 0, width - 1, min(height - 1, 62))
        text(frame, "Controls hidden: frame too small.", (8, 20), width - 16, 0.3)
        if height >= 48:
            text(frame, "Keyboard: H help / Q exit", (8, 42), width - 16, 0.3, MUTED)
        return
    card(frame, layout.header)
    x = layout.header.left + layout.gap
    top, scale = layout.header.top, layout.scale
    line_width = layout.header.width - 2 * layout.gap
    title = "REALITY LOOM" if width >= 480 else "REALITY LOOM / H: help"
    text(frame, title, (x, top + round(21 * scale)), line_width, 0.52 * scale, ACCENT)
    if width >= 480:
        text(frame, f"Hands: {hand_count}   H: help", (max(x, layout.header.right - round(155 * scale)),
             top + round(21 * scale)), round(150 * scale), 0.4 * scale, MUTED)
    state = "ADJUSTING DELAY" if interaction.adjusting_delay else interaction.state.replace("_", " ")
    # Keep status wording stable while temporal mode stays on its own line.
    status = interaction.status_text if not interaction.adjusting_delay else f"Panels: {len(interaction.panels)}/4 | {state}"
    text(frame, status, (x, top + round(42 * scale)), line_width, 0.44 * scale)
    panel = interaction.active_panel
    content = (f"Content: {interaction.content_mode}   |   Delay: {panel.delay_seconds:.1f} s   |   {panel.filter_name}"
               if panel is not None and not interaction.creation_mode else "New panel: two pinches to create")
    text(frame, content, (x, top + round(62 * scale)), line_width, 0.44 * scale, ACCENT)
    text(frame, interaction.instructions, (x, top + round(82 * scale)), line_width, 0.4 * scale, MUTED)
    if layout.toolbar is None:
        box = Box(layout.margin, layout.header.bottom + 8, width - layout.margin - 1,
                  min(height - 1, layout.header.bottom + 58))
        card(frame, box)
        text(frame, "Controls hidden: frame too small.", (box.left + 8, box.top + 18), box.width - 16, 0.38)
        text(frame, "Use keyboard shortcuts. H: help", (box.left + 8, box.top + 37), box.width - 16, 0.38, MUTED)


def draw_fist_feedback(frame, message):
    if frame.shape[0] < 220 or frame.shape[1] < 300:
        return
    layout = Layout(frame.shape[1], frame.shape[0])
    box = layout.footer
    card(frame, box)
    text(frame, message, (box.left + 8, box.top + round(21 * layout.scale)), box.width - 16,
         0.42 * layout.scale, ACCENT if message.startswith("Fist hold:") else MUTED)


def draw_buffering(frame, rectangle):
    x, y = round(rectangle.left) + 8, round(rectangle.top) + 40
    text(frame, "Buffering...", (x, min(y, round(rectangle.bottom) - 6)),
         max(0, round(rectangle.width) - 16), 0.45, TEXT)
