from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

try:
    from embedding import VECTOR_SIZE, encode_thumbnail
except ImportError:
    from drone_backend.embedding import VECTOR_SIZE, encode_thumbnail


DINO_MODEL_NAME = "dinov2_vits14"
DINO_NATIVE_SIZE = 384
DINO_RESERVED_SIZE = VECTOR_SIZE - DINO_NATIVE_SIZE
DINO_VECTOR_LAYOUT = "dinov2_384_plus_reserved_128"


@dataclass(frozen=True)
class DinoEmbeddingResult:
    vector: list[float]
    thumbnail: str | None = None


_MODEL: Any | None = None
_TORCH: Any | None = None


def dino_to_512(vector: np.ndarray) -> list[float]:
    flat = vector.astype(np.float32).reshape(-1)

    if flat.size != DINO_NATIVE_SIZE:
        raise ValueError(
            f"Expected DINO vector size {DINO_NATIVE_SIZE}, received {flat.size}"
        )

    padded = np.zeros(VECTOR_SIZE, dtype=np.float32)
    padded[:DINO_NATIVE_SIZE] = flat

    norm = np.linalg.norm(padded)
    if norm > 0:
        padded = padded / norm

    return padded.tolist()


def load_dinov2_model() -> tuple[Any, Any]:
    global _MODEL, _TORCH

    if _MODEL is not None and _TORCH is not None:
        return _MODEL, _TORCH

    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "PyTorch is required for --embedder dinov2. Install torch/torchvision "
            "or run with --embedder opencv."
        ) from exc

    try:
        model = torch.hub.load("facebookresearch/dinov2", DINO_MODEL_NAME)
    except Exception as exc:
        raise RuntimeError(
            "Could not load DINOv2-small via torch.hub. This may require internet "
            "access the first time, or a cached model. Run with --embedder opencv "
            "if you only need the lightweight baseline."
        ) from exc

    model.eval()
    _MODEL = model
    _TORCH = torch
    return _MODEL, _TORCH


def preprocess_for_dino(image: np.ndarray, torch: Any) -> Any:
    resized = cv2.resize(image, (224, 224), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0

    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    normalized = (rgb - mean) / std
    chw = np.transpose(normalized, (2, 0, 1))

    return torch.from_numpy(chw).unsqueeze(0)


def embed_image_dinov2(image: np.ndarray) -> DinoEmbeddingResult:
    model, torch = load_dinov2_model()
    tensor = preprocess_for_dino(image, torch)

    with torch.no_grad():
        output = model(tensor)

    if isinstance(output, dict):
        output = output.get("x_norm_clstoken") or output.get("last_hidden_state")
    if isinstance(output, (tuple, list)):
        output = output[0]

    vector = output.detach().cpu().numpy().reshape(-1)
    return DinoEmbeddingResult(
        vector=dino_to_512(vector),
        thumbnail=encode_thumbnail(image),
    )
