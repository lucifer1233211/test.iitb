import cv2


def draw_face_id(image, bbox, label, color):
    x, y, w, h = bbox

    cv2.rectangle(
        image,
        (x, y),
        (x + w, y + h),
        color,
        2
    )

    cv2.putText(
        image,
        label,
        (x, y - 5 if y - 5 > 10 else y + 15),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        color,
        2
    )
