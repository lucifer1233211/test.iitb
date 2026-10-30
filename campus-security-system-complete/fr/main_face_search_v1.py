import cv2
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from pathlib import Path
from boxmot import BoostTrack
import time
from collections import defaultdict, deque
from typing import List, Dict, Tuple, Optional
import json
from datetime import datetime


# ==================== CONFIGURATION ====================
class Config:
    # Paths
    YOLO_CFG = "/media/mdmlab/F47CCC667CCC2568/Python code/Face Recognition/people-r-people.cfg"
    YOLO_NAMES = "/media/mdmlab/F47CCC667CCC2568/Python code/Face Recognition/people-r-people.names"
    YOLO_WEIGHTS = "/media/mdmlab/F47CCC667CCC2568/Python code/Face Recognition/people-r-people_iitb_v1.weights"
    SFACE_MODEL = "/media/mdmlab/F47CCC667CCC2568/Python code/Face Recognition/face_recognition_sface_2021dec.onnx"
    REID_WEIGHTS = "/media/mdmlab/F47CCC667CCC2568/Python code/Face Recognition/clip_market1501.pt"
    
    # Video
    VIDEO_PATH = "/media/mdmlab/F47CCC667CCC2568/Python code/Face Recognition/Ygate_exit_05_01_2026_2_cut.mp4"
    REFERENCE_FACE_PATH = "/media/mdmlab/F47CCC667CCC2568/Python code/Face Recognition/allan_photo.jpeg"
    
    # Detection
    YOLO_INPUT_SIZE = 416
    PERSON_CONF_THRESHOLD = 0.5
    FACE_CONF_THRESHOLD = 0.5
    NMS_THRESHOLD = 0.4
    MIN_FACE_SIZE = 30
    PROCESS_EVERY_N_FRAMES = 1
    
    # Face Recognition
    MAX_FACES_PER_TRACK = 25
    AGGREGATION_THRESHOLD = 6  # Minimum faces for C-FAN
    MATCH_THRESHOLD = 0.70
    MATCH_CONFIDENCE_FRAMES = 3
    MIN_FACE_QUALITY_SCORE = 0.3
    
    # C-FAN Parameters
    CFAN_EMBEDDING_DIM = 128
   
    CFAN_AGGREGATION = 'weighted'  # 'mean', 'max', or 'weighted'
    
    # Output
    OUTPUT_DIR = Path("output")
    SAVE_MATCHED_FACES = True
    SAVE_ANNOTATED_VIDEO = True
    SAVE_LOG = True

