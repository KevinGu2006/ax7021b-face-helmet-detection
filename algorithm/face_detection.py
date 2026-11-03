"""Independent Haar face detector. Boxes use original-image [x1,y1,x2,y2)."""
from pathlib import Path
import cv2
import numpy as np
from face_geometry import clip_box, suppress_boxes


class FaceDetector:
    backend = "opencv_haar"

    def __init__(self, cascade_path=None, max_detection_side=640, min_face=24,
                 use_profile=False, scale_factor=1.1, min_neighbors=5):
        if max_detection_side < 64 or min_face < 12:
            raise ValueError("Invalid detector dimensions")
        if not np.isfinite(scale_factor) or scale_factor <= 1 or min_neighbors < 0:
            raise ValueError("Invalid Haar parameters")
        self.max_detection_side = int(max_detection_side)
        self.min_face = int(min_face)
        self.scale_factor = float(scale_factor)
        self.min_neighbors = int(min_neighbors)
        default = Path(__file__).resolve().parent / "models/haarcascade_frontalface_default.xml"
        if cascade_path is None:
            cascade_path = default if default.exists() else (
                Path(cv2.data.haarcascades) / default.name if hasattr(cv2, "data") else default)
        self.frontal = cv2.CascadeClassifier(str(cascade_path))
        if self.frontal.empty():
            raise ValueError("Cannot load face cascade: {}".format(cascade_path))
        self.profile = None
        if use_profile:
            path = Path(cascade_path).with_name("haarcascade_profileface.xml")
            self.profile = cv2.CascadeClassifier(str(path))
            if self.profile.empty():
                raise ValueError("Cannot load profile cascade: {}".format(path))

    @staticmethod
    def validate_frame(frame):
        if not isinstance(frame, np.ndarray) or frame.dtype != np.uint8:
            raise TypeError("frame_bgr must be a numpy uint8 array")
        if frame.ndim != 3 or frame.shape[2] != 3 or min(frame.shape[:2]) < 2:
            raise ValueError("frame_bgr must have nonempty HxWx3 BGR shape")

    @staticmethod
    def validate_gray(gray):
        if not isinstance(gray, np.ndarray) or gray.dtype != np.uint8:
            raise TypeError("gray_image must be a numpy uint8 array")
        if gray.ndim != 2 or min(gray.shape) < 2:
            raise ValueError("gray_image must have nonempty HxW shape")

    def detection_size(self, height, width):
        scale = min(1., float(self.max_detection_side) / max(width, height))
        return max(1, round(width * scale)), max(1, round(height * scale))

    def prepare_bgr_for_pl(self, frame_bgr):
        """Resize BGR before PL, preserving the legacy operation ordering."""
        self.validate_frame(frame_bgr)
        height, width = frame_bgr.shape[:2]
        dw, dh = self.detection_size(height, width)
        small = cv2.resize(frame_bgr, (dw, dh), interpolation=cv2.INTER_LINEAR) if (
            dw, dh) != (width, height) else frame_bgr
        return np.ascontiguousarray(small)

    def detect_faces(self, frame_bgr):
        small = self.prepare_bgr_for_pl(frame_bgr)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        return self.detect_faces_gray(gray, original_shape=frame_bgr.shape[:2])

    def prepare_gray(self, gray_image, original_shape=None):
        """Return equalized detector pixels and original H,W; never modifies input."""
        self.validate_gray(gray_image)
        if original_shape is None:
            height, width = gray_image.shape
            dw, dh = self.detection_size(height, width)
            small = cv2.resize(gray_image, (dw, dh), interpolation=cv2.INTER_LINEAR) if (
                dw, dh) != (width, height) else gray_image
        else:
            if len(original_shape) != 2 or any(
                    isinstance(x, bool) or not isinstance(x, (int, np.integer)) or x < 2
                    for x in original_shape):
                raise ValueError("original_shape must be integer (height,width), both >=2")
            height, width = map(int, original_shape)
            dw, dh = self.detection_size(height, width)
            if gray_image.shape != (dh, dw):
                raise ValueError("PL gray dimensions do not match resized BGR; do not resize twice")
            small = gray_image
        return cv2.equalizeHist(np.ascontiguousarray(small)), (height, width)

    def haar_on_equalized(self, gray, original_shape):
        """Haar + coordinate mapping + NMS. No resize, conversion or equalization."""
        height, width = original_shape
        dh, dw = gray.shape
        sx, sy = width / dw, height / dh
        minimum = max(12, round(self.min_face / max(sx, sy)))
        args = dict(scaleFactor=self.scale_factor, minNeighbors=self.min_neighbors,
                    minSize=(minimum, minimum))
        boxes = []
        for x, y, w, h in self.frontal.detectMultiScale(gray, **args):
            boxes.append(clip_box([x*sx, y*sy, (x+w)*sx, (y+h)*sy], width, height))
        if self.profile is not None:
            for mirrored in (False, True):
                image = cv2.flip(gray, 1) if mirrored else gray
                for x, y, w, h in self.profile.detectMultiScale(image, **args):
                    if mirrored:
                        x = dw-x-w
                    boxes.append(clip_box([x*sx, y*sy, (x+w)*sx, (y+h)*sy], width, height))
        return suppress_boxes(boxes)

    def detect_faces_gray(self, gray_image, original_shape=None):
        equalized, shape = self.prepare_gray(gray_image, original_shape)
        return self.haar_on_equalized(equalized, shape)


_default = None


def _detector():
    global _default
    if _default is None:
        _default = FaceDetector()
    return _default


def detect_faces(frame_bgr):
    return _detector().detect_faces(frame_bgr)


def detect_faces_gray(gray_image, original_shape=None):
    return _detector().detect_faces_gray(gray_image, original_shape)
