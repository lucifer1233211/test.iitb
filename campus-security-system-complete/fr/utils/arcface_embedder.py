import cv2
import numpy as np


class ArcFaceEmbedder:
    """
    ArcFace ONNX embedder.
    Interface-compatible with SFaceEmbedder.
    """

    def __init__(self, model_path, input_size=(112, 112)):
        self.model_path = model_path
        self.input_size = input_size

        self.net = cv2.dnn.readNetFromONNX(model_path)

        # CPU-only by default (safe)
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

    def embed(self, face):
        """
        face: aligned face image (BGR, 112x112)
        returns: L2-normalized embedding (np.ndarray)
        """

        if face is None:
            return None

        if face.shape[:2] != self.input_size:
            face = cv2.resize(face, self.input_size)

        # ---- ArcFace preprocessing ----
        # BGR → RGB
        face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)

        # Normalize to [-1, 1]
        blob = face.astype(np.float32)
        blob = (blob - 127.5) / 128.0

        blob = np.transpose(blob, (2, 0, 1))  # CHW
        blob = np.expand_dims(blob, axis=0)

        # ---- Forward pass ----
        self.net.setInput(blob)
        emb = self.net.forward()

        emb = emb.flatten()

        # ---- L2 normalize ----
        norm = np.linalg.norm(emb)
        if norm < 1e-6:
            return None

        return emb / norm