class PersonDetector:
    """
    Detects PERSONS using YOLO (people-r-people model).
    Returns person bounding boxes for tracking.
    """
    
    def __init__(self, cfg_file: str, weights_file: str, names_file: str, 
                 input_size: int = 416):
        """
        Initialize person detector.
        
        Args:
            cfg_file: Path to YOLO .cfg file
            weights_file: Path to YOLO .weights file
            names_file: Path to class names file
            input_size: YOLO input size (416, 608, etc.)
        """
        self.cfg_file = cfg_file
        self.weights_file = weights_file
        self.input_size = input_size
        
        # Load class names
        self.class_names = open(names_file).read().strip().split('\n')
        
        # Find person class index
        if 'person' not in self.class_names:
            raise ValueError(f"'person' class not found in {names_file}")
        
        self.person_class_id = self.class_names.index('person')
        
        # Load YOLO network
        print(f"Loading person detector from {cfg_file}...")
        self.net = cv2.dnn.readNetFromDarknet(cfg_file, weights_file)
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        
        # Get output layers
        layer_names = self.net.getLayerNames()
        self.output_layers = [layer_names[i - 1] for i in self.net.getUnconnectedOutLayers()]
        
        print(f"✓ Person detector loaded")
        print(f"  Input size: {input_size}x{input_size}")
        print(f"  Person class ID: {self.person_class_id}")
    
    def detect(self, frame: np.ndarray, conf_threshold: float = 0.5, 
               nms_threshold: float = 0.4) -> List[Dict]:
        """
        Detect persons in frame.
        
        Args:
            frame: Input frame (BGR)
            conf_threshold: Confidence threshold
            nms_threshold: NMS IoU threshold
        
        Returns:
            List of person detections:
            [
                {
                    'box': [x1, y1, x2, y2],
                    'confidence': float,
                    'class': 'person',
                    'class_id': int
                },
                ...
            ]
        """
        height, width = frame.shape[:2]
        
        # Create blob
        blob = cv2.dnn.blobFromImage(
            frame,
            scalefactor=1/255.0,
            size=(self.input_size, self.input_size),
            swapRB=True,
            crop=False
        )
        
        # Forward pass
        self.net.setInput(blob)
        outputs = self.net.forward(self.output_layers)
        
        # Parse detections
        boxes = []
        confidences = []
        class_ids = []
        
        for output in outputs:
            for detection in output:
                scores = detection[5:]
                class_id = np.argmax(scores)
                confidence = scores[class_id]
                
                # Only keep PERSON detections
                if class_id == self.person_class_id and confidence > conf_threshold:
                    # YOLO format: center_x, center_y, width, height (normalized 0-1)
                    center_x = int(detection[0] * width)
                    center_y = int(detection[1] * height)
                    w = int(detection[2] * width)
                    h = int(detection[3] * height)
                    
                    # Convert to corner coordinates
                    x1 = int(center_x - w / 2)
                    y1 = int(center_y - h / 2)
                    
                    boxes.append([x1, y1, w, h])
                    confidences.append(float(confidence))
                    class_ids.append(class_id)
        
        # Apply Non-Maximum Suppression
        indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, nms_threshold)
        
        # Format results
        detections = []
        if len(indices) > 0:
            for i in indices.flatten():
                x1, y1, w, h = boxes[i]
                x2 = x1 + w
                y2 = y1 + h
                
                # Clamp to frame boundaries
                x1 = max(0, min(x1, width - 1))
                y1 = max(0, min(y1, height - 1))
                x2 = max(0, min(x2, width - 1))
                y2 = max(0, min(y2, height - 1))
                
                detections.append({
                    'box': [x1, y1, x2, y2],
                    'confidence': confidences[i],
                    'class': 'person',
                    'class_id': class_ids[i]
                })
        
        return detections
    
    def format_for_tracker(self, detections: List[Dict]) -> np.ndarray:
        """
        Convert detections to tracker format.
        
        Args:
            detections: List of person detections
        
        Returns:
            numpy array of shape (N, 6): [x1, y1, x2, y2, confidence, class_id]
        """
        if len(detections) == 0:
            return np.zeros((0, 6), dtype=np.float32)
        
        boxes = []
        for det in detections:
            x1, y1, x2, y2 = det['box']
            boxes.append([x1, y1, x2, y2, det['confidence'], det['class_id']])
        
        return np.array(boxes, dtype=np.float32)


