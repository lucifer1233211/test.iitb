import cv2
import numpy as np

CANONICAL_LANDMARKS = np.array([
    [38.2946, 51.6963],   # left eye
    [73.5318, 51.5014],   # right eye
    [56.0252, 71.7366],   # nose
    [41.5493, 92.3655],   # left mouth
    [70.7299, 92.2041],   # right mouth
], dtype=np.float32)


def should_align(bbox, landmarks):
    _, _, w, h = bbox

    right_eye = landmarks[0]
    left_eye = landmarks[1]

    eye_dist = np.linalg.norm(left_eye - right_eye)
    if eye_dist < 0.15 * w:
        return False

    lm_w = landmarks[:, 0].max() - landmarks[:, 0].min()
    lm_h = landmarks[:, 1].max() - landmarks[:, 1].min()
    if lm_w < 0.4 * w or lm_h < 0.4 * h:
        return False

    return True


def align_face(image, bbox, landmarks, output_size=(112, 112), pad=0.3):
    """
    image: resized_frame
    bbox: (x, y, w, h)
    landmarks: YuNet order
    """

    x, y, w, h = bbox
    ih, iw = image.shape[:2]

    # ---- padded ROI ----
    px = int(pad * w)
    py = int(pad * h)

    x1 = max(0, x - px)
    y1 = max(0, y - py)
    x2 = min(iw, x + w + px)
    y2 = min(ih, y + h + py)

    roi = image[y1:y2, x1:x2]
    if roi.size == 0:
        return None

    lm = landmarks.copy()
    lm[:, 0] -= x1
    lm[:, 1] -= y1

    src = np.array([
        lm[1],  # left eye
        lm[0],  # right eye
        lm[2],  # nose
        lm[4],  # left mouth
        lm[3],  # right mouth
    ], dtype=np.float32)

    dst = CANONICAL_LANDMARKS.copy()

    M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)
    if M is None:
        return None

    # ---- rotation constraint ----
    angle = np.degrees(np.arctan2(M[0, 1], M[0, 0]))
    if abs(angle) > 30:
        return None

    # ---- scale constraint ----
    scale = np.sqrt(M[0, 0]**2 + M[0, 1]**2)
    if scale < 0.5 or scale > 1.5:
        return None

    aligned = cv2.warpAffine(
        roi,
        M,
        output_size,
        flags=cv2.INTER_LINEAR,
        borderValue=0
    )

    if np.mean(aligned == 0) > 0.2:
        return None

    return aligned


def fallback_crop(image, bbox, output_size=(112, 112), pad=0.35):
    x, y, w, h = bbox
    ih, iw = image.shape[:2]

    px = int(pad * w)
    py = int(pad * h)

    x1 = max(0, x - px)
    y1 = max(0, y - py)
    x2 = min(iw, x + w + px)
    y2 = min(ih, y + h + py)

    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    return cv2.resize(crop, output_size)

