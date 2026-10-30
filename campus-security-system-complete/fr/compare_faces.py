import argparse
import cv2
import numpy as np

from utils.preprocess import FacePreprocessor
from utils.sface_embedder import SFaceEmbedder


def cosine_similarity(f1, f2):
    f1 = f1 / np.linalg.norm(f1)
    f2 = f2 / np.linalg.norm(f2)
    return float(np.dot(f1, f2))


def main(args):
    # Load images
    img1 = cv2.imread(args.image1)
    img2 = cv2.imread(args.image2)

    if img1 is None or img2 is None:
        raise RuntimeError("Could not load one or both images")

    if img1.shape[:2] != (112, 112) or img2.shape[:2] != (112, 112):
        print("[WARN] Images are not 112x112. Make sure they are aligned faces.")

    # Initialize preprocessing (same as main pipeline)
    preprocessor = FacePreprocessor(
        enable=not args.no_preprocess,
        clahe_clip=2.0,
        sharpen_amount=0.6
    )

    # Initialize SFace embedder
    embedder = SFaceEmbedder(
        model_path=args.model
    )

    # Preprocess images
    img1_p = preprocessor(img1)
    img2_p = preprocessor(img2)

    # ---- Show processed images ----
    if args.show:
        combined = np.hstack([img1_p, img2_p])
        cv2.imshow("Processed faces (left vs right)", combined)
        print("[INFO] Press any key in the image window to continue...")
        cv2.waitKey(0)
        cv2.destroyAllWindows()

    # Compute embeddings
    emb1 = embedder.embed(img1_p)
    emb2 = embedder.embed(img2_p)

    if emb1 is None or emb2 is None:
        raise RuntimeError("Embedding failed")

    # Compute similarity
    sim = cosine_similarity(emb1, emb2)

    print(f"Cosine similarity: {sim:.4f}")

    if sim >= 0.65:
        print("→ Likely SAME person")
    elif sim >= 0.5:
        print("→ Possibly same person (borderline)")
    else:
        print("→ Likely DIFFERENT people")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image1", help="Path to first aligned face image")
    parser.add_argument("image2", help="Path to second aligned face image")
    parser.add_argument(
        "--model",
        default="models/sface/face_recognition_sface_2021dec.onnx",
        help="Path to SFace ONNX model"
    )
    parser.add_argument(
        "--no-preprocess",
        action="store_true",
        help="Disable preprocessing (CLAHE + sharpening)"
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show processed images in a GUI window"
    )

    args = parser.parse_args()
    main(args)
