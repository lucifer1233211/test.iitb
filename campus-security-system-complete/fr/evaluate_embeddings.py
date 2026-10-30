import os
import argparse
import numpy as np
import cv2, random
import itertools
import matplotlib.pyplot as plt

from utils.preprocess import FacePreprocessor
from utils.sface_embedder import SFaceEmbedder
from utils.onnx_embedder import ONNXRuntimeEmbedder

MAX_PAIRS = 1_000_000

# def cosine_similarity(f1, f2):
#     return float(np.dot(f1, f2))

def cosine_similarity(f1, f2):
    f1 = f1 / np.linalg.norm(f1)
    f2 = f2 / np.linalg.norm(f2)
    return float(np.dot(f1, f2))

def load_dataset_embeddings(dataset_root, embedder, preprocessor):
    """
    Loads CASIA-WebFace style dataset:
        root/
          ├── person1/
          │    ├── img1.jpg
          │    ├── img2.jpg
          ├── person2/
          │    ├── img1.jpg
    Returns:
        dict: {person_id: [embeddings]}
    """

    embeddings = {}

    for person in sorted(os.listdir(dataset_root)):
        person_dir = os.path.join(dataset_root, person)
        if not os.path.isdir(person_dir):
            continue

        person_embeddings = []

        for img_name in os.listdir(person_dir):
            if not img_name.lower().endswith((".jpg", ".png", ".jpeg")):
                continue

            img_path = os.path.join(person_dir, img_name)
            img = cv2.imread(img_path)

            if img is None:
                continue

            img = cv2.resize(img, (112, 112))
            img = preprocessor(img)

            emb = embedder.embed(img)
            emb = emb / np.linalg.norm(emb)

            if emb is not None:
                person_embeddings.append(emb)

        if len(person_embeddings) > 0:
            embeddings[person] = person_embeddings

    return embeddings


def compute_intra_class_similarities(embeddings_dict, max_pairs=1_000_000):
    sims = []
    persons = list(embeddings_dict.keys())

    while len(sims) < max_pairs:
        person = random.choice(persons)
        embs = embeddings_dict[person]

        if len(embs) < 2:
            continue

        e1, e2 = random.sample(embs, 2)
        sims.append(cosine_similarity(e1, e2))

    return sims


def compute_inter_class_similarities(embeddings_dict, max_pairs=1_000_000):
    sims = []
    persons = list(embeddings_dict.keys())

    while len(sims) < max_pairs:
        p1, p2 = random.sample(persons, 2)

        e1 = random.choice(embeddings_dict[p1])
        e2 = random.choice(embeddings_dict[p2])

        sims.append(cosine_similarity(e1, e2))

    return sims


def plot_histogram(data, title):
    plt.figure()
    plt.hist(data, bins=50)
    plt.title(title)
    plt.xlabel("Cosine Similarity")
    plt.ylabel("Frequency")
    plt.show()


def plot_distributions(intra_sims, inter_sims, bins=200):
    """
    Plot normalized density curves for intra and inter class similarities.
    X-axis restricted to [0, 1].
    """

    # Convert to numpy
    intra_sims = np.array(intra_sims)
    inter_sims = np.array(inter_sims)

    # Restrict values to [0, 1] for visualization
    intra_sims = intra_sims[(intra_sims >= 0) & (intra_sims <= 1)]
    inter_sims = inter_sims[(inter_sims >= 0) & (inter_sims <= 1)]

    # Create bins in [0,1]
    bin_edges = np.linspace(0, 1, bins)

    # Compute normalized histograms (density=True gives probability density)
    intra_hist, _ = np.histogram(intra_sims, bins=bin_edges, density=True)
    inter_hist, _ = np.histogram(inter_sims, bins=bin_edges, density=True)

    # Compute bin centers
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

    # Plot
    plt.figure()

    plt.plot(bin_centers, intra_hist, label="Intra-class")
    plt.plot(bin_centers, inter_hist, label="Inter-class")

    plt.xlim(0, 1)

    plt.xlabel("Cosine Similarity")
    plt.ylabel("Density")
    plt.title("Embedding Similarity Distributions")
    plt.legend()

    plt.show()

def main(args):
    print("[INFO] Initializing embedder...")
    embedder = ONNXRuntimeEmbedder(
        model_path=args.model
    )

    preprocessor = FacePreprocessor(
        enable=not args.no_preprocess,
        clahe_clip=2.0,
        sharpen_amount=0.6
    )

    print("[INFO] Loading dataset and computing embeddings...")
    embeddings = load_dataset_embeddings(
        args.dataset,
        embedder,
        preprocessor
    )

    print("[INFO] Computing intra-class similarities...")
    intra_sims = compute_intra_class_similarities(embeddings)

    print("[INFO] Computing inter-class similarities...")
    inter_sims = compute_inter_class_similarities(embeddings)

    print(f"[INFO] Intra pairs: {len(intra_sims)}")
    print(f"[INFO] Inter pairs: {len(inter_sims)}")

    # ---- Plot intra-class ----
    # plot_histogram(intra_sims, "Intra-class Cosine Similarity")

    # # ---- Plot inter-class ----
    # plot_histogram(inter_sims, "Inter-class Cosine Similarity")
    print(np.mean(intra_sims), np.mean(inter_sims))

    plot_distributions(intra_sims, inter_sims)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to CASIA-WebFace style dataset"
    )
    parser.add_argument(
        "--model",
        default="models/sface/face_recognition_sface_2021dec.onnx",
        help="Path to SFace ONNX model"
    )
    parser.add_argument(
        "--no-preprocess",
        action="store_true",
        help="Disable preprocessing"
    )

    args = parser.parse_args()
    main(args)