"""Small OpenCV UI primitives with bounded text and consistent contrast."""

import cv2


BACKGROUND = (29, 25, 23)
TEXT = (242, 240, 235)
MUTED = (183, 177, 168)
ACCENT = (235, 204, 72)
FONT = cv2.FONT_HERSHEY_SIMPLEX


def surface(frame, left, top, right, bottom):
    cv2.rectangle(frame, (left, top), (right, bottom), BACKGROUND, -1)


def text(frame, value, position, width, scale=0.45, color=TEXT):
    """Render one clean pass, clipping long labels with an ellipsis."""
    value = str(value)
    if width <= 0:
        return
    if cv2.getTextSize(value, FONT, scale, 1)[0][0] > width:
        while value and cv2.getTextSize(value + "...", FONT, scale, 1)[0][0] > width:
            value = value[:-1]
        value = value.rstrip() + "..." if value else ""
    cv2.putText(frame, value, position, FONT, scale, color, 1, cv2.LINE_AA)


def badge(frame, value, position, color=ACCENT):
    x, y = position
    width = cv2.getTextSize(value, FONT, 0.4, 1)[0][0] + 12
    surface(frame, x, y - 14, x + width, y + 5)
    text(frame, value, (x + 6, y), width - 12, 0.4, color)
