from detectors.people_r_people_detector import PeopleRPeopleDetector
from utils.face_registry import FaceRegistry
from utils.temporal_smoother import TemporalSmoother
from utils.preprocess import FacePreprocessor
from utils.visualize import draw_face_id
from utils.faiss_index import FaceIndex
from utils.sface_embedder import SFaceEmbedder
from utils.augment import SafeFaceAugmenter
from utils.align import align_face, should_align, fallback_crop
from utils.arcface_embedder import ArcFaceEmbedder
import argparse
import os
import cv2

from detectors.yunet_detector import YuNetDetector
from detectors.retinaface_detector import RetinaFaceDetector
from utils.video import video_frame_generator
from utils.image import crop_annotate_and_save


def get_detector(name, args):
    if name == "yunet":
        return YuNetDetector(
            model_path=args.yunet_model
        )
    elif name == "retinaface":
        return RetinaFaceDetector(
            model_path=args.retinaface_model
        )
    elif name == "people":
        return PeopleRPeopleDetector(
            cfg_path=args.people_cfg,
            weights_path=args.people_weights,
            names_path=args.people_names
        )
    else:
        raise ValueError(f"Unknown detector: {name}")

def process_frame(frame, detector, output_dir, prefix):
    detections, resized_frame = detector.detect(frame)

    for i, det in enumerate(detections):
        bbox = det["bbox"]
        landmarks = det.get("landmarks")

        # ---- Save annotated raw crop ----
        crop_annotate_and_save(
            resized_frame,
            bbox,
            landmarks,
            save_dir=os.path.join(output_dir, "crops"),
            prefix=f"{prefix}_face{i}"
        )

        # ---- Alignment ----
        if landmarks is not None and should_align(bbox, landmarks):
            aligned = align_face(resized_frame, bbox, landmarks)
        else:
            aligned = fallback_crop(resized_frame, bbox)

        if aligned is None:
            continue

        out_path = os.path.join(
            output_dir,
            "aligned",
            f"{prefix}_face{i}.jpg"
        )
        cv2.imwrite(out_path, aligned)

