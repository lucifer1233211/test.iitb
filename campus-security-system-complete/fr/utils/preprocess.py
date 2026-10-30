import cv2
import numpy as np

class FacePreprocessor:
    def __init__(
        self,
        enable=True,
        clahe_clip=2.0,
        clahe_grid=(8, 8),
        sharpen_amount=0.6
    ):
        """
        enable: master switch (False = no-op)
        clahe_clip: contrast limit (keep low!)
        sharpen_amount: 0.0–1.0 (keep mild)
        """
        self.enable = enable
        self.sharpen_amount = sharpen_amount

        if enable:
            self.clahe = cv2.createCLAHE(
                clipLimit=clahe_clip,
                tileGridSize=clahe_grid
            )

    def __call__(self, face):
        """
        face: aligned face (112x112 BGR)
        returns: processed face (same shape)
        """
        if not self.enable:
            return face

        # ---- CLAHE on luminance only ----
        lab = cv2.cvtColor(face, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)

        l = self.clahe.apply(l)

        lab = cv2.merge((l, a, b))
        face = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

        # ---- Mild unsharp masking ----
        if self.sharpen_amount > 0:
            blur = cv2.GaussianBlur(face, (0, 0), sigmaX=1.0)
            face = cv2.addWeighted(
                face,
                1.0 + self.sharpen_amount,
                blur,
                -self.sharpen_amount,
                0
            )

        return face
