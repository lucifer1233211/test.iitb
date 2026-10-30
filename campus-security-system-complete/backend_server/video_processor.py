import cv2
import time
import threading
import queue
import numpy as np
import os
from pathlib import Path
from typing import Optional, Dict, Any, Generator
from datetime import datetime, timezone
from reidentification import PersonReidentificationTracker

UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"


class VideoProcessor:
    def __init__(self):
        self.active_streams: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self.reidentification_tracker = PersonReidentificationTracker()

    # ─────────────────────────────────────────────────────────────────────────
    # Video file processing
    # ─────────────────────────────────────────────────────────────────────────

    def process_video_file(
        self,
        file_path: str,
        face_service,
        frame_interval: int = 5,
        callback=None,
    ) -> Dict[str, Any]:
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            return {"error": f"Cannot open video file: {file_path}"}

        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = total_frames / fps if fps > 0 else 0

        detections = []
        frames_processed = 0
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % frame_interval == 0:
                frames_processed += 1
                _, buf = cv2.imencode('.jpg', frame)
                image_bytes = buf.tobytes()

                result = face_service.identify_face(image_bytes)
                if result.get("detected_faces"):
                    for face in result["detected_faces"]:
                        detections.append({
                            "frame_number": frame_idx,
                            "timestamp_sec": round(frame_idx / fps, 2),
                            "bbox": face["bbox"],
                            "confidence": face["confidence"],
                            "quality_score": face.get("quality_score", 0),
                            "person_name": face.get("person_name"),
                            "person_id": face.get("person_id"),
                            "match_confidence": face.get("match_confidence"),
                            "identified": face.get("identified", False),
                        })

                if callback:
                    callback(frame_idx, total_frames, len(detections))

            frame_idx += 1

        cap.release()

        unique_persons = {
            d["person_name"]
            for d in detections
            if d.get("person_name") and d["person_name"] != "Unknown"
        }

        return {
            "video_info": {
                "width": width,
                "height": height,
                "fps": round(fps, 2),
                "total_frames": total_frames,
                "duration_sec": round(duration, 2),
            },
            "processing_info": {
                "frames_processed": frames_processed,
                "frame_interval": frame_interval,
                "total_detections": len(detections),
                "unique_persons": list(unique_persons),
            },
            "detections": detections,
        }

    def generate_annotated_frames(
        self,
        file_path: str,
        face_service,
        frame_interval: int = 3,
        target_fps: float = 10,
    ) -> Generator[bytes, None, None]:
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            return

        frame_delay = 1.0 / target_fps
        frame_idx = 0
        last_faces = []

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % frame_interval == 0:
                    _, buf = cv2.imencode('.jpg', frame)
                    result = face_service.identify_face(buf.tobytes())
                    last_faces = result.get("detected_faces", [])

                annotated = self._draw_annotations(frame, last_faces)
                _, jpeg = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 75])
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n'
                    + jpeg.tobytes()
                    + b'\r\n'
                )

                frame_idx += 1
                time.sleep(frame_delay)
        except GeneratorExit:
            pass  # client disconnected cleanly
        finally:
            cap.release()

    # ─────────────────────────────────────────────────────────────────────────
    # RTSP stream management
    # ─────────────────────────────────────────────────────────────────────────

    def start_rtsp_stream(
        self,
        stream_id: str,
        rtsp_url: str,
        face_service,
        frame_interval: int = 15,
        db_session_factory=None,
        alert_creator=None,
        detection_creator=None,
        camera_db_id: Optional[int] = None,
        camera_name: Optional[str] = None,
        camera_location: Optional[str] = None,
        reidentification_enabled: bool = True,
        rfdetr_service=None,
        detection_mode: str = "both",
        rfdetr_alert_creator=None,
        # Optional callback: called with (event_type, payload_dict) for SSE notifications
        notify_callback=None,
    ) -> Dict[str, Any]:
        with self._lock:
            if len(self.active_streams) >= 20:
                return {"error": "Maximum camera limit reached"}

            if stream_id in self.active_streams:
                return {"stream_id": stream_id, "status": "already_active"}

            for sid, stream in self.active_streams.items():
                if stream.get("rtsp_url") == rtsp_url:
                    return {
                        "status": "already_active",
                        "stream_id": sid,
                        "message": "RTSP URL already running",
                    }

            frame_queue: queue.Queue = queue.Queue(maxsize=2)
            stop_event = threading.Event()

            stream_info: Dict[str, Any] = {
                "stream_id": stream_id,
                "rtsp_url": rtsp_url,
                "cap": None,
                "frame_queue": frame_queue,
                "stop_event": stop_event,
                "thread": None,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "frames_read": 0,
                "detections_count": 0,
                "object_detections_count": 0,
                "detection_mode": detection_mode,
                "last_jpeg": None,
                "last_faces": [],
                "last_objects": [],
                # Use a threading.Lock-protected flag instead of a bare bool to
                # prevent the race between the capture loop and face-analysis thread.
                "_face_lock": threading.Lock(),
                "_face_running": False,
                "_object_lock": threading.Lock(),
                "_object_running": False,
                "camera_db_id": camera_db_id,
                "camera_name": camera_name or stream_id,
                "camera_location": camera_location,
                # Track active generator count so we only stop capture when last consumer leaves
                "_generator_count": 0,
            }
            self.active_streams[stream_id] = stream_info

        def capture_loop():
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"

            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            if not cap.isOpened():
                print(f"[VideoProcessor] Cannot connect to RTSP stream: {rtsp_url}")
                with self._lock:
                    self.active_streams.pop(stream_id, None)
                stop_event.set()
                return

            with self._lock:
                if stream_id in self.active_streams:
                    self.active_streams[stream_id]["cap"] = cap

            fidx = 0
            reconnect_count = 0
            max_reconnects = 10

            try:
                while not stop_event.is_set():
                    ret, frame = cap.read()

                    if not ret or frame is None:
                        reconnect_count += 1
                        print(
                            f"[VideoProcessor] Stream {stream_id}: "
                            f"reconnect attempt {reconnect_count}/{max_reconnects}"
                        )

                        if reconnect_count > max_reconnects:
                            print(
                                f"[VideoProcessor] Stream {stream_id}: "
                                f"max reconnects reached, stopping cleanly"
                            )
                            break

                        try:
                            cap.release()
                        except Exception:
                            pass

                        time.sleep(2)

                        if stop_event.is_set():
                            return

                        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
                            "rtsp_transport;tcp|stimeout;5000000"
                        )
                        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                        with self._lock:
                            if stream_id in self.active_streams:
                                self.active_streams[stream_id]["cap"] = cap
                        continue

                    # Ensure frame is a valid contiguous BGR uint8 array
                    if (
                        frame is None
                        or not isinstance(frame, np.ndarray)
                        or frame.ndim != 3
                        or frame.shape[2] != 3
                        or frame.dtype != np.uint8
                    ):
                        print(f"[VideoProcessor] Stream {stream_id}: invalid frame format, skipping")
                        continue

                    if not frame.flags["C_CONTIGUOUS"]:
                        frame = np.ascontiguousarray(frame)

                    reconnect_count = 0
                    stream_info["frames_read"] += 1
                    current_mode = stream_info.get("detection_mode", "both")

                    # ── Face analysis in a daemon thread ──────────────────────
                    if (
                        fidx % frame_interval == 0
                        and face_service.models_loaded
                        and current_mode in ("face", "both")
                    ):
                        # Use a lock to prevent spawning duplicate face threads
                        face_lock: threading.Lock = stream_info["_face_lock"]
                        with face_lock:
                            already_running = stream_info["_face_running"]
                            if not already_running:
                                stream_info["_face_running"] = True

                        if not already_running:
                            def run_face_analysis(f_frame, _stream_info=stream_info):
                                db = None
                                try:
                                    ok, buf = cv2.imencode(".jpg", f_frame)
                                    if not ok:
                                        return

                                    result = face_service.identify_face(
                                        buf.tobytes(), include_embeddings=reidentification_enabled
                                    )
                                    faces = result.get("detected_faces", [])

                                    if reidentification_enabled:
                                        for face in faces:
                                            event = self.reidentification_tracker.observe(
                                                face=face,
                                                camera_name=camera_name or stream_id,
                                                camera_location=camera_location,
                                                stream_id=stream_id,
                                            )
                                            if event and notify_callback is not None:
                                                notify_callback("person_reidentified", event)
                                            # Never expose raw biometric vectors through snapshots.
                                            face.pop("_embedding", None)

                                    _stream_info["last_faces"] = faces
                                    _stream_info["detections_count"] += len(faces)

                                    if not faces:
                                        return

                                    if db_session_factory is None:
                                        return

                                    db = db_session_factory()
                                    for face in faces:
                                        identified  = face.get("identified", False)
                                        person_name = face.get("person_name") or "Unknown"
                                        person_id   = face.get("person_id")
                                        confidence  = float(
                                            face.get("match_confidence")
                                            or face.get("confidence")
                                            or 0.0
                                        )
                                        bbox = face.get("bbox")

                                        if detection_creator is not None:
                                            try:
                                                detection_creator(
                                                    db=db,
                                                    person_name=person_name,
                                                    person_id=person_id,
                                                    camera_id=camera_db_id,
                                                    camera_name=camera_name or stream_id,
                                                    location=camera_location,
                                                    confidence=confidence,
                                                    bounding_box=bbox,
                                                    identified=identified,
                                                    detection_type="face",
                                                )
                                            except Exception as e:
                                                print(
                                                    f"[Detection Persist Error] "
                                                    f"stream={stream_id}: {e}"
                                                )

                                        alert_type = "face_recognized" if identified else "unknown_person"
                                        severity   = "low"            if identified else "high"

                                        if alert_creator is None:
                                            continue

                                        alert = alert_creator(
                                            db=db,
                                            alert_type=alert_type,
                                            severity=severity,
                                            person_name=person_name,
                                            person_id=person_id,
                                            camera_id=camera_db_id,
                                            camera_name=camera_name or stream_id,
                                            location=camera_location,
                                            confidence=confidence,
                                        )

                                        if alert:
                                            print(
                                                f"[ALERT] {alert_type} | "
                                                f"{person_name} | "
                                                f"conf={confidence:.2f}"
                                            )
                                except Exception as e:
                                    print(f"[Face Analysis Error] stream={stream_id}: {e}")
                                finally:
                                    if db is not None:
                                        try:
                                            db.close()
                                        except Exception:
                                            pass
                                    with _stream_info["_face_lock"]:
                                        _stream_info["_face_running"] = False

                            threading.Thread(
                                target=run_face_analysis,
                                args=(frame.copy(),),
                                daemon=True,
                            ).start()

                    # ── RFDETR object detection in a daemon thread ────────────
                    if (
                        fidx % frame_interval == 0
                        and rfdetr_service is not None
                        and rfdetr_service.models_loaded
                        and current_mode in ("object", "both")
                    ):
                        object_lock: threading.Lock = stream_info["_object_lock"]
                        with object_lock:
                            already_running = stream_info["_object_running"]
                            if not already_running:
                                stream_info["_object_running"] = True

                        if not already_running:
                            def run_object_detection(f_frame, _stream_info=stream_info):
                                try:
                                    detections = rfdetr_service.detect(f_frame, camera_name=camera_name or stream_id)
                                    _stream_info["last_objects"] = detections
                                    _stream_info["object_detections_count"] += len(detections)

                                    if not detections:
                                        return

                                    if db_session_factory is None or detection_creator is None:
                                        return

                                    db = db_session_factory()
                                    for det in detections:
                                        bbox = det.get("bbox")
                                        confidence = det.get("confidence", 0.0)
                                        label = det.get("label", "object")

                                        detection_creator(
                                            db=db,
                                            person_name=label,
                                            person_id=None,
                                            camera_id=camera_db_id,
                                            camera_name=camera_name or stream_id,
                                            location=camera_location,
                                            confidence=confidence,
                                            bounding_box=bbox,
                                            identified=False,
                                            detection_type="object",
                                            detection_source="rfdetr",
                                        )

                                    # Create alerts and notifications for rfdetr detections
                                    if rfdetr_alert_creator is not None:
                                        for det in detections:
                                            label = det.get("label", "object")
                                            confidence = det.get("confidence", 0.0)
                                            bbox = det.get("bbox")
                                            try:
                                                rfdetr_alert_creator(
                                                    db=db,
                                                    alert_type="object_detected",
                                                    severity="high" if confidence > 0.7 else "medium",
                                                    object_label=label,
                                                    camera_id=camera_db_id,
                                                    camera_name=camera_name or stream_id,
                                                    location=camera_location,
                                                    confidence=confidence,
                                                )
                                            except Exception as e:
                                                print(f"[RFDETR Alert Error] stream={stream_id}: {e}")

                                    # Publish SSE notification for rfdetr detections
                                    if notify_callback is not None:
                                        try:
                                            notify_callback("rfdetr_detection", {
                                                "stream_id": stream_id,
                                                "camera_name": camera_name or stream_id,
                                                "location": camera_location,
                                                "detections": [
                                                    {
                                                        "label": det.get("label", "object"),
                                                        "confidence": det.get("confidence", 0.0),
                                                        "bbox": det.get("bbox"),
                                                    }
                                                    for det in detections
                                                ],
                                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                            })
                                        except Exception as e:
                                            print(f"[RFDETR Notify Error] stream={stream_id}: {e}")

                                    db.commit()
                                except Exception as e:
                                    print(f"[Object Detection Error] stream={stream_id}: {e}")
                                finally:
                                    with _stream_info["_object_lock"]:
                                        _stream_info["_object_running"] = False
                                    try:
                                        db.close()
                                    except Exception:
                                        pass

                            threading.Thread(
                                target=run_object_detection,
                                args=(frame.copy(),),
                                daemon=True,
                            ).start()

                    # ── Annotate & push to frame queue ────────────────────────
                    annotated = self._draw_annotations(
                        frame,
                        stream_info["last_faces"],
                        stream_info["last_objects"],
                    )
                    _, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    jpeg_bytes = jpeg.tobytes()

                    with self._lock:
                        if stream_id in self.active_streams:
                            self.active_streams[stream_id]["last_jpeg"] = jpeg_bytes

                    # Drop oldest frame if queue is full to stay real-time
                    if frame_queue.full():
                        try:
                            frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                    try:
                        frame_queue.put_nowait(jpeg_bytes)
                    except queue.Full:
                        pass

                    fidx += 1
                    time.sleep(0.01)

            except Exception as e:
                print(f"[VideoProcessor] Stream {stream_id} capture loop error: {e}")
            finally:
                try:
                    cap.release()
                except Exception:
                    pass
                # Signal stop so any waiting generators wake up and exit cleanly
                stop_event.set()
                with self._lock:
                    self.active_streams.pop(stream_id, None)
                print(f"[VideoProcessor] Stream {stream_id} capture loop exited cleanly")

        t = threading.Thread(target=capture_loop, daemon=True)
        stream_info["thread"] = t
        t.start()

        return {"stream_id": stream_id, "status": "started"}

    # ─────────────────────────────────────────────────────────────────────────
    # Frame generator for StreamingResponse
    # ─────────────────────────────────────────────────────────────────────────

    def get_rtsp_frame_generator(self, stream_id: str) -> Optional[Generator[bytes, None, None]]:
        with self._lock:
            stream = self.active_streams.get(stream_id)
            if stream:
                stream["_generator_count"] += 1

        if not stream:
            return None

        def generate():
            fq: queue.Queue      = stream["frame_queue"]
            stop: threading.Event = stream["stop_event"]

            # Send an initial blank boundary so the browser img element
            # connects immediately rather than timing out on first frame.
            try:
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n\r\n'
            except GeneratorExit:
                _dec_generator_count()
                return

            try:
                while not stop.is_set():
                    try:
                        jpeg_bytes = fq.get(timeout=2)
                        yield (
                            b'--frame\r\n'
                            b'Content-Type: image/jpeg\r\n\r\n'
                            + jpeg_bytes
                            + b'\r\n'
                        )
                    except queue.Empty:
                        # Stream is stopped — send an end-of-stream sentinel
                        # so the browser img sees a clean MJPEG close, not a
                        # connection drop (which caused the React crash).
                        if stop.is_set():
                            break
                        # No frames yet but capture is still running — keep waiting
                        continue
            except GeneratorExit:
                # Client closed tab / navigated away — clean close, not an error
                pass
            except Exception as e:
                print(f"[VideoProcessor] Generator for stream {stream_id} error: {e}")
            finally:
                _dec_generator_count()
                print(f"[VideoProcessor] Generator for stream {stream_id} closed")

        def _dec_generator_count():
            """
            Decrement consumer count. Only set stop when there are no more
            consumers AND the capture thread itself already stopped.  This
            prevents one viewer's disconnect from killing the stream for others.
            """
            with self._lock:
                if stream_id in self.active_streams:
                    self.active_streams[stream_id]["_generator_count"] = max(
                        0, self.active_streams[stream_id]["_generator_count"] - 1
                    )
                else:
                    # Capture loop already cleaned up — nothing more to do
                    pass

        return generate()

    # ─────────────────────────────────────────────────────────────────────────
    # Snapshot
    # ─────────────────────────────────────────────────────────────────────────

    def get_rtsp_snapshot(self, stream_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            stream = self.active_streams.get(stream_id)
        if not stream:
            return None

        jpeg_bytes = stream.get("last_jpeg")
        if not jpeg_bytes:
            return None

        import base64
        return {
            "image": base64.b64encode(jpeg_bytes).decode(),
            "faces": stream["last_faces"],
            "objects": stream["last_objects"],
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Stop
    # ─────────────────────────────────────────────────────────────────────────

    def stop_rtsp_stream(self, stream_id: str) -> Dict[str, Any]:
        with self._lock:
            stream = self.active_streams.pop(stream_id, None)
        if not stream:
            return {"error": "Stream not found"}

        # Signal the capture thread to stop
        stream["stop_event"].set()

        # Release the OpenCV capture so it doesn't block on a dead RTSP socket
        try:
            if stream.get("cap") is not None:
                stream["cap"].release()
        except Exception:
            pass

        # Drain the queue so blocked put_nowait unblocks immediately
        fq: queue.Queue = stream["frame_queue"]
        while not fq.empty():
            try:
                fq.get_nowait()
            except queue.Empty:
                break

        # Wait briefly — caller offloads this via run_in_executor so it won't
        # block the event loop. Use a shorter timeout since we already signaled.
        if stream.get("thread"):
            stream["thread"].join(timeout=5)

        return {
            "stream_id": stream_id,
            "status": "stopped",
            "frames_read": stream["frames_read"],
            "detections_count": stream["detections_count"],
        }

    def set_stream_mode(self, stream_id: str, mode: str) -> Dict[str, Any]:
        with self._lock:
            stream = self.active_streams.get(stream_id)
        if not stream:
            return {"error": "Stream not found"}

        if mode not in ("face", "object", "both"):
            return {"error": "Invalid mode. Use 'face', 'object', or 'both'."}

        stream["detection_mode"] = mode

        if mode == "face":
            stream["last_objects"] = []
        elif mode == "object":
            stream["last_faces"] = []

        return {"stream_id": stream_id, "detection_mode": mode}

    def list_active_streams(self) -> list:
        with self._lock:
            return [
                {
                    "stream_id": sid,
                    "rtsp_url": s["rtsp_url"],
                    "started_at": s["started_at"],
                    "frames_read": s["frames_read"],
                    "detections_count": s["detections_count"],
                    "object_detections_count": s["object_detections_count"],
                    "detection_mode": s.get("detection_mode", "both"),
                    "active_faces": len(s["last_faces"]),
                    "active_objects": len(s["last_objects"]),
                }
                for sid, s in self.active_streams.items()
            ]

    # ─────────────────────────────────────────────────────────────────────────
    # Frame annotation
    # ─────────────────────────────────────────────────────────────────────────

    def _draw_annotations(
        self,
        frame: np.ndarray,
        faces: list,
        objects: list = None,
    ) -> np.ndarray:
        if objects is None:
            objects = []
        annotated = frame.copy()

        for face in faces:
            bbox = face.get("bbox", {})
            x = bbox.get("x", 0)
            y = bbox.get("y", 0)
            w = bbox.get("width", 0)
            h = bbox.get("height", 0)

            person_name = face.get("person_name")
            identified  = face.get("identified", False)
            confidence  = face.get("confidence", 0)
            match_conf  = face.get("match_confidence")

            color = (0, 200, 0) if (identified or person_name) else (0, 0, 220)
            cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)

            label_parts = []
            if person_name:
                label_parts.append(person_name)
            elif not identified:
                label_parts.append("Unknown")
            if match_conf is not None:
                label_parts.append(f"{match_conf * 100:.0f}%")
            elif confidence:
                label_parts.append(f"{confidence * 100:.0f}%")

            label = " | ".join(label_parts) if label_parts else "Face"

            font       = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            thickness  = 1
            (tw, th), _ = cv2.getTextSize(label, font, font_scale, thickness)

            label_y = max(y - 8, th + 4)
            cv2.rectangle(annotated, (x, label_y - th - 4), (x + tw + 4, label_y + 4), color, -1)
            cv2.putText(annotated, label, (x + 2, label_y), font, font_scale, (255, 255, 255), thickness)

        for obj in objects:
            bbox = obj.get("bbox", {})
            x = bbox.get("x", 0)
            y = bbox.get("y", 0)
            w = bbox.get("width", 0)
            h = bbox.get("height", 0)
            label = obj.get("label", "object")
            confidence = obj.get("confidence", 0.0)

            color = (255, 165, 0)
            cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)

            label_text = f"{label} {confidence * 100:.0f}%"
            font       = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            thickness  = 1
            (tw, th), _ = cv2.getTextSize(label_text, font, font_scale, thickness)

            label_y = max(y - 8, th + 4)
            cv2.rectangle(annotated, (x, label_y - th - 4), (x + tw + 4, label_y + 4), color, -1)
            cv2.putText(annotated, label_text, (x + 2, label_y), font, font_scale, (255, 255, 255), thickness)

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(
            annotated, ts,
            (10, annotated.shape[0] - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
        )
        cv2.putText(
            annotated, f"IITB Security | Faces: {len(faces)} | Objects: {len(objects)}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1,
        )
        return annotated


# ─────────────────────────────────────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────────────────────────────────────

_video_processor: Optional[VideoProcessor] = None


def get_video_processor() -> VideoProcessor:
    global _video_processor
    if _video_processor is None:
        _video_processor = VideoProcessor()
    return _video_processor