class FaceDetector:
    """
    Detects FACES using YOLO (people-r-people model).
    Designed to detect faces WITHIN person bounding boxes.
    """
    
    def __init__(self, cfg_file: str, weights_file: str, names_file: str,
                 input_size: int = 416):
        """
        Initialize face detector.
        
        Args:
            cfg_file: Path to YOLO .cfg file
            weights_file: Path to YOLO .weights file
            names_file: Path to class names file
            input_size: YOLO input size
        """
        self.cfg_file = cfg_file
        self.weights_file = weights_file
        self.input_size = input_size
        
        # Load class names
        self.class_names = open(names_file).read().strip().split('\n')
        
        # Find face class index
        if 'face' not in self.class_names:
            raise ValueError(f"'face' class not found in {names_file}")
        
        self.face_class_id = self.class_names.index('face')
        
        # Load YOLO network
        print(f"Loading face detector from {cfg_file}...")
        self.net = cv2.dnn.readNetFromDarknet(cfg_file, weights_file)
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        
        # Get output layers
        layer_names = self.net.getLayerNames()
        self.output_layers = [layer_names[i - 1] for i in self.net.getUnconnectedOutLayers()]
        
        print(f"✓ Face detector loaded")
        print(f"  Input size: {input_size}x{input_size}")
        print(f"  Face class ID: {self.face_class_id}")


    def sfdetect(self, frame: np.ndarray) -> List[Dict]:
        """ This is a simple code to detect faces given a image of a person """

        if frame is None or frame.size == 0:
            print("Empty frame provided to face detector.")
            return []
        # Create blob from ROI
        blob = cv2.dnn.blobFromImage(
            frame,
            scalefactor=1/255.0,
            size=(self.input_size, self.input_size),
            swapRB=True,
            crop=False
        )
        
        # Forward pass
        self.net.setInput(blob)
        outputs = self.net.forward(self.output_layers)
        
        # Parse detections
        boxes = []
        confidences = []

        h, w = frame.shape[:2]
        face_detections = []

        for output in outputs:
            for detection in output:
                scores = detection[5:]
                class_id = int(np.argmax(scores))
                confidence = float(scores[class_id])

                # ✅ FACE CLASS CHECK
                if class_id != self.face_class_id or confidence <= 0.5:
                    continue

                # YOLO normalized bbox
                cx, cy, bw, bh = detection[:4]

                # Convert to absolute frame coordinates
                cx_abs = int(cx * w)
                cy_abs = int(cy * h)
                bw_abs = int(bw * w)
                bh_abs = int(bh * h)

                x1_abs = int(cx_abs - bw_abs / 2)
                y1_abs = int(cy_abs - bh_abs / 2)
                x2_abs = int(cx_abs + bw_abs / 2)
                y2_abs = int(cy_abs + bh_abs / 2)

                # Clip to image bounds
                x1_abs = max(0, x1_abs)
                y1_abs = max(0, y1_abs)
                x2_abs = min(w - 1, x2_abs)
                y2_abs = min(h - 1, y2_abs)

                boxes.append([x1_abs, y1_abs, x2_abs - x1_abs, y2_abs - y1_abs])
                confidences.append(confidence)
                face_detections.append({
                    'box': [x1_abs, y1_abs, x2_abs, y2_abs],
                })
        return face_detections    
    
    def detect_in_roi(self, frame: np.ndarray, person_box: List[int],
                      conf_threshold: float = 0.5,
                      nms_threshold: float = 0.4,
                      min_face_size: int = 30) -> List[Dict]:
        """
        Detect faces within a person's bounding box.
        
        Args:
            frame: Full frame (BGR)
            person_box: Person bounding box [x1, y1, x2, y2]
            conf_threshold: Confidence threshold
            nms_threshold: NMS IoU threshold
            min_face_size: Minimum face size in pixels
        
        Returns:
            List of face detections (coordinates relative to FULL FRAME):
            [
                {
                    'box': [x1, y1, x2, y2],  # Absolute coordinates in full frame
                    'confidence': float,
                    'class': 'face',
                    'face_crop': np.ndarray  # Cropped face image
                },
                ...
            ]
        """
        x1_p, y1_p, x2_p, y2_p = person_box
        
        # Validate person box
        if x2_p <= x1_p or y2_p <= y1_p:
            return []
        
        frame_h, frame_w = frame.shape[:2]
        
        # Clamp person box to frame
        x1_p = max(0, min(x1_p, frame_w - 1))
        y1_p = max(0, min(y1_p, frame_h - 1))
        x2_p = max(0, min(x2_p, frame_w - 1))
        y2_p = max(0, min(y2_p, frame_h - 1))
        
        # Extract person ROI
        person_roi = frame[y1_p:y2_p, x1_p:x2_p]
        
        if person_roi.size == 0:
            return []
        
        roi_h, roi_w = person_roi.shape[:2]
        
        # Create blob from ROI
        blob = cv2.dnn.blobFromImage(
            person_roi,
            scalefactor=1/255.0,
            size=(self.input_size, self.input_size),
            swapRB=True,
            crop=False
        )
        
        # Forward pass
        self.net.setInput(blob)
        outputs = self.net.forward(self.output_layers)
        
        # Parse detections
        boxes = []
        confidences = []
        
        for output in outputs:
            for detection in output:
                scores = detection[5:]
                class_id = np.argmax(scores)
                confidence = scores[class_id]
                
                # Only keep FACE detections
                if class_id == self.face_class_id and confidence > conf_threshold:
                    # YOLO outputs normalized coordinates relative to ROI
                    center_x = int(detection[0] * roi_w)
                    center_y = int(detection[1] * roi_h)
                    w = int(detection[2] * roi_w)
                    h = int(detection[3] * roi_h)
                    
                    # Convert to corner coordinates (relative to ROI)
                    x1_roi = int(center_x - w / 2)
                    y1_roi = int(center_y - h / 2)
                    
                    boxes.append([x1_roi, y1_roi, w, h])
                    confidences.append(float(confidence))
        
        # Apply NMS
        indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, nms_threshold)
        
        # Format results
        face_detections = []
        if len(indices) > 0:
            for i in indices.flatten():
                x1_roi, y1_roi, w, h = boxes[i]
                x2_roi = x1_roi + w
                y2_roi = y1_roi + h
                
                # Clamp to ROI boundaries
                x1_roi = max(0, min(x1_roi, roi_w - 1))
                y1_roi = max(0, min(y1_roi, roi_h - 1))
                x2_roi = max(0, min(x2_roi, roi_w - 1))
                y2_roi = max(0, min(y2_roi, roi_h - 1))
                
                # Check minimum face size
                face_w = x2_roi - x1_roi
                face_h = y2_roi - y1_roi
                
                if face_w < min_face_size or face_h < min_face_size:
                    continue
                
                # Convert to absolute coordinates in full frame
                x1_abs = x1_p + x1_roi
                y1_abs = y1_p + y1_roi
                x2_abs = x1_p + x2_roi
                y2_abs = y1_p + y2_roi
                
                # Extract face crop from full frame
                face_crop = frame[y1_abs:y2_abs, x1_abs:x2_abs]
                
                if face_crop.size == 0:
                    continue
                
                face_detections.append({
                    'box': [x1_abs, y1_abs, x2_abs, y2_abs],
                    'confidence': confidences[i],
                    'class': 'face',
                    'face_crop': face_crop
                })
        
        return face_detections
    
    def detect_faces_for_tracks(self, frame: np.ndarray, 
                                person_tracks: np.ndarray,
                                conf_threshold: float = 0.5,
                                nms_threshold: float = 0.4,
                                min_face_size: int = 30) -> Dict[int, List[Dict]]:
        """
        Detect faces for multiple person tracks.
        
        Args:
            frame: Full frame
            person_tracks: Array of person tracks (N x 8): [x1, y1, x2, y2, track_id, conf, cls, ind]
            conf_threshold: Face detection confidence threshold
            nms_threshold: NMS threshold
            min_face_size: Minimum face size
        
        Returns:
            Dictionary mapping track_id to list of face detections:
            {
                track_id: [
                    {'box': [...], 'confidence': float, 'face_crop': np.ndarray},
                    ...
                ],
                ...
            }
        """
        faces_per_track = {}
        
        for track in person_tracks:
            x1, y1, x2, y2, track_id, conf, cls, ind = track
            track_id = int(track_id)
            person_box = [int(x1), int(y1), int(x2), int(y2)]
            
            # Detect faces in this person's bounding box
            face_detections = self.detect_in_roi(
                frame,
                person_box,
                conf_threshold,
                nms_threshold,
                min_face_size
            )
            
            if len(face_detections) > 0:
                faces_per_track[track_id] = face_detections
        
        return faces_per_track


