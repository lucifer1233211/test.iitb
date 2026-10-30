from abc import ABC, abstractmethod

class FaceDetector(ABC):
    def __init__(self, model_path):
        self.model_path = model_path

    @abstractmethod
    def detect(self, image):
        """
        Returns:
            List of detections.
            Each detection must at least contain:
            {
                "bbox": (x, y, w, h)
            }
        """
        pass
