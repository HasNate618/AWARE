from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from typing import Any

import numpy as np

from aware.app.perception.interface import Detection, PerceptionSnapshot

logger = logging.getLogger(__name__)

# COCO class names (index → name)
_COCO_NAMES = [
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
]

# Map COCO labels to AWARE vocabulary
_LABEL_MAP: dict[str, str] = {
    "person": "person",
    "cat": "cat",
    "dog": "dog",
    "car": "car",
    "truck": "car",
    "bus": "car",
    "motorcycle": "car",
    "bicycle": "bicycle",
    "backpack": "package",
    "handbag": "package",
    "suitcase": "package",
    "cell phone": "phone",
    "laptop": "laptop",
    "keyboard": "keyboard",
    "tv": "tv",
    "bottle": "bottle",
    "cup": "cup",
    "book": "book",
    "chair": "chair",
}


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thresh: float = 0.45) -> list[int]:
    """Simple non-maximum suppression. Returns indices of kept boxes."""
    if len(boxes) == 0:
        return []
    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter)
        inds = np.where(iou <= iou_thresh)[0]
        order = order[inds + 1]
    return keep


class YOLOCamera:
    """Real camera + YOLOv8-nano ONNX inference. Implements PerceptionSource."""

    def __init__(
        self,
        device: str = "/dev/video2",
        model_path: str = "models/yolov8n.onnx",
        confidence: float = 0.5,
        inference_interval: float = 0.5,
        resolution: tuple[int, int] = (320, 240),
    ) -> None:
        self.device = device
        self.model_path = model_path
        self.confidence = confidence
        self.inference_interval = inference_interval
        self.resolution = resolution
        self._running = False
        self._cap: Any = None
        self._session: Any = None
        self._last_frame: np.ndarray | None = None
        self._latest_frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self._frame_thread: threading.Thread | None = None
        self._last_snapshot: PerceptionSnapshot = PerceptionSnapshot(
            detections=[], sounds=[], source="yolo_unavailable", timestamp=time.time()
        )
        self._detection_log: deque[dict[str, object]] = deque(maxlen=200)

    async def start(self) -> None:
        self._running = True
        try:
            import cv2

            logger.info("Loading YOLO ONNX model: %s", self.model_path)
            import onnxruntime as ort

            self._session = ort.InferenceSession(
                self._session_path(), providers=["CPUExecutionProvider"]
            )
            logger.info("Model loaded, input: %s", self._session.get_inputs()[0].shape)

            logger.info("Opening camera: %s (%dx%d)", self.device, *self.resolution)
            self._cap = cv2.VideoCapture(self.device)
            if not self._cap.isOpened():
                logger.error("Failed to open camera %s", self.device)
                self._cap = None
                return

            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            logger.info("YOLO camera started")

            # Start dedicated frame reader thread
            self._frame_thread = threading.Thread(target=self._read_frames, daemon=True)
            self._frame_thread.start()
        except ImportError as e:
            logger.error("Missing dependency: %s — falling back to unavailable", e)
        except Exception:
            logger.exception("Failed to start YOLO camera")

    def _session_path(self) -> str:
        from pathlib import Path

        p = Path(self.model_path)
        if p.exists():
            return str(p)
        # Try relative to project root
        project_root = Path(__file__).parent.parent.parent.parent
        return str(project_root / self.model_path)

    async def stop(self) -> None:
        self._running = False
        if self._frame_thread is not None:
            self._frame_thread.join(timeout=1.0)
            self._frame_thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        logger.info("YOLO camera stopped")

    async def snapshot(self) -> PerceptionSnapshot:
        return self._last_snapshot

    def get_frame_jpeg(self) -> bytes | None:
        """Return latest frame as JPEG with YOLO bounding boxes drawn, or None."""
        if self._last_frame is None:
            return None
        try:
            import cv2

            frame = self._last_frame.copy()
            snap = self._last_snapshot
            h, w = frame.shape[:2]

            for det in snap.detections:
                x1, y1, x2, y2 = det.bbox
                # Draw box
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 136), 2)
                # Label
                label = f"{det.label} {det.confidence:.0%}"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 4, y1), (0, 255, 136), -1)
                cv2.putText(
                    frame,
                    label,
                    (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 0, 0),
                    1,
                )

            # Encode to JPEG
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            result: bytes = buf.tobytes()
            return result
        except Exception:
            logger.exception("Failed to encode frame")
            return None

    def get_detection_log(self, limit: int = 50) -> list[dict[str, object]]:
        """Return recent detections with timestamps."""
        items = list(self._detection_log)
        return items[-limit:]

    def _read_frames(self) -> None:
        """Continuously read frames from camera in dedicated thread."""
        while self._running and self._cap is not None:
            ret, frame = self._cap.read()
            if ret and frame is not None:
                with self._frame_lock:
                    self._latest_frame = frame
            else:
                time.sleep(0.01)

    async def run_inference_loop(self) -> None:
        """Background loop: capture frame, run YOLO, store snapshot."""
        cycle = 0
        while self._running:
            if self._cap is None or self._session is None:
                await asyncio.sleep(1.0)
                continue
            cycle += 1
            try:
                snapshot = await asyncio.to_thread(self._infer)
                self._last_snapshot = snapshot
                if snapshot.detections:
                    for det in snapshot.detections:
                        self._detection_log.append(
                            {
                                "label": det.label,
                                "confidence": det.confidence,
                                "bbox": det.bbox,
                                "timestamp": snapshot.timestamp,
                            }
                        )
                        logger.info("[yolo] %s %.0f%%", det.label, det.confidence * 100)
            except Exception:
                logger.exception("YOLO inference error")
            await asyncio.sleep(self.inference_interval)

    def _infer(self) -> PerceptionSnapshot:
        import cv2

        assert self._session is not None

        # Grab latest frame from reader thread
        with self._frame_lock:
            frame = self._latest_frame
        if frame is None:
            return PerceptionSnapshot(
                detections=[], sounds=[], source="yolo", timestamp=time.time()
            )

        self._last_frame = frame

        # Preprocess: resize, BGR→RGB, normalize, NCHW
        # Use OpenCL for image processing when available (Adreno GPU)
        cv2.ocl.setUseOpenCL(True)
        img = cv2.resize(frame, (320, 320))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))  # HWC → CHW
        blob = np.expand_dims(img, axis=0)  # NCHW

        # Inference
        input_name = self._session.get_inputs()[0].name
        outputs = self._session.run(None, {input_name: blob})
        # YOLOv8 output: [1, 84, 3400] → 84 = 4 (xywh) + 80 (class scores)
        pred = outputs[0][0]  # shape: (84, 3400)

        # Extract boxes and scores
        boxes_xywh = pred[:4, :].T  # (3400, 4)
        class_scores = pred[4:, :].T  # (3400, 80)

        # Get best class per detection
        max_scores = class_scores.max(axis=1)
        class_ids = class_scores.argmax(axis=1)

        # Confidence filter
        mask = max_scores >= self.confidence
        boxes_xywh = boxes_xywh[mask]
        max_scores = max_scores[mask]
        class_ids = class_ids[mask]

        if len(max_scores) == 0:
            return PerceptionSnapshot(
                detections=[], sounds=[], source="yolo", timestamp=time.time()
            )

        # Convert xywh → xyxy for NMS
        x_c, y_c, w, h = boxes_xywh[:, 0], boxes_xywh[:, 1], boxes_xywh[:, 2], boxes_xywh[:, 3]
        boxes_xyxy = np.stack([x_c - w / 2, y_c - h / 2, x_c + w / 2, y_c + h / 2], axis=1)

        # NMS
        keep = _nms(boxes_xyxy, max_scores)

        detections: list[Detection] = []
        frame_h, frame_w = frame.shape[:2]
        for i in keep:
            cls_id = int(class_ids[i])
            raw_label = _COCO_NAMES[cls_id] if cls_id < len(_COCO_NAMES) else f"cls_{cls_id}"
            label = _LABEL_MAP.get(raw_label, raw_label)
            conf = float(max_scores[i])
            x1, y1, x2, y2 = boxes_xyxy[i]
            # Scale back to original frame coords
            x1 = int(x1 * frame_w / 320)
            y1 = int(y1 * frame_h / 320)
            x2 = int(x2 * frame_w / 320)
            y2 = int(y2 * frame_h / 320)
            detections.append(
                Detection(
                    label=label,
                    confidence=round(conf, 3),
                    bbox=(x1, y1, x2, y2),
                )
            )

        return PerceptionSnapshot(
            detections=detections,
            sounds=[],
            source="yolo",
            timestamp=time.time(),
        )