# ==================== C-FAN AGGREGATOR ====================
class CFANAggregator:
    """Component-wise Feature Aggregation Network from the paper."""

    def __init__(self, embedding_dim=128, aggregation='weighted'):
        self.embedding_dim = embedding_dim
        self.aggregation = aggregation

    def aggregate_embeddings(
        self,
        embeddings_list: List[np.ndarray],
        quality_scores: Optional[List[float]] = None
    ) -> Optional[np.ndarray]:
        """
        Aggregate embeddings using weighted mean.
        Higher quality frames contribute more.
        """

        if len(embeddings_list) == 0:
            return None

        if len(embeddings_list) == 1:
            emb = embeddings_list[0]
            return emb / (np.linalg.norm(emb) + 1e-8)

        E = np.stack(embeddings_list, axis=0)  # (N, D)

        # L2 normalize each embedding
        E = E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-8)

        # if quality_scores is not None:
        #     weights = np.array(quality_scores, dtype=np.float32)
        #     weights = weights / (weights.sum() + 1e-8)
        #     aggregated = np.sum(E * weights[:, None], axis=0)
        # else:
        aggregated = np.mean(E, axis=0)

        # Final L2 normalization
        aggregated = aggregated / (np.linalg.norm(aggregated) + 1e-8)

        return aggregated



