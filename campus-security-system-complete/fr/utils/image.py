import cv2
import os
import numpy as np

def crop_and_save(image, bbox, save_dir, prefix):
    x, y, w, h = bbox
    h_img, w_img = image.shape[:2]

    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(w_img, x + w)
    y2 = min(h_img, y + h)

    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return

    os.makedirs(save_dir, exist_ok=True)
    filename = f"{prefix}.jpg"
    cv2.imwrite(os.path.join(save_dir, filename), crop)

def crop_annotate_and_save(image, bbox, landmarks, save_dir, prefix):
    x, y, w, h = bbox

    crop = image[y:y+h, x:x+w].copy()
    if crop.size == 0:
        return

    # Shift landmarks to crop coordinates
    lm = landmarks.copy()
    lm[:, 0] -= x
    lm[:, 1] -= y

    # Draw bounding box (entire crop)
    cv2.rectangle(
        crop,
        (0, 0),
        (w - 1, h - 1),
        (0, 255, 0),
        2
    )

    # Landmark colors (same convention as YuNet demo)
    colors = [
        (255, 0, 0),    # right eye
        (0, 0, 255),    # left eye
        (0, 255, 0),    # nose
        (255, 0, 255),  # right mouth
        (0, 255, 255),  # left mouth
    ]

    for i, (px, py) in enumerate(lm.astype(int)):
        if 0 <= px < w and 0 <= py < h:
            cv2.circle(crop, (px, py), 2, colors[i], 2)

    os.makedirs(save_dir, exist_ok=True)
    out_path = os.path.join(save_dir, f"{prefix}.jpg")
    cv2.imwrite(out_path, crop)
