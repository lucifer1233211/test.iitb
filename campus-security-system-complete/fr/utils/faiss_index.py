import faiss
import numpy as np


class FaceIndex:
    def __init__(self, dim, metric="cosine"):
        self.dim = dim
        self.metric = metric

        if metric == "cosine":
            # cosine similarity = inner product on normalized vectors
            self.index = faiss.IndexFlatIP(dim)
        elif metric == "l2":
            self.index = faiss.IndexFlatL2(dim)
        else:
            raise ValueError("Unsupported metric")

        self.embeddings = []      # list of np arrays
        self.identity_ids = []    # parallel list
        self.next_id = 0

    def _normalize(self, x):
        return x / np.linalg.norm(x)

    def add(self, embedding, identity_id):
        emb = embedding.astype("float32")
        if self.metric == "cosine":
            emb = self._normalize(emb)

        self.index.add(emb.reshape(1, -1))
        self.embeddings.append(emb)
        self.identity_ids.append(identity_id)

    def search(self, embedding, k=1):
        if self.index.ntotal == 0:
            return None, None

        emb = embedding.astype("float32")
        if self.metric == "cosine":
            emb = self._normalize(emb)

        distances, indices = self.index.search(
            emb.reshape(1, -1), k
        )

        return distances[0], indices[0]

    def assign_identity(self, embedding, threshold):
        """
        Returns:
            identity_id (int)
            is_new (bool)
        """

        if self.index.ntotal == 0:
            identity_id = self.next_id
            self.next_id += 1
            self.add(embedding, identity_id)
            return identity_id, True, 1

        distances, indices = self.search(embedding, k=1)
        best_dist = distances[0]
        best_idx = indices[0]

        if self.metric == "cosine":
            match = best_dist >= threshold
        else:  # l2
            match = best_dist <= threshold

        if match:
            identity_id = self.identity_ids[best_idx]
            self.add(embedding, identity_id)
            return identity_id, False, best_dist
        else:
            identity_id = self.next_id
            self.next_id += 1
            self.add(embedding, identity_id)
            return identity_id, True, 1