def main(args):
    detector = get_detector(args.detector, args)
    first = True

    crops_dir = "output/crops"
    aligned_dir = "output/aligned"
    identities_dir = "output/identities"
    os.makedirs(crops_dir, exist_ok=True)
    os.makedirs(aligned_dir, exist_ok=True)

    embedder = SFaceEmbedder(
        model_path=args.sface_model
    )

    preprocessor = FacePreprocessor(
        enable=True,      # set False to bypass entirely
        clahe_clip=2.0,
        sharpen_amount=0.6
    )

    video_writer = None
    video_out_path = "output/video_annotated.mp4"

    embeddings = []   # list of (frame_id, embedding)

    smoother = TemporalSmoother(
        enable=False,    # set False to bypass
        max_count=20
    )
    
    face_index = FaceIndex(
        dim=128,          # SFace output
        metric="cosine"
    )

    augmenter = SafeFaceAugmenter(
        enable=True   # turn off anytime
    )

    registry = FaceRegistry(
        embedder=embedder,
        preprocessor=preprocessor,
        augmenter=augmenter
    )

    registry.load(
        db_dir=args.face_db,
        face_index=face_index,
        smoother=smoother
    )

    if args.image:
        
        image = cv2.imread(args.image)
        if image is None:
            raise RuntimeError(f"Failed to read image: {args.image}")

        detector.prepare(image)
        process_frame(
            image,
            detector,
            output_dir="output",
            prefix="image"
        )
        print("[INFO] Image processing complete.")

        return

    COSINE_THRESHOLD = 0.5

    for frame_id, frame in video_frame_generator(args.video):
        if first:
            detector.prepare(frame)
            first = False
        
        # frame = preprocessor(frame)

        detections, resized_frame = detector.detect(frame)

        if video_writer is None:
            h, w = resized_frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            video_writer = cv2.VideoWriter(
                video_out_path,
                fourcc,
                25,          # FPS (safe default)
                (w, h)
            )

        for i, det in enumerate(detections):
            bbox = det["bbox"]
            landmarks = det["landmarks"]

            # ---- Annotated raw crop (debug) ----
            crop_annotate_and_save(
                resized_frame,
                bbox,
                landmarks,
                save_dir=crops_dir,
                prefix=f"frame{frame_id}_face{i}"
            )

            # ---- Alignment decision ----
            if should_align(bbox, landmarks):
               aligned = align_face(resized_frame, bbox, landmarks)
            else:
               aligned = fallback_crop(resized_frame, bbox)
            # aligned = fallback_crop(resized_frame, bbox)

            if aligned is None:
                continue

            # Save aligned face
            out_path = os.path.join(
                aligned_dir,
                f"frame{frame_id}_face{i}.jpg"
            )
    
            cv2.imwrite(out_path, aligned)

            # ---- Embedding ----
            processed = preprocessor(aligned)
            embedding = embedder.embed(processed)
            if embedding is None:
                continue

            identity_id, is_new, dist = face_index.assign_identity(
                embedding,
                threshold=COSINE_THRESHOLD
            )
            
            smoothed_embedding = smoother.update(identity_id, embedding)
            
            # ---- Decide label & color ----
            if identity_id in registry.id_to_name:
                label = registry.id_to_name[identity_id]
                color = (0, 255, 0)       # green = known
            else:
                label = f"Unknown {identity_id}: {dist}"
                color = (0, 255, 255)     # yellow = unknown

            # ---- Draw bounding box + label ----
            draw_face_id(
                resized_frame,
                bbox,
                label,
                color
            )

            status = "KNOWN" if identity_id in registry.id_to_name else "UNKNOWN"
            print(
                f"Frame {frame_id}, face {i} → {label} ({status})"
            )
            
            if is_new:
                out_path = os.path.join(
                    identities_dir,
                    f"id_{identity_id}.jpg"
                )
                cv2.imwrite(out_path, aligned)

        video_writer.write(resized_frame)

    if video_writer is not None:
        video_writer.release()

    print(f"\nAnnotated video saved to: {video_out_path}")
    
    if len(embeddings) >= 2:
        print("\nSanity check on embeddings:\n")

        f1 = embeddings[0][1]
        f2 = embeddings[-1][1]
        f3 = embeddings[10][1]

        cos_sim = embedder.cosine_similarity(f1, f2)
        cossim2 = embedder.cosine_similarity(f1, f3)
        l2_dist = embedder.l2_distance(f1, f2)
        l3 = embedder.l2_distance(f1, f3)

        print(f"Cosine similarity (first vs last): {cos_sim:.4f} {cossim2:.4f}")
        print(f"L2 distance (first vs last): {l2_dist:.4f} {l3:.4f}")
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="Path to video file")
    parser.add_argument(
        "--detector",
        choices=["yunet", "retinaface", "people"],
        default="yunet"
    )
    parser.add_argument(
        "--face-db",
        default="face_db",
        help="Path to face registration database"
    )
    parser.add_argument(
        "--image",
        help="Path to image"
    )   
    parser.add_argument(
        "--yunet-model",
        default="models/yunet/face_detection_yunet_2023mar.onnx",
        help="Path to YuNet model"
    )

    parser.add_argument(
        "--retinaface-model",
        default="models/retinaface/retinaface_resnet50.onnx",
        help="Path to RetinaFace model"
    )

    parser.add_argument(
        "--people-cfg",
        default="models/people_r_people/people-r-people.cfg",
        help="Path to People-R-People cfg"
    )

    parser.add_argument(
        "--people-weights",
        default="models/people_r_people/people-r-people_iitb_v1.1.weights",
        help="Path to People-R-People weights"
    )

    parser.add_argument(
        "--people-names",
        default="models/people_r_people/people-r-people.names",
        help="Path to People-R-People names file"
    )

    parser.add_argument(
        "--sface-model",
        default="models/sface/face_recognition_sface_2021dec.onnx",
        help="Path to SFace recognition model"
    )

    args = parser.parse_args()
    main(args)
