"""All boxes are original-image [x1, y1, x2, y2), integers."""
import math


ROI_POLICY = "face_expand_left_right_0.25_top_0.75_bottom_0.10_v1"


def clip_box(box, width, height):
    if len(box) != 4 or not all(math.isfinite(float(v)) for v in box):
        raise ValueError("A box requires four finite coordinates")
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        raise ValueError("Box must have positive width and height")
    result = [max(0, min(width, int(math.floor(x1)))),
              max(0, min(height, int(math.floor(y1)))),
              max(0, min(width, int(math.ceil(x2)))),
              max(0, min(height, int(math.ceil(y2))))]
    if result[2] <= result[0] or result[3] <= result[1]:
        raise ValueError("Box lies outside the image")
    return result


def head_box(face, width, height):
    x1, y1, x2, y2 = face
    w, h = x2 - x1, y2 - y1
    return clip_box([x1 - .25*w, y1 - .75*h, x2 + .25*w, y2 + .10*h],
                    width, height)


def iou(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(
        0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union else 0.0


def suppress_boxes(boxes, threshold=.35):
    # Cascade has no calibrated scores; prefer larger boxes deterministically.
    ordered = sorted(boxes, key=lambda b: (-(b[2]-b[0])*(b[3]-b[1]), b))
    keep = []
    for box in ordered:
        if all(iou(box, other) < threshold for other in keep):
            keep.append(box)
    return keep
