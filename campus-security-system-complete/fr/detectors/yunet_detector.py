import cv2
from detectors.base_detector import FaceDetector

class YuNetDetector(FaceDetector):

    def __init__(
        self,
        model_path,
        score_threshold=0.9,
        nms_threshold=0.3,
        top_k=5000,
        scale=1.0
    ):
        super().__init__(model_path)
        self.scale = scale
        self.detector = cv2.FaceDetectorYN.create(
            model_path,
            "",
            (320, 320),   # Initial dummy size
            score_threshold,
            nms_threshold,
            top_k,
            # ADD THESE TWO LINES:
            backend_id=cv2.dnn.DNN_BACKEND_OPENCV,
            target_id=cv2.dnn.DNN_TARGET_CPU
        )
        self.input_size = None

    def prepare(self, frame):
        """Call ONCE before processing video"""
        h, w = frame.shape[:2]
        fw = int(w * self.scale)
        fh = int(h * self.scale)

        # 🔴 MUST be divisible by 32
        fw = fw - (fw % 32)
        fh = fh - (fh % 32)

        self.input_size = (fw, fh)
        self.detector.setInputSize(self.input_size)

    def detect(self, frame):
        if self.input_size is None:
            raise RuntimeError("Call prepare(frame) once before detect()")

        # Get original dimensions
        orig_h, orig_w = frame.shape[:2]
        
        # Perform detection on the resized frame
        frame_resized = cv2.resize(frame, self.input_size)
        faces = self.detector.detect(frame_resized)

        if faces[1] is None:
            return [], frame_resized

        # Calculate scale factors to map coordinates back if necessary
        # Or simply ensure the user knows detections are relative to frame_resized
        detections = []
        for face in faces[1]:
            # If you want coordinates relative to the RESIZED frame:
            x, y, w, h = face[:4].astype(int)
            
            detections.append({
                "bbox": (x, y, w, h),
                "landmarks": face[4:14].reshape((5, 2)),
                "confidence": float(face[-1])
            })

        return detections, frame_resized

