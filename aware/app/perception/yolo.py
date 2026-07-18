from __future__ import annotations

import asyncio
import logging
import time

from aware.app.perception.interface import Detection, PerceptionSnapshot

logger = logging.getLogger(__name__)

# COCO classes YOLOv8 is trained on — map to our vocabulary where possible
_LABEL_MAP: dict[str, str] = {
    "person": "person",
    "cat": "cat",
    "dog": "dog",
    "car": "car",
    "truck": "car",
    "bus": "car",
    "motorcycle": "car",
    "bicycle": "car",
    "backpack": "package",
    "handbag": "package",
    "suitcase": "package",
    "cell phone": "phone",
    "laptop": "laptop",
    "tv": "tv",
}


class YOLOCamera:
    """Real camera + YOLOv8-nano inference. Implements PerceptionSource."""

    def __init__(
        self,
        device: str = "/dev/video2",
        model_name: str = "yolov8n.pt",
        confidence: float = 0.5,
        inference_interval: float = 0.5,
        resolution: tuple[int, int] = (320, 240),
    ) -> None:
        self.device = device
        self.model_name = model_name
        self.confidence = confidence
        self.inference_interval = inference_interval
        self.resolution = resolution
        self._running = False
        self._cap: object | None = None
        self._model: object | None = None
        self._last_snapshot: PerceptionSnapshot | None = None

    async def start(self) -> None:
        self._running = True
        try:
            import cv2
            from ultralytics import YOLO

            logger.info("Loading YOLO model: %s", self.model_name)
            self._model = YOLO(self.model_name)

            logger.info("Opening camera: %s (%dx%d)", self.device, *self.resolution)
            self._cap = cv2.VideoCapture(self.device)
            if not self._cap.isOpened():
                logger.error("Failed to open camera %s", self.device)
                self._cap = None
                return

            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
            logger.info("YOLO camera started")
        except ImportError as e:
            logger.error("Missing dependency: %s — falling back to unavailable", e)
        except Exception:
            logger.exception("Failed to start YOLO camera")

    async def stop(self) -> None:
        self._running = False
        if self._cap is not None:
            try:
                import cv2

                self._cap.release()
            except Exception:
                pass
            self._cap = None
        logger.info("YOLO camera stopped")

    async def snapshot(self) -> PerceptionSnapshot:
        if self._last_snapshot is not None:
            return self._last_snapshot
        return PerceptionSnapshot(
            detections=[], sounds=[], source="yolo_unavailable", timestamp=time.time()
        )

    async def run_inference_loop(self) -> None:
        """Background loop: capture frame, run YOLO, store snapshot."""
        while self._running:
            if self._cap is None or self._model is None:
                await asyncio.sleep(1.0)
                continue
            try:
                snapshot = await asyncio.to_thread(self._infer)
                self._last_snapshot = snapshot
            except Exception:
                logger.exception("YOLO inference error")
            await asyncio.sleep(self.inference_interval)

    def _infer(self) -> PerceptionSnapshot:
        import cv2

        assert self._cap is not None
        assert self._model is not None

        ret, frame = self._cap.read()
        if not ret or frame is None:
            return PerceptionSnapshot(
                detections=[], sounds=[], source="yolo", timestamp=time.time()
            )

        results = self._model(frame, verbose=False, conf=self.confidence)
        detections: list[Detection] = []

        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                raw_label = r.names.get(cls_id, f"cls_{cls_id}")
                label = _LABEL_MAP.get(raw_label, raw_label)
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(
                    Detection(
                        label=label,
                        confidence=round(conf, 3),
                        bbox=(int(x1), int(y1), int(x2), int(y2)),
                    )
                )

        return PerceptionSnapshot(
            detections=detections,
            sounds=[],
            source="yolo",
            timestamp=time.time(),
        )
