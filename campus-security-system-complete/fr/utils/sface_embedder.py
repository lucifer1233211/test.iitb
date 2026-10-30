import cv2
import numpy as np


class SFaceEmbedder:
    def __init__(self, model_path):
        """
        model_path: path to face_recognition_sface_*.onnx
        """
        self.recognizer = cv2.FaceRecognizerSF.create(
            model_path,
            ""
        )

    def embed(self, aligned_face):
        """
        aligned_face: 112x112 BGR image
        returns: 1D numpy array (embedding)
        """

        if aligned_face is None:
            return None

        # SFace expects aligned face already
        feature = self.recognizer.feature(aligned_face).flatten()

        norm = np.linalg.norm(feature)
        if norm < 1e-6:
            return None

        return feature / norm

    @staticmethod
    def cosine_similarity(f1, f2):
        f1 = f1 / np.linalg.norm(f1)
        f2 = f2 / np.linalg.norm(f2)
        return float(np.dot(f1, f2))

    @staticmethod
    def l2_distance(f1, f2):
        return float(np.linalg.norm(f1 - f2))
