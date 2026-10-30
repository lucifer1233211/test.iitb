import onnxruntime as ort
import numpy as np
import cv2


class ONNXRuntimeEmbedder:
    def __init__(self, model_path):
        self.session = ort.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"]
        )

        self.input_name = self.session.get_inputs()[0].name

    def embed(self, aligned_face):
        if aligned_face is None:
            return None

        # Match training preprocessing
        img = cv2.cvtColor(aligned_face, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0

        img = np.transpose(img, (2, 0, 1))
        img = np.expand_dims(img, axis=0)

        output = self.session.run(None, {self.input_name: img})[0]

        emb = output.flatten()

        norm = np.linalg.norm(emb)
        if norm < 1e-6:
            return None

        return emb / norm