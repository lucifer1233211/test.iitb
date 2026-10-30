import os
import threading
import time
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from collections import defaultdict

from rfdetr import RFDETRMedium

MODELS_DIR = Path(__file__).parent / "models"
MODELS_DIR.mkdir(exist_ok=True)

DEFAULT_CONF = 0.5


class RFDETRAnalytics:
    """Thread-safe analytics tracker for RF-DETR detections."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total_detections = 0
        self.total_frames_processed = 0
        self.detections_by_label: Dict[str, int] = defaultdict(int)
        self.confidence_by_label: Dict[str, List[float]] = defaultdict(list)
        self.detections_by_camera: Dict[str, int] = defaultdict(int)
        self.detections_per_frame: List[int] = []
        self.avg_confidence_by_label: Dict[str, float] = {}
        self.last_detection_time: Optional[str] = None
        self._start_time = time.time()

    def record(self, label: str, confidence: float, camera_name: str = "") -> None:
        with self._lock:
            self.total_detections += 1
            self.detections_by_label[label] += 1
            self.confidence_by_label[label].append(confidence)
            if camera_name:
                self.detections_by_camera[camera_name] += 1
            self.last_detection_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._recompute_averages()

    def record_frame(self, num_detections: int) -> None:
        with self._lock:
            self.total_frames_processed += 1
            self.detections_per_frame.append(num_detections)

    def _recompute_averages(self) -> None:
        for label, confs in self.confidence_by_label.items():
            if confs:
                self.avg_confidence_by_label[label] = round(sum(confs) / len(confs), 4)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            uptime_seconds = time.time() - self._start_time
            return {
                "total_detections": self.total_detections,
                "total_frames_processed": self.total_frames_processed,
                "detections_by_label": dict(self.detections_by_label),
                "avg_confidence_by_label": dict(self.avg_confidence_by_label),
                "detections_by_camera": dict(self.detections_by_camera),
                "last_detection_time": self.last_detection_time,
                "uptime_seconds": round(uptime_seconds, 1),
            }

    def reset(self) -> None:
        with self._lock:
            self.total_detections = 0
            self.total_frames_processed = 0
            self.detections_by_label.clear()
            self.confidence_by_label.clear()
            self.detections_by_camera.clear()
            self.detections_per_frame.clear()
            self.avg_confidence_by_label.clear()
            self.last_detection_time = None


class RFDETRService:
    def __init__(self, model_path: Optional[str] = None, notify_callback: Optional[Callable[[str, dict], None]] = None):
        self.model = None
        self.models_loaded = False
        self._lock = threading.Lock()
        self.analytics = RFDETRAnalytics()
        self.notify_callback = notify_callback

        try:
            if model_path and Path(model_path).exists():
                self.model = RFDETRMedium.from_checkpoint(model_path)
            else:
                self.model = RFDETRMedium()
            self.models_loaded = True
            print(f"[RFDETRService] model loaded")
        except Exception as e:
            print(f"[RFDETRService] load failed: {e}")

    def detect(
        self,
        frame: np.ndarray,
        conf_threshold: float = DEFAULT_CONF,
        camera_name: str = "",
    ) -> List[Dict[str, Any]]:
        if not self.models_loaded or self.model is None:
            return []

        if frame is None or not isinstance(frame, np.ndarray):
            return []

        if frame.ndim != 3 or frame.shape[2] not in (3, 4):
            return []

        if frame.size == 0:
            return []

        rgb = frame
        if frame.shape[2] == 4:
            rgb = frame[:, :, :3]
        elif frame.shape[2] == 3:
            rgb = frame[:, :, ::-1].copy()

        try:
            with self._lock:
                detections = self.model.predict(rgb, threshold=conf_threshold)
        except Exception as e:
            print(f"[RFDETRService] inference error: {e}")
            return []

        results: List[Dict[str, Any]] = []
        try:
            xyxy = detections.xyxy
            confidence = detections.confidence
            class_ids = detections.class_id
            class_names = detections.data.get("class_name", [])
        except Exception as e:
            print(f"[RFDETRService] parse error: {e}")
            return []

        if xyxy is None or len(xyxy) == 0:
            return []

        for i in range(len(xyxy)):
            try:
                x1, y1, x2, y2 = xyxy[i]
                conf = float(confidence[i]) if confidence is not None else 0.0
                cls_id = int(class_ids[i]) if class_ids is not None else -1
                label = str(class_names[i]) if class_names is not None and i < len(class_names) else str(cls_id)
            except Exception:
                continue

            results.append({
                "label": label,
                "confidence": conf,
                "bbox": {
                    "x": int(x1),
                    "y": int(y1),
                    "width": int(x2 - x1),
                    "height": int(y2 - y1),
                },
            })

        # Record analytics
        self.analytics.record_frame(len(results))
        for det in results:
            self.analytics.record(det["label"], det["confidence"], camera_name)

        # Publish notification if callback is set and detections found
        if results and self.notify_callback is not None and camera_name:
            try:
                self.notify_callback("rfdetr_detection", {
                    "camera_name": camera_name,
                    "detections": results,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })
            except Exception as e:
                print(f"[RFDETRService] notify error: {e}")

        return results

    def warmup(self, width: int = 640, height: int = 640):
        if not self.models_loaded or self.model is None:
            return
        try:
            dummy = np.zeros((height, width, 3), dtype=np.uint8)
            dummy[:, :] = [255, 255, 255]
            with self._lock:
                self.model.predict(dummy, threshold=0.5)
            print("[RFDETRService] warmup complete")
        except Exception as e:
            print(f"[RFDETRService] warmup failed: {e}")

    def get_analytics(self) -> Dict[str, Any]:
        return self.analytics.get_stats()

    def reset_analytics(self) -> None:
        self.analytics.reset()


_rfdetr_service: Optional[RFDETRService] = None


def get_rfdetr_service() -> RFDETRService:
    global _rfdetr_service
    if _rfdetr_service is None:
        _rfdetr_service = RFDETRService()
    return _rfdetr_service
