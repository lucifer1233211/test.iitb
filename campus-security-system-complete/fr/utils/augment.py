import cv2
import numpy as np


class SafeFaceAugmenter:
    def __init__(
        self,
        enable=True,
        rotations=(-10, -5, 5, 10),
        scales=(0.95, 1.0, 1.05),
        translations=(-5, 0, 5),
        blur_sigma=(0.0, 0.6),
        brightness=(0.9, 1.1)
    ):
        self.enable = enable
        self.rotations = rotations
        self.scales = scales
        self.translations = translations
        self.blur_sigma = blur_sigma
        self.brightness = brightness

    def augment(self, face):
        if not self.enable:
            return [(face, "orig")]

        h, w = face.shape[:2]
        cx, cy = w // 2, h // 2

        augmented = []

        for angle in self.rotations:
            for scale in self.scales:
                for dx in self.translations:
                    for dy in self.translations:
                        tag = f"rot{angle}_s{scale}_dx{dx}_dy{dy}"

                        M = cv2.getRotationMatrix2D((cx, cy), angle, scale)
                        M[0, 2] += dx
                        M[1, 2] += dy

                        warped = cv2.warpAffine(
                            face,
                            M,
                            (w, h),
                            flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_REFLECT
                        )

                        augmented.append((warped, tag))

        final = []
        for img, tag in augmented:
            for sigma in self.blur_sigma:
                tag2 = f"{tag}_blur{sigma}"
                if sigma > 0:
                    img2 = cv2.GaussianBlur(img, (0, 0), sigma)
                else:
                    img2 = img.copy()
                final.append((img2, tag2))

        output = []
        for img, tag in final:
            for b in self.brightness:
                tag2 = f"{tag}_b{b}"
                img2 = np.clip(img.astype(np.float32) * b, 0, 255).astype(np.uint8)
                output.append((img2, tag2))

        return output
