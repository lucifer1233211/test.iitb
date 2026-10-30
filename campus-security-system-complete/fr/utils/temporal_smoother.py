import numpy as np


class TemporalSmoother:
    def __init__(self, enable=True, max_count=20):
        self.enable = enable
        self.max_count = max_count
        self.prototypes = {}   # identity_id -> mean embedding
        self.counts = {}       # identity_id -> number of samples

    def update(self, identity_id, embedding):
        if not self.enable:
            return embedding

        if identity_id not in self.prototypes:
            self.prototypes[identity_id] = embedding.copy()
            self.counts[identity_id] = 1
            return self.prototypes[identity_id]

        count = self.counts[identity_id]
        proto = self.prototypes[identity_id]

        # Cap contribution count
        effective_count = min(count, self.max_count)

        new_proto = (effective_count * proto + embedding) / (effective_count + 1)

        self.prototypes[identity_id] = new_proto
        self.counts[identity_id] = count + 1

        return new_proto

    def get(self, identity_id):
        return self.prototypes.get(identity_id, None)
