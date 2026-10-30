from detectors.base_detector import FaceDetector

class RetinaFaceDetector(FaceDetector):
    def __init__(self, model_path):
        super().__init__(model_path)
        raise NotImplementedError(
            "RetinaFace inference will be added later"
        )

    def detect(self, image):
        pass
