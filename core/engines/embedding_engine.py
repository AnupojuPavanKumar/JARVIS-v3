# core/embedding_engine.py  —  LIGHTWEIGHT (NO FREEZE)

import numpy as np
import re


class EmbeddingEngine:

    def __init__(self):
        print("[Embedding] Lightweight mode active")

    def _tokenize(self, text):
        return re.findall(r'\b\w+\b', text.lower())

    def encode(self, text: str):
        tokens = self._tokenize(text)

        vec = np.zeros(64)

        for token in tokens:
            h = hash(token) % 64
            vec[h] += 1

        # normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        return vec