from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

import cv2
import numpy as np


VECTOR_SIZE = 512


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    thumbnail: str | None = None


def zero_vector() -> list[float]:
    return np.zeros(VECTOR_SIZE, dtype=np.float32).tolist()


def normalize_vector(vector: np.ndarray) -> list[float]:
    flat = vector.astype(np.float32).reshape(-1)

    if flat.size == 0:
        return zero_vector()

    if flat.size < VECTOR_SIZE:
        flat = np.pad(flat, (0, VECTOR_SIZE - flat.size))
    elif flat.size > VECTOR_SIZE:
        chunks = np.array_split(flat, VECTOR_SIZE)
        flat = np.array([chunk.mean() for chunk in chunks], dtype=np.float32)

    norm = np.linalg.norm(flat)
    if norm > 0:
        flat = flat / norm

    return flat.tolist()


def decode_base64_image(image_base64: str) -> np.ndarray:
    if "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]

    try:
        raw = base64.b64decode(image_base64, validate=True)
    except binascii.Error as exc:
        raise ValueError("Invalid base64 image payload") from exc

    encoded = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError("Could not decode image payload")

    return image


def encode_thumbnail(image: np.ndarray) -> str:
    resized = cv2.resize(image, (320, 180), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), 75])

    if not ok:
        return ""

    thumbnail_base64 = base64.b64encode(encoded.tobytes()).decode("utf-8")
    return f"data:image/jpeg;base64,{thumbnail_base64}"


def extract_opencv_features(image: np.ndarray) -> np.ndarray:
    resized = cv2.resize(image, (64, 64), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

    intensity_grid = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA).reshape(-1)
    hist = cv2.calcHist([gray], [0], None, [64], [0, 256]).reshape(-1)

    sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(sobel_x, sobel_y)
    gradient_grid = cv2.resize(magnitude, (16, 8), interpolation=cv2.INTER_AREA).reshape(-1)

    features = np.concatenate([
        intensity_grid / 255.0,
        hist / max(float(hist.sum()), 1.0),
        gradient_grid / 255.0,
    ])

    return features


def embed_image(image: np.ndarray) -> EmbeddingResult:
    features = extract_opencv_features(image)

    return EmbeddingResult(
        vector=normalize_vector(features),
        thumbnail=encode_thumbnail(image),
    )


def embed_base64_image(image_base64: str) -> EmbeddingResult:
    image = decode_base64_image(image_base64)
    return embed_image(image)