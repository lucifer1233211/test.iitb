"""Short-lived cross-camera person re-identification for live streams."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, Optional

import numpy as np


class PersonReidentificationTracker:
    """Matches recent face signatures without persisting unknown-person biometrics."""

    def __init__(self, similarity_threshold: float = 0.72, memory_seconds: int = 300):
        self.similarity_threshold = similarity_threshold
        self.memory_seconds = memory_seconds
        self._profiles: Dict[str, Dict[str, Any]] = {}
        self._last_notifications: Dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def observe(self, face: Dict[str, Any], camera_name: str,
                camera_location: Optional[str], stream_id: str) -> Optional[Dict[str, Any]]:
        """Record a detection and emit only when its last sighting used another camera."""
        now = time.time()
        embedding_data = face.get("_embedding")
        person_id = face.get("person_id") if face.get("identified") else None

        if person_id:
            identity_id = f"known:{person_id}"
            confidence = float(face.get("match_confidence") or 0.0)
            label = face.get("person_name") or "Recognized person"
            embedding = None
        elif embedding_data is not None:
            embedding = np.asarray(embedding_data, dtype=np.float32)
            norm = float(np.linalg.norm(embedding))
            if norm == 0:
                return None
            embedding = embedding / norm
            identity_id, confidence = self._find_similar_unknown(embedding, now)
            label = "Unenrolled person"
        else:
            return None

        with self._lock:
            self._prune(now)
            profile = self._profiles.get(identity_id)
            previous = profile.get("last_seen") if profile else None
            if profile is None:
                profile = {"identity_id": identity_id, "label": label, "last_seen": None}
                self._profiles[identity_id] = profile

            if embedding is not None:
                profile["embedding"] = embedding
            profile["label"] = label
            profile["last_seen"] = {
                "camera_name": camera_name,
                "camera_location": camera_location,
                "stream_id": stream_id,
                "timestamp": now,
            }

            if not previous or previous["stream_id"] == stream_id:
                return None
            notification_key = (identity_id, stream_id)
            if now - self._last_notifications.get(notification_key, 0) < 60:
                return None
            self._last_notifications[notification_key] = now

            return {
                "id": str(uuid.uuid4()),
                "title": "Person Re-identified",
                "message": f"{label} matched between {previous['camera_name']} and {camera_name}.",
                "identity_id": identity_id,
                "person_id": person_id,
                "person_name": label,
                "confidence": round(confidence, 4),
                "source_camera_name": previous["camera_name"],
                "source_location": previous.get("camera_location"),
                "source_stream_id": previous["stream_id"],
                "camera_name": camera_name,
                "location": camera_location,
                "stream_id": stream_id,
            }

    def _find_similar_unknown(self, embedding: np.ndarray, now: float) -> tuple[str, float]:
        with self._lock:
            self._prune(now)
            best_identity: Optional[str] = None
            best_score = -1.0
            for identity_id, profile in self._profiles.items():
                if identity_id.startswith("known:") or "embedding" not in profile:
                    continue
                score = float(np.dot(embedding, profile["embedding"]))
                if score > best_score:
                    best_identity, best_score = identity_id, score
            if best_identity and best_score >= self.similarity_threshold:
                return best_identity, best_score
            return f"unknown:{uuid.uuid4()}", 0.0

    def _prune(self, now: float) -> None:
        cutoff = now - self.memory_seconds
        self._profiles = {
            identity_id: profile for identity_id, profile in self._profiles.items()
            if profile.get("last_seen", {}).get("timestamp", 0) >= cutoff
        }
        self._last_notifications = {
            key: timestamp for key, timestamp in self._last_notifications.items()
            if timestamp >= cutoff
        }