# ==================== FACE QUALITY ====================
class FaceQualityChecker:
    @staticmethod
    def calculate_blur(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        return cv2.Laplacian(gray, cv2.CV_64F).var()
    
    @staticmethod
    def calculate_brightness(image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        return np.mean(gray)
    
    @staticmethod
    def assess_quality(face_img) -> Tuple[float, Dict]:
        h, w = face_img.shape[:2]
        
        size = min(h, w)
        size_score = min(1.0, size / 112.0) if size >= Config.MIN_FACE_SIZE else 0.0
        
        blur = FaceQualityChecker.calculate_blur(face_img)
        blur_score = min(1.0, blur / 100.0)
        
        brightness = FaceQualityChecker.calculate_brightness(face_img)
        brightness_score = 1.0 - abs(brightness - 128) / 128.0
        
        quality = 0.4 * size_score + 0.4 * blur_score + 0.2 * brightness_score
        
        return quality, {
            "size": size,
            "blur": blur,
            "brightness": brightness,
            "quality": quality
        }


# ==================== SFACE RECOGNIZER ====================
class SFaceRecognizer:
    def __init__(self):
        self.sface_model = None
        
        self.cfan = CFANAggregator(
            embedding_dim=Config.CFAN_EMBEDDING_DIM,
            aggregation=Config.CFAN_AGGREGATION
        )
        self.load_sface()
    
    def load_sface(self):
            """Load SFace model for face recognition"""
            print("\nLoading SFace model...")
            
            # Try to download or find model
            model_path = "/media/mdmlab/F47CCC667CCC2568/Python code/Face Recognition/face_recognition_sface_2021dec.onnx"
            
            if model_path is None:
                print("ERROR: Could not find or download SFace model")
                
                return
            try:
                # Alternative using DNN
                self.sface_model = cv2.FaceRecognizerSF.create(model_path, "")

                print("SFace loaded using opencv loader ")
            except:
                print("Failed to load SFace model")
        
    def extract_face_embedding_sface(self, frame: np.ndarray, face_box: Tuple) -> np.ndarray:
        """Extract face embedding using SFace"""
        if self.sface_model is None:
            return None
        x1, y1, x2, y2 = face_box[:4]
        face_align = self.sface_model.alignCrop(frame, np.array([[x1, y1, x2, y2]]))
        embedding = self.sface_model.feature(face_align)
        return embedding.flatten()
    
    def compare_faces(self, embedding1: np.ndarray, embedding2: np.ndarray) -> float:
        """Calculate cosine similarity between embeddings"""
        if embedding1 is None or embedding2 is None:
            return 0.0
        
        similarity = np.dot(embedding1, embedding2) / (
            np.linalg.norm(embedding1) * np.linalg.norm(embedding2))
        return float(similarity)
    

    def set_reference_face(self, face_image: np.ndarray, name: str = "Target"):
        self.reference_name = name
        config = Config()
        fdetector = FaceDetector(
            config.YOLO_CFG,
            config.YOLO_WEIGHTS,
            config.YOLO_NAMES,
            config.YOLO_INPUT_SIZE
        )

        h, w = face_image.shape[:2]
        top_left     = (0, 0)
        top_right    = (w - 1, 0)
        bottom_right = (w - 1, h - 1)
        bottom_left  = (0, h - 1)

        vertices = [top_left, top_right, bottom_right, bottom_left]

        faceboxn = fdetector.sfdetect(face_image)
        if faceboxn is None or len(faceboxn) == 0:
            print(f"✗ No face detected in reference image for {name}")
            facebox = vertices
        else:
            facebox = faceboxn[0]['box']
            if facebox is None:
                print(f"✗ No face detected in reference image for {name}")
                facebox = vertices

        embedding = self.extract_face_embedding_sface(face_image,facebox)
        if embedding is not None:
            self.reference_embedding = embedding
            print(f"✓ Reference: {name}")
            return True
        return False
    
    def aggregate_embeddings_cfan(self, embeddings: List[np.ndarray],
                                   qualities: Optional[List[float]] = None) -> np.ndarray:
        return self.cfan.aggregate_embeddings(embeddings, qualities)
    
    def calculate_distance(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        return np.linalg.norm(emb1 - emb2)
    
    def match_embedding(self, embedding: np.ndarray) -> Tuple[bool, float]:
        if self.reference_embedding is None:
            return False, 1.0
        similarity = self.compare_faces(self.reference_embedding, embedding)
        return similarity > Config.MATCH_THRESHOLD, similarity


# ==================== TRACK MANAGER ====================
class TrackManager:
    def __init__(self, face_recognizer: SFaceRecognizer, max_faces: int = 30):
        self.face_recognizer = face_recognizer
        self.max_faces = max_faces
        self.tracks = defaultdict(lambda: {
            'faces': deque(maxlen=max_faces),
            'embeddings': deque(maxlen=max_faces),
            'qualities': deque(maxlen=max_faces),
            'frame_ids': deque(maxlen=max_faces),
            'match_history': deque(maxlen=10),
            'is_target': False,
            'best_distance': 0.0,
            'first_seen': None,
            'last_seen': None,
            'aggregation_method': None,
        })
    
    def add_face(self, track_id: int, face_img: np.ndarray, embedding: np.ndarray,
                 quality: float, frame_id: int):
        track = self.tracks[track_id]
        
        if track['first_seen'] is None:
            track['first_seen'] = frame_id
        track['last_seen'] = frame_id
        
        track['faces'].append(face_img.copy())
        track['embeddings'].append(embedding)
        track['qualities'].append(quality)
        track['frame_ids'].append(frame_id)
    
    def get_aggregated_embedding(self, track_id: int) -> Optional[np.ndarray]:
        track = self.tracks[track_id]
        
        if len(track['embeddings']) == 0:
            return None
        
        if len(track['embeddings']) >= Config.AGGREGATION_THRESHOLD:
            # Use C-FAN
            embeddings = list(track['embeddings'])
            qualities = list(track['qualities'])
            aggregated = self.face_recognizer.aggregate_embeddings_cfan(embeddings, qualities)
            track['aggregation_method'] = 'cfan'
            return aggregated
        else:
            # Use best single
            best_idx = np.argmax(list(track['qualities']))
            track['aggregation_method'] = 'single'
            return track['embeddings'][best_idx]
    
    def update_match_status(self, track_id: int, is_match: bool, distance: float):
        track = self.tracks[track_id]
        track['match_history'].append(is_match)
        
        if is_match and distance > track['best_distance']:
            track['best_distance'] = distance
        
        if len(track['match_history']) >= Config.MATCH_CONFIDENCE_FRAMES:
            recent = list(track['match_history'])[-Config.MATCH_CONFIDENCE_FRAMES:]
            track['is_target'] = sum(recent) >= (Config.MATCH_CONFIDENCE_FRAMES - 1)
    
    def is_target_track(self, track_id: int) -> bool:
        return self.tracks[track_id]['is_target']
    
    def get_track_info(self, track_id: int) -> Dict:
        track = self.tracks[track_id]
        return {
            'track_id': track_id,
            'num_faces': len(track['faces']),
            'is_target': track['is_target'],
            'best_distance': track['best_distance'],
            'first_seen': track['first_seen'],
            'last_seen': track['last_seen'],
            'avg_quality': np.mean(list(track['qualities'])) if track['qualities'] else 0.0,
            'aggregation_method': track['aggregation_method']
        }


# ==================== MAIN PROCESSOR ====================
class FaceSearchProcessor:
    def __init__(self, config: Config):
        self.config = config
        
        print("\n" + "="*60)
        print("INITIALIZING PERSON DETECTOR")
        print("="*60)
        self.person_detector = PersonDetector(
            config.YOLO_CFG,
            config.YOLO_WEIGHTS,
            config.YOLO_NAMES,
            config.YOLO_INPUT_SIZE
        )
        
        print("\n" + "="*60)
        print("INITIALIZING FACE DETECTOR")
        print("="*60)
        self.face_detector = FaceDetector(
            config.YOLO_CFG,
            config.YOLO_WEIGHTS,
            config.YOLO_NAMES,
            config.YOLO_INPUT_SIZE
        )
        
        print("\n" + "="*60)
        print("INITIALIZING PERSON TRACKER")
        print("="*60)
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        try:
            reid_path = Path(config.REID_WEIGHTS)
            if reid_path.exists():
                self.tracker = BoostTrack(reid_weights=reid_path, device=device, half=False, with_reid=True)
                print("✓ Tracker WITH ReID")
            else:
                raise FileNotFoundError
        except:
            self.tracker = BoostTrack(device=device, half=False, with_reid=False)
            print("✓ Tracker WITHOUT ReID")
        
        print("\n" + "="*60)
        print("INITIALIZING SFACE WITH C-FAN")
        print("="*60)
        self.face_recognizer = SFaceRecognizer()
        
        if Path(config.REFERENCE_FACE_PATH).exists():
            ref_img = cv2.imread(config.REFERENCE_FACE_PATH)
            print(f"\nSetting reference face from {config.REFERENCE_FACE_PATH}...")
            if ref_img is not None:
                self.face_recognizer.set_reference_face(ref_img)
        
        self.track_manager = TrackManager(self.face_recognizer, config.MAX_FACES_PER_TRACK)
        
        # Output
        config.OUTPUT_DIR.mkdir(exist_ok=True)
        (config.OUTPUT_DIR / "matched_faces").mkdir(exist_ok=True)
        (config.OUTPUT_DIR / "logs").mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = config.OUTPUT_DIR / "logs" / f"log_{timestamp}.txt"
        self.video_writer = None
        
        self.stats = {
            'frames_processed': 0,
            'persons_detected': 0,
            'faces_detected': 0,
            'target_found': False,
            'target_track_ids': set(),
            'cfan_used': 0,
            'single_used': 0
        }
    
    def _process_frame(self, frame: np.ndarray, frame_id: int) -> np.ndarray:
        """
        Process single frame:
        1. Detect persons
        2. Track persons
        3. For each person track, detect faces
        4. Extract face embeddings
        5. Aggregate using C-FAN
        6. Match against reference
        """
        
        # Step 1: Detect persons
        person_detections = self.person_detector.detect(
            frame,
            conf_threshold=self.config.PERSON_CONF_THRESHOLD,
            nms_threshold=self.config.NMS_THRESHOLD
        )
        
        self.stats['persons_detected'] += len(person_detections)
        
        # Step 2: Track persons
        detections_array = self.person_detector.format_for_tracker(person_detections)
        
        person_tracks = np.empty((0, 8))
        try:
            if len(detections_array) > 0:
                person_tracks = self.tracker.update(detections_array, frame)
        except Exception as e:
            print(f"Tracker error: {e}")
        
        # Step 3: For each person track, detect faces
        faces_per_track = self.face_detector.detect_faces_for_tracks(
            frame,
            person_tracks,
            conf_threshold=self.config.FACE_CONF_THRESHOLD,
            nms_threshold=self.config.NMS_THRESHOLD,
            min_face_size=self.config.MIN_FACE_SIZE
        )
        
        # Step 4 & 5: Process faces for each track
        for track in person_tracks:
            x1_p, y1_p, x2_p, y2_p, track_id, conf, cls, ind = track
            track_id = int(track_id)
            
            # Draw person box
            self._draw_person_box(frame, int(x1_p), int(y1_p), int(x2_p), int(y2_p), track_id)
            
            # Check if faces detected for this track
            if track_id not in faces_per_track:
                continue
            
            face_detections = faces_per_track[track_id]
            self.stats['faces_detected'] += len(face_detections)
            
            # Process each face
            for face_det in face_detections:
                face_crop = face_det['face_crop']
                
                # # Quality check
                quality, _ = FaceQualityChecker.assess_quality(face_crop)
                if quality < self.config.MIN_FACE_QUALITY_SCORE:
                    continue
                
                # Extract embedding
                embedding = self.face_recognizer.extract_face_embedding_sface(frame, face_det['box'])
                if embedding is None:
                    continue
                
                # Add to track manager
                self.track_manager.add_face(track_id, face_crop, embedding, quality, frame_id)
                
                # Draw face box
                x1_f, y1_f, x2_f, y2_f = face_det['box']
                cv2.rectangle(frame, (x1_f, y1_f), (x2_f, y2_f), (255, 0, 255), 1)
            
            # Get aggregated embedding for this person track
            agg_emb = self.track_manager.get_aggregated_embedding(track_id)
            
            if agg_emb is not None:
                info = self.track_manager.get_track_info(track_id)
                if info['aggregation_method'] == 'cfan':
                    self.stats['cfan_used'] += 1
                else:
                    self.stats['single_used'] += 1
                
                # Match against reference
                is_match, distance = self.face_recognizer.match_embedding(agg_emb)
                self.track_manager.update_match_status(track_id, is_match, distance)
                
                # Check if target
                if self.track_manager.is_target_track(track_id):
                    self.stats['target_found'] = True
                    self.stats['target_track_ids'].add(track_id)
                    
                    if self.config.SAVE_MATCHED_FACES and len(face_detections) > 0:
                        path = self.config.OUTPUT_DIR / "matched_faces" / f"track_{track_id}_frame_{frame_id}.jpg"
                        cv2.imwrite(str(path), face_detections[0]['face_crop'])
                    
                    self._log(f"Frame {frame_id}: TARGET - Track {track_id}, d={distance:.3f}, "
                             f"method={info['aggregation_method']}, faces={info['num_faces']}")
        
        # Draw info
        self._draw_info(frame, frame_id, len(person_tracks))
        
        return frame
    
    def _draw_person_box(self, frame, x1, y1, x2, y2, track_id):
        is_target = self.track_manager.is_target_track(track_id)
        color = (0, 255, 0) if is_target else (0, 0, 255)
        thickness = 3 if is_target else 2
        
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        
        info = self.track_manager.get_track_info(track_id)
        label = f"P{track_id}"
        if is_target:
            label += f" TARGET d:{info['best_distance']:.2f}"
        label += f" [{info['num_faces']}f]"
        if info['aggregation_method']:
            label += f" {'C' if info['aggregation_method']=='cfan' else 'S'}"
        
        cv2.rectangle(frame, (x1, y1-25), (x1+len(label)*8, y1), color, -1)
        cv2.putText(frame, label, (x1+2, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
    
    def _draw_info(self, frame, fid, num_tracks):
        y = 25
        cv2.putText(frame, f"Frame: {fid}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
        y += 25
        cv2.putText(frame, f"Persons: {num_tracks}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
        y += 25
        cv2.putText(frame, f"Faces: {self.stats['faces_detected']}", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
        y += 25
        
        if self.stats['target_found']:
            cv2.putText(frame, f"TARGET: {len(self.stats['target_track_ids'])} person(s)", 
                       (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)
        else:
            cv2.putText(frame, "Searching...", (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,165,255), 2)
    
    def _log(self, msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log = f"[{ts}] {msg}"
        print(log)
        with open(self.log_file, 'a') as f:
            f.write(log + "\n")
    
    def process_video(self, video_path: str):
        print("\n" + "="*60)
        print("PROCESSING VIDEO")
        print("="*60)
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open: {video_path}")
        
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        print(f"Video: {w}x{h} @ {fps}fps, {total} frames")
        
        if self.config.SAVE_ANNOTATED_VIDEO:
            out = self.config.OUTPUT_DIR / "annotated.mp4"
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.video_writer = cv2.VideoWriter(str(out), fourcc, fps, (w, h))
        
        fid = 0
        start = time.time()
        
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                fid += 1
                
                if fid % self.config.PROCESS_EVERY_N_FRAMES != 0:
                    if self.video_writer:
                        self.video_writer.write(frame)
                    continue
                
                processed = self._process_frame(frame, fid)
                self.stats['frames_processed'] += 1
                
                if self.video_writer:
                    self.video_writer.write(processed)
                
                cv2.imshow('Face Search', processed)
                
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('p'):
                    cv2.waitKey(0)
                
                if fid % 100 == 0:
                    elapsed = time.time() - start
                    print(f"{fid}/{total} ({100*fid/total:.1f}%) - {fid/elapsed:.1f} fps")
        
        finally:
            cap.release()
            if self.video_writer:
                self.video_writer.release()
            cv2.destroyAllWindows()
        
        self._report()
    
    def _report(self):
        print("\n" + "="*60)
        print("FINAL REPORT")
        print("="*60)
        print(f"Frames: {self.stats['frames_processed']}")
        print(f"Persons detected: {self.stats['persons_detected']}")
        print(f"Faces detected: {self.stats['faces_detected']}")
        print(f"Person tracks: {len(self.track_manager.tracks)}")
        print(f"C-FAN aggregations: {self.stats['cfan_used']}")
        print(f"Single aggregations: {self.stats['single_used']}")
        print(f"Target found: {self.stats['target_found']}")
        
        if self.stats['target_found']:
            for tid in self.stats['target_track_ids']:
                info = self.track_manager.get_track_info(tid)
                print(f"\n  Person Track {tid}:")
                print(f"    Faces collected: {info['num_faces']}")
                print(f"    Best distance: {info['best_distance']:.3f}")
                print(f"    Method: {info['aggregation_method']}")
                print(f"    Frames: {info['first_seen']}-{info['last_seen']}")


# ==================== MAIN ====================
def main():
    config = Config()
    processor = FaceSearchProcessor(config)
    processor.process_video(config.VIDEO_PATH)
    print("\n✓ Complete!")

if __name__ == "__main__":
    main()