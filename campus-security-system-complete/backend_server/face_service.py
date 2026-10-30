import os
import uuid
import time
import json
import numpy as np
import cv2
from pathlib import Path
from typing import List, Dict, Any, Optional
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceDetector, FaceDetectorOptions,
)

MODELS_DIR = Path(__file__).parent / "models"
UPLOADS_DIR = Path(__file__).parent / "uploads"
EMBEDDINGS_DIR = MODELS_DIR / "embeddings"

MODELS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)
EMBEDDINGS_DIR.mkdir(exist_ok=True)

FACE_DETECTOR_MODEL = str(MODELS_DIR / "blaze_face_short_range.tflite")
ARCFACE_MODEL = str(MODELS_DIR / "arcface_r100_int8.onnx")

ARCFACE_INPUT_SIZE = (112, 112)
ARCFACE_EMBEDDING_DIM = 512

ARCFACE_VERIFY_THRESHOLD = 0.4
ARCFACE_IDENTIFY_THRESHOLD = 0.35
ARCFACE_SEARCH_THRESHOLD = 0.25


class FaceRecognitionService:
    def __init__(self):
        self.detector = None          # MediaPipe (legacy fallback)
        self.yunet_detector = None    # YuNet — primary detector
        self.arcface_session = None   # ArcFace (legacy)
        self.arcface_input_name = None
        self.sface_recognizer = None  # SFace — primary recognizer
        self.models_loaded = False
        self.arcface_loaded = False
        self.sface_loaded = False
        self.yunet_loaded = False
        self.enrolled_faces: Dict[str, Dict[str, Any]] = {}

        # ── YuNet detector (primary) ──────────────────────────────────────────
        yunet_model = str(MODELS_DIR / "face_detection_yunet_2023mar.onnx")
        try:
            if os.path.exists(yunet_model):
                self.yunet_detector = cv2.FaceDetectorYN.create(
                    yunet_model, "", (320, 320),
                    score_threshold=0.6,
                    nms_threshold=0.3,
                    top_k=5000,
                    backend_id=cv2.dnn.DNN_BACKEND_OPENCV,
                    target_id=cv2.dnn.DNN_TARGET_CPU,
                )
                self.yunet_loaded = True
                self.models_loaded = True
                print(f"[FaceService] YuNet detector loaded: {yunet_model}")
            else:
                print(f"[FaceService] YuNet model not found at {yunet_model}")
        except Exception as e:
            print(f"[FaceService] YuNet load failed: {e}")

        # ── MediaPipe BlazeFace (fallback detector) ───────────────────────────
        if not self.yunet_loaded:
            try:
                detector_options = FaceDetectorOptions(
                    base_options=BaseOptions(model_asset_path=FACE_DETECTOR_MODEL),
                    min_detection_confidence=0.3,
                )
                self.detector = FaceDetector.create_from_options(detector_options)
                self.models_loaded = True
                print("[FaceService] MediaPipe BlazeFace loaded (YuNet fallback)")
            except Exception as e:
                print(f"[FaceService] MediaPipe load failed: {e}")
                self.models_loaded = False

        # ── Haar cascade (last-resort fallback) ──────────────────────────────
        self.haar_cascade = None
        try:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self.haar_cascade = cv2.CascadeClassifier(cascade_path)
            if self.haar_cascade.empty():
                self.haar_cascade = None
            else:
                print("[FaceService] Haar cascade loaded (last-resort fallback)")
        except Exception as e:
            print(f"[FaceService] Haar cascade load failed: {e}")

        # ── SFace recognizer (primary) ────────────────────────────────────────
        sface_model = str(MODELS_DIR / "face_recognition_sface_2021dec.onnx")
        try:
            if os.path.exists(sface_model):
                self.sface_recognizer = cv2.FaceRecognizerSF.create(sface_model, "")
                self.sface_loaded = True
                print(f"[FaceService] SFace recognizer loaded: {sface_model}")
            else:
                print(f"[FaceService] SFace model not found at {sface_model}")
        except Exception as e:
            print(f"[FaceService] SFace load failed: {e}")

        # ── ArcFace (fallback recognizer) ─────────────────────────────────────
        if not self.sface_loaded:
            try:
                import onnxruntime as ort
                sess_options = ort.SessionOptions()
                sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                sess_options.intra_op_num_threads = 2
                self.arcface_session = ort.InferenceSession(ARCFACE_MODEL, sess_options)
                self.arcface_input_name = self.arcface_session.get_inputs()[0].name
                self.arcface_loaded = True
                print(f"[FaceService] ArcFace loaded (SFace fallback, {ARCFACE_EMBEDDING_DIM}-dim)")
            except Exception as e:
                print(f"[FaceService] ArcFace load failed: {e}")

        print(f"[FaceService] Active detector: {'YuNet' if self.yunet_loaded else 'BlazeFace/Haar'}")
        print(f"[FaceService] Active recognizer: {'SFace' if self.sface_loaded else 'ArcFace/Fallback'}")

        self._load_enrolled_faces()

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _load_enrolled_faces(self):
        if EMBEDDINGS_DIR.exists():
            for f in EMBEDDINGS_DIR.glob("*.json"):
                try:
                    with open(f) as fh:
                        data = json.load(fh)
                        self.enrolled_faces[data["person_id"]] = data
                except Exception:
                    pass

    def _to_mp_image(self, img_bgr: np.ndarray) -> mp.Image:
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        return mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)

    def _align_face(self, face_img: np.ndarray) -> np.ndarray:
        h, w = face_img.shape[:2]
        if h == 0 or w == 0:
            return face_img

        target_h, target_w = ARCFACE_INPUT_SIZE
        scale = min(target_w / w, target_h / h)
        new_w, new_h = int(w * scale), int(h * scale)
        resized = cv2.resize(face_img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
        y_off = (target_h - new_h) // 2
        x_off = (target_w - new_w) // 2
        canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized
        return canvas

    def _compute_face_embedding(self, face_img: np.ndarray) -> Optional[np.ndarray]:
        if face_img.size == 0:
            return None

        if not self.arcface_loaded:
            return self._compute_fallback_embedding(face_img)

        aligned = self._align_face(face_img)
        img_rgb = cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB)

        blob = img_rgb.astype(np.float32)
        blob = (blob - 127.5) / 127.5
        blob = blob.transpose(2, 0, 1)
        blob = np.expand_dims(blob, axis=0)

        try:
            output = self.arcface_session.run(None, {self.arcface_input_name: blob})
            embedding = output[0][0]
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            return embedding.astype(np.float32)
        except Exception as e:
            print(f"ArcFace inference error: {e}")
            self._arcface_error_count = getattr(self, '_arcface_error_count', 0) + 1
            if self._arcface_error_count >= 3:
                print("ArcFace failed 3+ times — disabling and switching to fallback")
                self.arcface_loaded = False
            return None

    def _compute_fallback_embedding(self, face_img: np.ndarray) -> Optional[np.ndarray]:
        if face_img.size == 0:
            return None

        face_resized = cv2.resize(face_img, (112, 112))
        gray = cv2.cvtColor(face_resized, cv2.COLOR_BGR2GRAY)

        embedding = []

        lbp = np.zeros_like(gray, dtype=np.float32)
        for dy, dx in [(-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1)]:
            shifted = np.roll(np.roll(gray, dy, axis=0), dx, axis=1)
            lbp += (shifted >= gray).astype(np.float32)
        lbp_hist = cv2.calcHist([lbp.astype(np.uint8)], [0], None, [64], [0, 9]).flatten()
        lbp_hist = lbp_hist / (lbp_hist.sum() + 1e-7)
        embedding.extend(lbp_hist.tolist())

        gray_resized = cv2.resize(gray, (16, 16))
        dct_features = cv2.dct(gray_resized.astype(np.float32)).flatten()[:128]
        dct_features = dct_features / (np.linalg.norm(dct_features) + 1e-7)
        embedding.extend(dct_features.tolist())

        hog = cv2.HOGDescriptor((64, 64), (16, 16), (8, 8), (8, 8), 9)
        gray_hog = cv2.resize(gray, (64, 64))
        hog_features = hog.compute(gray_hog).flatten()[:128]
        hog_features = hog_features / (np.linalg.norm(hog_features) + 1e-7)
        embedding.extend(hog_features.tolist())

        hist_b = cv2.calcHist([face_resized], [0], None, [32], [0, 256]).flatten()
        hist_g = cv2.calcHist([face_resized], [1], None, [32], [0, 256]).flatten()
        hist_r = cv2.calcHist([face_resized], [2], None, [32], [0, 256]).flatten()
        for h in [hist_b, hist_g, hist_r]:
            h_norm = h / (h.sum() + 1e-7)
            embedding.extend(h_norm.tolist())

        embedding = np.array(embedding[:512], dtype=np.float32)
        if len(embedding) < 512:
            embedding = np.pad(embedding, (0, 512 - len(embedding)))
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding

    def _compute_quality_score(self, face_img: np.ndarray) -> float:
        if face_img.size == 0:
            return 0.0
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        sharpness = min(float(laplacian_var) / 500.0, 1.0)
        brightness = float(gray.mean()) / 255.0
        brightness_score = 1.0 - abs(brightness - 0.5) * 2
        h, w = face_img.shape[:2]
        size_score = min(min(h, w) / 100.0, 1.0)
        return round(sharpness * 0.4 + brightness_score * 0.3 + size_score * 0.3, 4)

    def _current_backend_tag(self) -> str:
        """
        FIX: was always returning ArcFace/Fallback — now correctly reflects
        whichever recognizer is actually active (SFace takes priority).
        """
        if self.sface_loaded:
            return "SFace-YuNet"
        if self.arcface_loaded:
            return "ArcFace-R100"
        return "Fallback-Handcrafted"

    def _find_match(self, embedding: np.ndarray, threshold: float = None) -> Optional[Dict]:
        if threshold is None:
            threshold = ARCFACE_IDENTIFY_THRESHOLD if self.arcface_loaded else 0.6

        current_backend = self._current_backend_tag()
        best_match = None
        best_similarity = 0.0
        for person_id, data in self.enrolled_faces.items():
            stored_backend = data.get("embedding_backend", "Fallback-Handcrafted")
            if stored_backend != current_backend:
                continue
            for stored_emb in data.get("embeddings", []):
                # FIX: support both plain-list and {"embedding": [...]} dict format
                raw = stored_emb["embedding"] if isinstance(stored_emb, dict) else stored_emb
                stored = np.array(raw, dtype=np.float32)
                similarity = float(np.dot(embedding, stored))
                if similarity > threshold and similarity > best_similarity:
                    best_similarity = similarity
                    best_match = {
                        "person_id": person_id,
                        "person_name": data.get("person_name", "Unknown"),
                        "similarity": round(similarity, 4),
                    }
        return best_match

    def _yunet_detect(self, img: np.ndarray):
        """Run YuNet on image, returns list of face dicts with bbox + landmarks."""
        h, w = img.shape[:2]

        # YuNet input size must be divisible by 32
        fw = w - (w % 32) or 32
        fh = h - (h % 32) or 32
        self.yunet_detector.setInputSize((fw, fh))

        resized = cv2.resize(img, (fw, fh)) if (fw != w or fh != h) else img
        scale_x = w / fw
        scale_y = h / fh

        _, faces = self.yunet_detector.detect(resized)
        if faces is None:
            return []

        results = []
        for face in faces:
            if not all(np.isfinite(face[i]) for i in range(4)):
                continue
            x = int(face[0] * scale_x)
            y = int(face[1] * scale_y)
            fw_ = int(face[2] * scale_x)
            fh_ = int(face[3] * scale_y)
            # Clamp to image bounds
            x = max(0, min(x, w - 1))
            y = max(0, min(y, h - 1))
            fw_ = max(1, min(fw_, w - x))
            fh_ = max(1, min(fh_, h - y))
            confidence = float(face[14])
            landmarks = face[4:14].reshape(5, 2)
            landmarks[:, 0] *= scale_x
            landmarks[:, 1] *= scale_y

            face_crop = img[y:y + fh_, x:x + fw_]
            if face_crop.size == 0:
                continue

            results.append({
                "bbox": {"x": x, "y": y, "width": fw_, "height": fh_},
                "confidence": round(confidence, 4),
                "face_img": face_crop,
                "landmarks": landmarks,
                "yunet_raw": face,
                "yunet_input_size": (fw, fh),
                "yunet_scale": (scale_x, scale_y),
            })
        return results

    def _sface_embed(self, img_bgr: np.ndarray, yunet_face_row, input_size) -> Optional[np.ndarray]:
        """Use SFace to align + embed. yunet_face_row is the raw face row from YuNet."""
        try:
            fw, fh = input_size
            img_resized = cv2.resize(img_bgr, (fw, fh)) if img_bgr.shape[:2] != (fh, fw) else img_bgr
            aligned = self.sface_recognizer.alignCrop(img_resized, yunet_face_row)
            embedding = self.sface_recognizer.feature(aligned)
            embedding = embedding.flatten().astype(np.float32)
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            return embedding
        except Exception as e:
            print(f"[FaceService] SFace embed error: {e}")
            return None

    def _extract_faces_from_image(self, img: np.ndarray):
        h, w = img.shape[:2]
        print(f"[FaceService] _extract_faces_from_image: input={w}x{h}, "
              f"yunet={'OK' if self.yunet_loaded else 'NO'}, "
              f"blazeface={'OK' if self.detector else 'NO'}")

        # ── Primary: YuNet ────────────────────────────────────────────────────
        if self.yunet_loaded and self.yunet_detector is not None:
            faces = self._yunet_detect(img)
            print(f"[FaceService] YuNet found {len(faces)} face(s)")

            if len(faces) == 0 and w <= 1920:
                print("[FaceService] YuNet found 0 at native res — retrying at 2x upscale")
                img2x = cv2.resize(img, (w * 2, h * 2))
                faces2x = self._yunet_detect(img2x)
                for f in faces2x:
                    b = f["bbox"]
                    f["bbox"] = {
                        "x": b["x"] // 2, "y": b["y"] // 2,
                        "width": b["width"] // 2, "height": b["height"] // 2,
                    }
                    f["face_img"] = img[
                        max(0, f["bbox"]["y"]):min(h, f["bbox"]["y"] + f["bbox"]["height"]),
                        max(0, f["bbox"]["x"]):min(w, f["bbox"]["x"] + f["bbox"]["width"]),
                    ]
                    if f.get("landmarks") is not None:
                        f["landmarks"] = f["landmarks"] / 2
                faces = faces2x
                print(f"[FaceService] YuNet 2x found {len(faces)} face(s)")

            return faces

        # ── Fallback: BlazeFace tiled ─────────────────────────────────────────
        if self.detector is not None:
            all_faces = []
            seen = []
            TARGET = 640
            tiles = []
            full_scale = TARGET / w
            tiles.append((cv2.resize(img, (TARGET, int(h * full_scale))), 0, 0, full_scale))
            for row in range(2):
                for col in range(2):
                    tx, ty = col * (w // 2), row * (h // 2)
                    tw = w - tx if col == 1 else w // 2
                    th = h - ty if row == 1 else h // 2
                    tile_scale = TARGET / tw
                    tiles.append((
                        cv2.resize(img[ty:ty + th, tx:tx + tw], (TARGET, int(th * tile_scale))),
                        tx, ty, tile_scale
                    ))
            print(f"[FaceService] BlazeFace running on {len(tiles)} tiles")
            for tile_img, ox, oy, scale in tiles:
                mp_img = self._to_mp_image(tile_img)
                try:
                    result = self.detector.detect(mp_img)
                except Exception:
                    continue
                for det in result.detections:
                    bb = det.bounding_box
                    x = int(bb.origin_x / scale) + ox
                    y = int(bb.origin_y / scale) + oy
                    fw_ = int(bb.width / scale)
                    fh_ = int(bb.height / scale)
                    if fw_ < 20 or fh_ < 20:
                        continue
                    if any(abs(x - px) < 50 and abs(y - py) < 50 for px, py in seen):
                        continue
                    seen.append((x, y))
                    conf = det.categories[0].score if det.categories else 0.5
                    crop = img[max(0, y):min(h, y + fh_), max(0, x):min(w, x + fw_)]
                    all_faces.append({
                        "bbox": {"x": x, "y": y, "width": fw_, "height": fh_},
                        "confidence": round(float(conf), 4),
                        "face_img": crop,
                    })
            print(f"[FaceService] BlazeFace total: {len(all_faces)} face(s)")
            return all_faces

        # ── Last resort: Haar ─────────────────────────────────────────────────
        if self.haar_cascade is not None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            dets = self.haar_cascade.detectMultiScale(gray, 1.1, 8, minSize=(40, 40))
            faces = []
            for (x, y, fw_, fh_) in (dets if len(dets) > 0 else []):
                crop = img[max(0, y):min(h, y + fh_), max(0, x):min(w, x + fw_)]
                if np.std(crop.astype(np.float32)) < 18:
                    continue
                faces.append({
                    "bbox": {"x": int(x), "y": int(y), "width": int(fw_), "height": int(fh_)},
                    "confidence": 0.65,
                    "face_img": crop,
                })
            print(f"[FaceService] Haar found {len(faces)} face(s)")
            return faces

        print("[FaceService] No detector available")
        return []

    def _identify_faces_with_results(self, faces: list, img: np.ndarray, threshold: float,
                                     include_embeddings: bool = False) -> list:
        """Given detected faces, compute embeddings and match against enrolled."""
        detected_faces = []
        h, w = img.shape[:2]

        for face in faces:
            bb = face["bbox"]
            face_img = face.get("face_img")
            if face_img is None or face_img.size == 0:
                continue

            # ── Compute embedding (SFace preferred) ───────────────────────────
            embedding = None
            if self.sface_loaded and face.get("yunet_raw") is not None:
                input_size = face.get("yunet_input_size", (w - w % 32, h - h % 32))
                embedding = self._sface_embed(img, face["yunet_raw"], input_size)
                if embedding is not None:
                    print(f"[FaceService] SFace embedding OK for face at {bb}")

            if embedding is None:
                embedding = self._compute_face_embedding(face_img)

            if embedding is None:
                continue

            # ── Match against enrolled ────────────────────────────────────────
            best_name = None
            best_pid = None
            best_score = -1.0
            for pid, pdata in self.enrolled_faces.items():
                for emb_data in pdata.get("embeddings", []):
                    # Support both old format (plain list) and new format (dict with "embedding" key)
                    raw = emb_data["embedding"] if isinstance(emb_data, dict) else emb_data
                    stored = np.array(raw, dtype=np.float32)
                    if stored.shape != embedding.shape:
                        continue
                    score = float(np.dot(embedding, stored))
                    if score > best_score:
                        best_score = score
                        best_name = pdata.get("person_name")
                        best_pid = pid

            identified = best_score >= threshold
            print(f"[FaceService] Face at {bb}: best_match={best_name} score={best_score:.3f} "
                  f"threshold={threshold} identified={identified}")

            result = {
                "bbox": bb,
                "confidence": face.get("confidence", 0.5),
                "identified": identified,
                "person_name": best_name if identified else None,
                "person_id": best_pid if identified else None,
                "match_confidence": round(best_score, 4),
            }
            if include_embeddings:
                # Used only by the in-memory live-stream re-identification worker.
                result["_embedding"] = embedding.tolist()
            detected_faces.append(result)

        return detected_faces

    def _identify_faces_placeholder(self, detected_faces: list, img_shape: tuple,
                                    processing_time: float) -> Dict[str, Any]:
        """Build the standard API response dict."""
        h, w = img_shape[:2]
        return {
            "detected_faces": detected_faces,
            "processing_time": round(processing_time * 1000, 2),
            "image_size": {"width": w, "height": h},
            "face_count": len(detected_faces),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def detect_faces(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        FIX: this method was missing entirely — main.py calls svc.detect_faces()
        at the /api/v1/face/detect endpoint. Returns detected faces without
        performing recognition/identification.
        """
        start_time = time.time()
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {"detected_faces": [], "processing_time": 0, "error": "Invalid image"}

        faces = self._extract_faces_from_image(img)
        h, w = img.shape[:2]

        detected = []
        for face in faces:
            face_img = face.get("face_img")
            quality = self._compute_quality_score(face_img) if face_img is not None and face_img.size > 0 else 0.0
            detected.append({
                "bbox": face["bbox"],
                "confidence": face.get("confidence", 0.5),
                "quality_score": quality,
            })

        processing_time = round((time.time() - start_time) * 1000, 2)
        return {
            "detected_faces": detected,
            "face_count": len(detected),
            "image_size": {"width": w, "height": h},
            "processing_time": processing_time,
        }

    def enroll_face(self, person_name: str, image_bytes_list: List[bytes],
                    person_id: Optional[str] = None, department: Optional[str] = None,
                    employee_id: Optional[str] = None) -> Dict[str, Any]:
        start_time = time.time()
        import re
        pid = person_id or str(uuid.uuid4())
        if not re.match(r'^[a-zA-Z0-9_-]+$', pid):
            return {"error": "Invalid person_id format"}

        embeddings = []
        quality_scores = []
        saved_images = []

        for i, image_bytes in enumerate(image_bytes_list):
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                continue

            faces = self._extract_faces_from_image(img)
            if not faces:
                continue

            face = faces[0]
            face_img = face.get("face_img")
            if face_img is not None and face_img.size > 0:
                h_img, w_img = img.shape[:2]
                embedding = None
                if self.sface_loaded and face.get("yunet_raw") is not None:
                    input_size = face.get("yunet_input_size", (w_img - w_img % 32, h_img - h_img % 32))
                    embedding = self._sface_embed(img, face["yunet_raw"], input_size)
                    print(f"[FaceService] Enroll SFace: {'OK' if embedding is not None else 'FAILED'}")
                if embedding is None:
                    embedding = self._compute_face_embedding(face_img)
                if embedding is not None:
                    embeddings.append({"embedding": embedding.tolist(), "source": "sface" if self.sface_loaded else "arcface"})
                    quality_scores.append(self._compute_quality_score(face_img))
                    img_filename = f"{pid}_{i}.jpg"
                    img_path = UPLOADS_DIR / img_filename
                    cv2.imwrite(str(img_path), face_img)
                    saved_images.append(img_filename)

        if not embeddings:
            return {"error": "No faces detected in provided images"}

        now = time.time()
        embedding_backend = self._current_backend_tag()
        enrollment_data = {
            "person_id": pid,
            "person_name": person_name,
            "department": department,
            "employee_id": employee_id,
            "embeddings": embeddings,
            "quality_scores": quality_scores,
            "enrollment_images": saved_images,
            "enrollment_source": "api",
            "embedding_backend": embedding_backend,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }

        self.enrolled_faces[pid] = enrollment_data
        emb_path = EMBEDDINGS_DIR / f"{pid}.json"
        with open(emb_path, "w") as f:
            json.dump(enrollment_data, f)

        processing_time = round((time.time() - start_time) * 1000, 2)
        return {
            "id": pid,
            "person_id": pid,
            "person_name": person_name,
            "department": department,
            "employee_id": employee_id,
            "face_embedding_count": len(embeddings),
            "enrollment_images": saved_images,
            "created_at": now,
            "updated_at": now,
            "is_active": True,
            "quality_scores": quality_scores,
            "enrollment_source": "api",
            "embedding_backend": embedding_backend,
            "processing_time": processing_time,
            "faces_enrolled": len(embeddings),
        }

    def identify_face(self, image_bytes: bytes, threshold: float = None,
                      include_embeddings: bool = False) -> Dict[str, Any]:
        start_time = time.time()
        if threshold is None:
            # FIX: use SFace threshold when SFace is active
            if self.sface_loaded:
                threshold = ARCFACE_IDENTIFY_THRESHOLD
            elif self.arcface_loaded:
                threshold = ARCFACE_IDENTIFY_THRESHOLD
            else:
                threshold = 0.6

        print(f"[FaceService] identify_face called, image_bytes={len(image_bytes)}B, "
              f"models_loaded={self.models_loaded}, detector={'OK' if self.detector or self.yunet_loaded else 'NONE'}, "
              f"enrolled={len(self.enrolled_faces)} persons, threshold={threshold}")

        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            print("[FaceService] identify_face: cv2.imdecode returned None — invalid image bytes")
            return {"detected_faces": [], "processing_time": 0, "error": "Invalid image"}

        print(f"[FaceService] image decoded: {img.shape[1]}x{img.shape[0]}")
        faces = self._extract_faces_from_image(img)
        print(f"[FaceService] _extract_faces_from_image returned {len(faces)} faces")

        detected_faces = self._identify_faces_with_results(
            faces, img, threshold, include_embeddings=include_embeddings
        )

        processing_time = round((time.time() - start_time) * 1000, 2)
        return {"detected_faces": detected_faces, "processing_time": processing_time}

    def verify_face(self, image_bytes: bytes, person_id: str,
                    threshold: float = None) -> Dict[str, Any]:
        start_time = time.time()
        if threshold is None:
            threshold = ARCFACE_VERIFY_THRESHOLD if (self.arcface_loaded or self.sface_loaded) else 0.6

        if person_id not in self.enrolled_faces:
            return {
                "is_match": False, "confidence": 0, "similarity_score": 0,
                "quality_score": 0, "is_spoofing_detected": False,
                "processing_time": 0, "error": "Person not enrolled",
            }

        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {"is_match": False, "error": "Invalid image", "processing_time": 0}

        faces = self._extract_faces_from_image(img)
        if not faces:
            processing_time = round((time.time() - start_time) * 1000, 2)
            return {
                "is_match": False, "confidence": 0, "similarity_score": 0,
                "quality_score": 0, "is_spoofing_detected": False,
                "processing_time": processing_time, "error": "No face detected",
            }

        face = faces[0]
        face_img = face["face_img"]
        quality_score = self._compute_quality_score(face_img) if face_img.size > 0 else 0

        # FIX: use SFace embedding when available, same as identify_face
        h_img, w_img = img.shape[:2]
        embedding = None
        if self.sface_loaded and face.get("yunet_raw") is not None:
            input_size = face.get("yunet_input_size", (w_img - w_img % 32, h_img - h_img % 32))
            embedding = self._sface_embed(img, face["yunet_raw"], input_size)
        if embedding is None:
            embedding = self._compute_face_embedding(face_img) if face_img.size > 0 else None

        best_similarity = 0.0
        current_backend = self._current_backend_tag()
        stored_backend = self.enrolled_faces[person_id].get("embedding_backend", "Fallback-Handcrafted")

        if embedding is not None and stored_backend == current_backend:
            for emb_data in self.enrolled_faces[person_id].get("embeddings", []):
                # FIX: support both plain-list and dict embedding formats
                raw = emb_data["embedding"] if isinstance(emb_data, dict) else emb_data
                stored = np.array(raw, dtype=np.float32)
                if stored.shape != embedding.shape:
                    continue
                similarity = float(np.dot(embedding, stored))
                best_similarity = max(best_similarity, similarity)

        processing_time = round((time.time() - start_time) * 1000, 2)
        return {
            "is_match": best_similarity >= threshold,
            "confidence": face["confidence"],
            "similarity_score": round(best_similarity, 4),
            "quality_score": round(quality_score, 4),
            "is_spoofing_detected": False,
            "processing_time": processing_time,
        }

    def search_similar(self, image_bytes: bytes, threshold: float = None,
                       limit: int = 10) -> Dict[str, Any]:
        start_time = time.time()
        if threshold is None:
            threshold = ARCFACE_SEARCH_THRESHOLD if (self.arcface_loaded or self.sface_loaded) else 0.5

        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {"results": [], "processing_time": 0, "error": "Invalid image"}

        faces = self._extract_faces_from_image(img)
        if not faces:
            processing_time = round((time.time() - start_time) * 1000, 2)
            return {"results": [], "processing_time": processing_time, "error": "No face detected"}

        face = faces[0]
        face_img = face["face_img"]

        # FIX: use SFace embedding when available
        h_img, w_img = img.shape[:2]
        embedding = None
        if self.sface_loaded and face.get("yunet_raw") is not None:
            input_size = face.get("yunet_input_size", (w_img - w_img % 32, h_img - h_img % 32))
            embedding = self._sface_embed(img, face["yunet_raw"], input_size)
        if embedding is None:
            embedding = self._compute_face_embedding(face_img) if face_img.size > 0 else None

        matches = []
        current_backend = self._current_backend_tag()
        if embedding is not None:
            for pid, data in self.enrolled_faces.items():
                stored_backend = data.get("embedding_backend", "Fallback-Handcrafted")
                if stored_backend != current_backend:
                    continue
                best_sim = 0.0
                for emb_data in data.get("embeddings", []):
                    # FIX: support both plain-list and dict embedding formats
                    raw = emb_data["embedding"] if isinstance(emb_data, dict) else emb_data
                    stored = np.array(raw, dtype=np.float32)
                    if stored.shape != embedding.shape:
                        continue
                    similarity = float(np.dot(embedding, stored))
                    best_sim = max(best_sim, similarity)
                if best_sim >= threshold:
                    matches.append({
                        "person_id": pid,
                        "person_name": data.get("person_name", "Unknown"),
                        "similarity": round(best_sim, 4),
                        "department": data.get("department"),
                    })
            matches.sort(key=lambda x: x["similarity"], reverse=True)
            matches = matches[:limit]

        processing_time = round((time.time() - start_time) * 1000, 2)
        return {"results": matches, "processing_time": processing_time}

    def get_enrolled_persons(self) -> List[Dict]:
        return list(self.enrolled_faces.values())

    def get_person(self, person_id: str) -> Optional[Dict]:
        return self.enrolled_faces.get(person_id)

    def delete_person(self, person_id: str) -> bool:
        if person_id in self.enrolled_faces:
            data = self.enrolled_faces.pop(person_id)
            emb_path = EMBEDDINGS_DIR / f"{person_id}.json"
            if emb_path.exists():
                emb_path.unlink()
            for img_file in data.get("enrollment_images", []):
                img_path = UPLOADS_DIR / img_file
                if img_path.exists():
                    img_path.unlink()
            return True
        return False

    def get_health(self) -> Dict[str, Any]:
        # FIX: detection/recognition backend strings now reflect the actual active model
        if self.yunet_loaded:
            detection = "YuNet (OpenCV)"
        elif self.detector:
            detection = "MediaPipe BlazeFace"
        else:
            detection = "Haar Cascade (fallback)"

        if self.sface_loaded:
            recognition = "SFace (OpenCV, 128-dim)"
        elif self.arcface_loaded:
            recognition = "ArcFace ResNet100 (ONNX, 512-dim)"
        else:
            recognition = "Fallback: Handcrafted Features (LBP+DCT+HOG)"

        return {
            "status": "operational" if self.models_loaded else "degraded",
            "models_loaded": self.models_loaded,
            "arcface_loaded": self.arcface_loaded,
            "sface_loaded": self.sface_loaded,
            "yunet_loaded": self.yunet_loaded,
            "message": f"Face recognition service running — Detection: {detection}, Recognition: {recognition}",
            "available_models": [
                "yunet" if self.yunet_loaded else ("mediapipe_face_detection" if self.detector else "haar_cascade"),
                "sface" if self.sface_loaded else ("arcface_r100_onnx" if self.arcface_loaded else "fallback_handcrafted"),
            ],
            "enrolled_persons": len(self.enrolled_faces),
            "detection_backend": detection,
            "recognition_backend": recognition,
            "embedding_dim": ARCFACE_EMBEDDING_DIM,
        }


face_service: Optional[FaceRecognitionService] = None


def get_face_service() -> FaceRecognitionService:
    global face_service
    if face_service is None:
        face_service = FaceRecognitionService()
    return face_service
