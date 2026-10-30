import cv2
import numpy as np
from detectors.base_detector import FaceDetector


class PeopleRPeopleDetector(FaceDetector):
    """
    YOLO Darknet-based head/person detector.
    Tracking-only detector (NO landmarks).
    """

    def __init__(
        self,
        cfg_path,
        weights_path,
        names_path,
        conf_threshold=0.4,
        nms_threshold=0.45,
        input_size=416
    ):
        super().__init__(weights_path)

        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold
        self.input_size = input_size
        self.allowed_classes = {"face", "head"}

        # Load class names
        with open(names_path, "r") as f:
            self.class_names = [line.strip() for line in f.readlines()]

        # Load YOLO Darknet network
        self.net = cv2.dnn.readNetFromDarknet(cfg_path, weights_path)
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

        self.output_layer_names = self.net.getUnconnectedOutLayersNames()

    def prepare(self, frame):
        """No per-video preparation needed."""
        pass

    def detect(self, frame):
        """
        Returns:
            detections: list of dicts with bbox + confidence
            frame: unchanged frame
        """

        h, w = frame.shape[:2]

        blob = cv2.dnn.blobFromImage(
            frame,
            scalefactor=1 / 255.0,
            size=(self.input_size, self.input_size),
            swapRB=True,
            crop=False
        )

        self.net.setInput(blob)
        outputs = self.net.forward(self.output_layer_names)

        boxes = []
        confidences = []

        for out in outputs:
            for det in out:
                scores = det[5:]
                class_id = np.argmax(scores)
                confidence = scores[class_id]

                class_name = self.class_names[class_id]
                
                if class_name not in self.allowed_classes:
                    continue
                
                if confidence < self.conf_threshold:
                    continue

                cx, cy, bw, bh = det[:4]
                x = int((cx - bw / 2) * w)
                y = int((cy - bh / 2) * h)
                bw = int(bw * w)
                bh = int(bh * h)

                boxes.append([x, y, bw, bh])
                confidences.append(float(confidence))

        indices = cv2.dnn.NMSBoxes(
            boxes,
            confidences,
            self.conf_threshold,
            self.nms_threshold
        )

        detections = []
        for i in indices.flatten():
            x, y, bw, bh = boxes[i]

            detections.append({
                "bbox": (x, y, bw, bh),
                "confidence": confidences[i],
                "landmarks": None   # IMPORTANT: no landmarks
            })

        return detections, frame

