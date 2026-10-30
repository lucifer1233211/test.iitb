import os
import cv2
import numpy as np
from utils.augment import SafeFaceAugmenter


class FaceRegistry:
    def __init__(self, embedder, preprocessor=None, augmenter=None):
        """
        embedder: SFaceEmbedder
        preprocessor: FacePreprocessor or None
        """
        self.embedder = embedder
        self.preprocessor = preprocessor
        self.augmenter = augmenter

        self.name_to_id = {}
        self.id_to_name = {}

    def load(self, db_dir, face_index, smoother=None):
        """
        db_dir: path to face_db/
        face_index: FaceIndex (FAISS wrapper)
        smoother: TemporalSmoother or None
        """

        if not os.path.isdir(db_dir):
            print(f"[FaceRegistry] No face DB found at {db_dir}")
            return

        print(f"[FaceRegistry] Loading face DB from {db_dir}")

        for name in sorted(os.listdir(db_dir)):
            person_dir = os.path.join(db_dir, name)
            if not os.path.isdir(person_dir):
                continue

            identity_id = face_index.next_id
            face_index.next_id += 1

            self.name_to_id[name] = identity_id
            self.id_to_name[identity_id] = name

            print(f"  Registering '{name}' as ID {identity_id}")

            for fname in os.listdir(person_dir):
                if not fname.lower().endswith((".jpg", ".png", ".jpeg")):
                    continue

                path = os.path.join(person_dir, fname)
                img = cv2.imread(path)
                if img is None:
                    continue

                # Optional preprocessing
                if self.preprocessor is not None:
                    img = self.preprocessor(img)

                images_to_embed = []

                # ---- If already augmented, just embed ----
                if fname.startswith("aug_") or self.augmenter is None:
                    images_to_embed.append(img)

                else:
                    # ---- Original image: embed + augment ----
                    images_to_embed.append(img)

                    augmented = self.augmenter.augment(img)
                    for aug_img, tag in augmented:
                        aug_name = f"aug_{tag}.jpg"
                        aug_path = os.path.join(person_dir, aug_name)

                        if not os.path.exists(aug_path):
                            cv2.imwrite(aug_path, aug_img)

                        images_to_embed.append(aug_img)

                # ---- Embed all collected images ----
                for im in images_to_embed:
                    emb = self.embedder.embed(im)
                    if emb is None:
                        continue

                    face_index.add(emb, identity_id)

                    if smoother is not None:
                        smoother.update(identity_id, emb)


        print("[FaceRegistry] Face DB loaded.\n")
