import cv2

def video_frame_generator(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    frame_id = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        yield frame_id, frame
        frame_id += 1

    cap.release()
