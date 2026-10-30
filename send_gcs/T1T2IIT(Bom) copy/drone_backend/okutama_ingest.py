from __future__ import annotations

import argparse
import json
import math
import shutil
import shlex
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

import cv2
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models
from sklearn.metrics.pairwise import cosine_similarity

try:
    from dino_embedding import DINO_MODEL_NAME, DINO_VECTOR_LAYOUT, embed_image_dinov2
    from embedding import VECTOR_SIZE, embed_image, normalize_vector
except ImportError:
    from drone_backend.dino_embedding import DINO_MODEL_NAME, DINO_VECTOR_LAYOUT, embed_image_dinov2
    from drone_backend.embedding import VECTOR_SIZE, embed_image, normalize_vector


COLLECTION_NAME = "stead_medoids"
DATASET_NAME = "Okutama-Action"
DEFAULT_LABELS_KIND = "SingleActionTrackingLabels"
DEFAULT_QDRANT_PATH = Path(__file__).resolve().parent / "local_qdrant_db"
FALLBACK_LABELS_KINDS = (
    "SingleActionTrackingLabels",
    "SingleActionLabels",
    "MultiActionLabels",
)
VIDEO_SUFFIXES = {".avi", ".mp4", ".mov", ".mkv", ".m4v"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}
RagTier = Literal["T1", "T2", "T3"]
SelectorMode = Literal["auto", "submodlib", "fallback"]
EmbedderMode = Literal["opencv", "dinov2"]
T2_VISUAL_VECTOR_LAYOUT = "drone_visual_logdet_t2_v1"


@dataclass(frozen=True)
class VideoNameMetadata:
    drone_number: int | None
    day_part: int | None
    scenario: int | None


@dataclass(frozen=True)
class OkutamaLabel:
    track_id: int
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    frame: int
    lost: int
    occluded: int
    generated: int
    label: str
    actions: tuple[str, ...]

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.xmin, self.ymin, self.xmax, self.ymax)


@dataclass
class MedoidCandidate:
    tier: RagTier
    label: str
    description: str
    vector: list[float]
    thumbnail: str | None
    metadata: dict[str, Any]


@dataclass
class IngestionSummary:
    dataset_root: str
    split: str
    dry_run: bool
    reset: bool
    videos_discovered: int
    videos_processed: int
    candidates: dict[str, int]
    selected: dict[str, int]
    upserted: int
    selected_ids: list[str]
    skipped_files: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_root": self.dataset_root,
            "split": self.split,
            "dry_run": self.dry_run,
            "reset": self.reset,
            "videos_discovered": self.videos_discovered,
            "videos_processed": self.videos_processed,
            "candidates": self.candidates,
            "selected": self.selected,
            "upserted": self.upserted,
            "selected_ids": self.selected_ids,
            "skipped_files": self.skipped_files,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class MediaSource:
    path: Path
    stem: str
    name: str
    kind: Literal["video", "frames"]


def parse_video_name(video_path: Path) -> VideoNameMetadata:
    parts = video_path.stem.split(".")
    if len(parts) < 3:
        return VideoNameMetadata(None, None, None)

    try:
        return VideoNameMetadata(
            drone_number=int(parts[0]),
            day_part=int(parts[1]),
            scenario=int(parts[2]),
        )
    except ValueError:
        return VideoNameMetadata(None, None, None)


def parse_okutama_label_row(row: str) -> OkutamaLabel:
    tokens = shlex.split(row.strip())
    if len(tokens) < 11:
        raise ValueError(f"Expected at least 11 columns, received {len(tokens)}")

    try:
        return OkutamaLabel(
            track_id=int(tokens[0]),
            xmin=float(tokens[1]),
            ymin=float(tokens[2]),
            xmax=float(tokens[3]),
            ymax=float(tokens[4]),
            frame=int(tokens[5]),
            lost=int(tokens[6]),
            occluded=int(tokens[7]),
            generated=int(tokens[8]),
            label=tokens[9],
            actions=tuple(tokens[10:]),
        )
    except ValueError as exc:
        raise ValueError(f"Could not parse Okutama label row: {row}") from exc


def parse_label_file(label_path: Path) -> list[OkutamaLabel]:
    records: list[OkutamaLabel] = []
    for line_number, row in enumerate(label_path.read_text().splitlines(), start=1):
        row = row.strip()
        if not row:
            continue
        try:
            records.append(parse_okutama_label_row(row))
        except ValueError as exc:
            raise ValueError(f"{label_path}:{line_number}: {exc}") from exc
    return records


def split_matches(path: Path, split: str) -> bool:
    if split == "all":
        return True
    split_lower = split.lower()
    parts = {part.lower() for part in path.parts}
    return split_lower in parts


def discover_media_sources(
    dataset_root: Path,
    split: str,
    video_glob: str,
    frame_glob: str,
) -> list[MediaSource]:
    videos = [
        path
        for path in dataset_root.glob(video_glob)
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
    ]
    video_sources = [
        MediaSource(path=path, stem=path.stem, name=path.name, kind="video")
        for path in videos
        if split_matches(path, split)
    ]

    frame_files = [
        path
        for path in dataset_root.glob(frame_glob)
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    frame_dirs = sorted({path.parent for path in frame_files})
    frame_sources = [
        MediaSource(path=path, stem=path.name, name=path.name, kind="frames")
        for path in frame_dirs
        if split_matches(path, split)
    ]

    return sorted(video_sources + frame_sources, key=lambda source: str(source.path))


def label_kind_candidates(preferred: str) -> tuple[str, ...]:
    ordered = [preferred]
    ordered.extend(kind for kind in FALLBACK_LABELS_KINDS if kind != preferred)
    return tuple(ordered)


def find_label_file(dataset_root: Path, media: MediaSource, preferred_kind: str) -> Path | None:
    stem = media.stem
    suffixes = (".txt", ".csv")

    for labels_kind in label_kind_candidates(preferred_kind):
        kind_matches = [
            path
            for path in dataset_root.rglob(f"*{stem}*")
            if path.is_file()
            and path.suffix.lower() in suffixes
            and labels_kind.lower() in str(path).lower()
        ]
        if kind_matches:
            return sorted(kind_matches)[0]

    generic_matches = [
        path
        for path in dataset_root.rglob(f"*{stem}*")
        if path.is_file() and path.suffix.lower() in suffixes
    ]
    return sorted(generic_matches)[0] if generic_matches else None


def labels_by_frame(labels: Iterable[OkutamaLabel]) -> dict[int, list[OkutamaLabel]]:
    by_frame: dict[int, list[OkutamaLabel]] = {}
    for record in labels:
        by_frame.setdefault(record.frame, []).append(record)
    return by_frame


def labels_by_track(labels: Iterable[OkutamaLabel]) -> dict[int, list[OkutamaLabel]]:
    by_track: dict[int, list[OkutamaLabel]] = {}
    for record in labels:
        by_track.setdefault(record.track_id, []).append(record)
    for track_records in by_track.values():
        track_records.sort(key=lambda item: item.frame)
    return by_track


def action_name(actions: Iterable[str]) -> str:
    clean = [action.upper().replace(" ", "_") for action in actions if action]
    return clean[0] if clean else "UNKNOWN_ACTION"


def safe_crop(frame: np.ndarray, bbox: tuple[float, float, float, float]) -> np.ndarray | None:
    height, width = frame.shape[:2]
    xmin, ymin, xmax, ymax = bbox
    x1 = max(0, min(width - 1, int(round(xmin))))
    y1 = max(0, min(height - 1, int(round(ymin))))
    x2 = max(0, min(width, int(round(xmax))))
    y2 = max(0, min(height, int(round(ymax))))

    if x2 <= x1 or y2 <= y1:
        return None

    return frame[y1:y2, x1:x2]


def read_frame_at(cap: cv2.VideoCapture, frame_index: int) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    return frame if ok else None


def image_frame_index(path: Path) -> int | None:
    try:
        return int(path.stem)
    except ValueError:
        return None


def discover_frame_files(frame_dir: Path) -> list[tuple[int, Path]]:
    indexed: list[tuple[int, Path]] = []
    for path in frame_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        index = image_frame_index(path)
        if index is None:
            continue
        indexed.append((index, path))
    return sorted(indexed, key=lambda item: item[0])


def label_metadata(
    *,
    video_path: Path,
    video_meta: VideoNameMetadata,
    record: OkutamaLabel | None,
    frame_index: int,
    labels_kind: str,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "dataset": DATASET_NAME,
        "video_name": video_path.name,
        "frame": frame_index,
        "labels_kind": labels_kind,
        "drone_number": video_meta.drone_number,
        "day_part": video_meta.day_part,
        "scenario": video_meta.scenario,
    }

    if record is not None:
        metadata.update(
            {
                "track_id": record.track_id,
                "actions": list(record.actions),
                "bbox": list(record.bbox),
                "lost": record.lost,
                "occluded": record.occluded,
                "generated": record.generated,
            }
        )

    return metadata


def build_payload(candidate: MedoidCandidate, medoid_id: str) -> dict[str, Any]:
    return {
        "id": medoid_id,
        "tier": candidate.tier,
        "label": candidate.label,
        "description": candidate.description,
        "source": "BASE",
        "thumbnail": candidate.thumbnail,
        "metadata": candidate.metadata,
        "created_at": time.time(),
    }


def frame_indices(total_frames: int, stride: int, limit: int) -> list[int]:
    if total_frames <= 0:
        return []

    stride = max(1, stride)
    indices = list(range(0, total_frames, stride))
    if limit > 0:
        indices = indices[:limit]
    return indices


def make_t1_candidate(
    *,
    video_path: Path,
    video_meta: VideoNameMetadata,
    frame: np.ndarray,
    frame_index: int,
    labels_kind: str,
    embedder: EmbedderMode,
) -> MedoidCandidate:
    if embedder == "dinov2":
        embedding = embed_image_dinov2(frame)
        embedder_name = DINO_MODEL_NAME
        vector_layout = DINO_VECTOR_LAYOUT
    else:
        embedding = embed_image(frame)
        embedder_name = "opencv"
        vector_layout = "opencv_features_512"

    scenario = video_meta.scenario if video_meta.scenario is not None else "UNKNOWN"
    return MedoidCandidate(
        tier="T1",
        label=f"OKUTAMA_T1_SCENARIO_{scenario}_FRAME_{frame_index}",
        description=(
            "Okutama-Action spatial baseline medoid from a full aerial frame."
        ),
        vector=embedding.vector,
        thumbnail=embedding.thumbnail,
        metadata=label_metadata(
            video_path=video_path,
            video_meta=video_meta,
            record=None,
            frame_index=frame_index,
            labels_kind=labels_kind,
        )
        | {
            "embedder": embedder_name,
            "vector_layout": vector_layout,
        },
    )


def make_t2_visual_candidate(
    *,
    video_path: Path,
    video_meta: VideoNameMetadata,
    frame_index: int,
    visual_vector: list[float],
    labels_kind: str,
) -> MedoidCandidate:
    scenario = video_meta.scenario if video_meta.scenario is not None else "UNKNOWN"
    return MedoidCandidate(
        tier="T2",
        label=f"DRONE_T2_LOGDET_SCENARIO_{scenario}_FRAME_{frame_index}",
        description=(
            "Drone 1/3 behavioral diversity medoid selected from the same visual "
            "candidate pool as T1 using log-determinant optimization."
        ),
        vector=visual_vector,
        thumbnail=None,
        metadata=label_metadata(
            video_path=video_path,
            video_meta=video_meta,
            record=None,
            frame_index=frame_index,
            labels_kind=labels_kind,
        )
        | {
            "vector_layout": T2_VISUAL_VECTOR_LAYOUT,
        },
    )


def temporal_descriptor(track_records: list[OkutamaLabel]) -> np.ndarray:
    if not track_records:
        return np.zeros(16, dtype=np.float32)

    centers = np.array(
        [
            [
                (record.xmin + record.xmax) / 2.0,
                (record.ymin + record.ymax) / 2.0,
            ]
            for record in track_records
        ],
        dtype=np.float32,
    )
    areas = np.array(
        [
            max(0.0, record.xmax - record.xmin)
            * max(0.0, record.ymax - record.ymin)
            for record in track_records
        ],
        dtype=np.float32,
    )
    frames = np.array([record.frame for record in track_records], dtype=np.float32)
    deltas = np.diff(centers, axis=0) if len(centers) > 1 else np.zeros((0, 2), dtype=np.float32)
    speeds = np.linalg.norm(deltas, axis=1) if deltas.size else np.zeros(1, dtype=np.float32)
    frame_span = max(float(frames[-1] - frames[0]), 1.0)
    displacement = float(np.linalg.norm(centers[-1] - centers[0])) if len(centers) > 1 else 0.0

    actions = sorted({action for record in track_records for action in record.actions})
    action_hash = sum((index + 1) * sum(map(ord, action)) for index, action in enumerate(actions))

    raw = np.array(
        [
            len(track_records),
            frame_span,
            displacement,
            float(speeds.mean()),
            float(speeds.std()),
            float(areas.mean()),
            float(areas.std()),
            float(np.mean([record.lost for record in track_records])),
            float(np.mean([record.occluded for record in track_records])),
            float(np.mean([record.generated for record in track_records])),
            float(len(actions)),
            float(action_hash % 997),
            float(centers[:, 0].mean()),
            float(centers[:, 1].mean()),
            float(centers[:, 0].std()),
            float(centers[:, 1].std()),
        ],
        dtype=np.float32,
    )
    return raw


def make_t2_candidate(
    *,
    video_path: Path,
    video_meta: VideoNameMetadata,
    track_records: list[OkutamaLabel],
    visual_vector: list[float] | None,
    labels_kind: str,
) -> MedoidCandidate:
    first = track_records[0]
    actions = sorted({action for record in track_records for action in record.actions})
    descriptor = temporal_descriptor(track_records)
    visual = np.array(visual_vector or [], dtype=np.float32)
    vector = normalize_vector(np.concatenate([descriptor, visual]))
    action = action_name(actions)
    return MedoidCandidate(
        tier="T2",
        label=f"OKUTAMA_T2_{action}_TRACK_{first.track_id}",
        description=(
            "Okutama-Action behavioral grammar medoid from a short annotated "
            "track/action window."
        ),
        vector=vector,
        thumbnail=None,
        metadata=label_metadata(
            video_path=video_path,
            video_meta=video_meta,
            record=first,
            frame_index=first.frame,
            labels_kind=labels_kind,
        )
        | {
            "window_start": track_records[0].frame,
            "window_end": track_records[-1].frame,
            "window_size": len(track_records),
        },
    )


def make_t3_candidate(
    *,
    video_path: Path,
    video_meta: VideoNameMetadata,
    record: OkutamaLabel,
    crop: np.ndarray,
    labels_kind: str,
) -> MedoidCandidate:
    embedding = embed_image(crop)
    return MedoidCandidate(
        tier="T3",
        label=f"OKUTAMA_T3_PROXY_TRACK_{record.track_id}",
        description=(
            "Okutama-Action proxy entity/session anchor from an actor crop; "
            "this is not a biometric identity record."
        ),
        vector=embedding.vector,
        thumbnail=embedding.thumbnail,
        metadata=label_metadata(
            video_path=video_path,
            video_meta=video_meta,
            record=record,
            frame_index=record.frame,
            labels_kind=labels_kind,
        ),
    )


def build_candidates_for_video(
    *,
    video_path: Path,
    label_path: Path,
    labels_kind: str,
    frame_stride: int,
    max_frames_per_video: int,
    window_size: int,
    embedder: EmbedderMode,
) -> dict[RagTier, list[MedoidCandidate]]:
    labels = parse_label_file(label_path)
    by_frame = labels_by_frame(labels)
    by_track = labels_by_track(labels)
    video_meta = parse_video_name(video_path)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sampled_indices = frame_indices(total_frames, frame_stride, max_frames_per_video)
        candidates: dict[RagTier, list[MedoidCandidate]] = {
            "T1": [],
            "T2": [],
            "T3": [],
        }
        frame_embeddings: dict[int, list[float]] = {}

        for index in sampled_indices:
            frame = read_frame_at(cap, index)
            if frame is None:
                continue
            t1_candidate = make_t1_candidate(
                video_path=video_path,
                video_meta=video_meta,
                frame=frame,
                frame_index=index,
                labels_kind=labels_kind,
                embedder=embedder,
            )
            candidates["T1"].append(t1_candidate)
            frame_embeddings[index] = t1_candidate.vector

            frame_records = [
                record for record in by_frame.get(index, []) if record.lost == 0
            ]
            for record in frame_records[:3]:
                crop = safe_crop(frame, record.bbox)
                if crop is None:
                    continue
                candidates["T3"].append(
                    make_t3_candidate(
                        video_path=video_path,
                        video_meta=video_meta,
                        record=record,
                        crop=crop,
                        labels_kind=labels_kind,
                    )
                )

        for track_records in by_track.values():
            for start in range(0, len(track_records), max(1, window_size)):
                window = track_records[start : start + window_size]
                if len(window) < 2:
                    continue
                nearest_frame = min(
                    frame_embeddings,
                    key=lambda frame_index: abs(frame_index - window[0].frame),
                    default=None,
                )
                visual_vector = frame_embeddings.get(nearest_frame) if nearest_frame is not None else None
                candidates["T2"].append(
                    make_t2_candidate(
                        video_path=video_path,
                        video_meta=video_meta,
                        track_records=window,
                        visual_vector=visual_vector,
                        labels_kind=labels_kind,
                    )
                )

        return candidates
    finally:
        cap.release()


def build_candidates_for_frame_dir(
    *,
    frame_dir: Path,
    label_path: Path,
    labels_kind: str,
    frame_stride: int,
    max_frames_per_video: int,
    window_size: int,
    embedder: EmbedderMode,
) -> dict[RagTier, list[MedoidCandidate]]:
    labels = parse_label_file(label_path)
    by_frame = labels_by_frame(labels)
    by_track = labels_by_track(labels)
    video_meta = parse_video_name(frame_dir)
    frames = discover_frame_files(frame_dir)
    stride = max(1, frame_stride)
    sampled_frames = frames[::stride]
    if max_frames_per_video > 0:
        sampled_frames = sampled_frames[:max_frames_per_video]

    candidates: dict[RagTier, list[MedoidCandidate]] = {
        "T1": [],
        "T2": [],
        "T3": [],
    }
    frame_embeddings: dict[int, list[float]] = {}

    for frame_index, image_path in sampled_frames:
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            continue

        t1_candidate = make_t1_candidate(
            video_path=frame_dir,
            video_meta=video_meta,
            frame=frame,
            frame_index=frame_index,
            labels_kind=labels_kind,
            embedder=embedder,
        )
        candidates["T1"].append(t1_candidate)
        frame_embeddings[frame_index] = t1_candidate.vector

        frame_records = [
            record for record in by_frame.get(frame_index, []) if record.lost == 0
        ]
        for record in frame_records[:3]:
            crop = safe_crop(frame, record.bbox)
            if crop is None:
                continue
            candidates["T3"].append(
                make_t3_candidate(
                    video_path=frame_dir,
                    video_meta=video_meta,
                    record=record,
                    crop=crop,
                    labels_kind=labels_kind,
                )
            )

    for track_records in by_track.values():
        for start in range(0, len(track_records), max(1, window_size)):
            window = track_records[start : start + window_size]
            if len(window) < 2:
                continue
            nearest_frame = min(
                frame_embeddings,
                key=lambda frame_index: abs(frame_index - window[0].frame),
                default=None,
            )
            visual_vector = frame_embeddings.get(nearest_frame) if nearest_frame is not None else None
            candidates["T2"].append(
                make_t2_candidate(
                    video_path=frame_dir,
                    video_meta=video_meta,
                    track_records=window,
                    visual_vector=visual_vector,
                    labels_kind=labels_kind,
                )
            )

    return candidates


def build_t1_candidates_for_video(
    *,
    video_path: Path,
    labels_kind: str,
    frame_stride: int,
    max_frames_per_video: int,
    embedder: EmbedderMode,
) -> dict[RagTier, list[MedoidCandidate]]:
    video_meta = parse_video_name(video_path)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")

    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        candidates: dict[RagTier, list[MedoidCandidate]] = {
            "T1": [],
            "T2": [],
            "T3": [],
        }
        for index in frame_indices(total_frames, frame_stride, max_frames_per_video):
            frame = read_frame_at(cap, index)
            if frame is None:
                continue
            t1_candidate = make_t1_candidate(
                video_path=video_path,
                video_meta=video_meta,
                frame=frame,
                frame_index=index,
                labels_kind=labels_kind,
                embedder=embedder,
            )
            candidates["T1"].append(t1_candidate)
            candidates["T2"].append(
                make_t2_visual_candidate(
                    video_path=video_path,
                    video_meta=video_meta,
                    frame_index=index,
                    visual_vector=t1_candidate.vector,
                    labels_kind=labels_kind,
                )
            )
        return candidates
    finally:
        cap.release()


def build_t1_candidates_for_frame_dir(
    *,
    frame_dir: Path,
    labels_kind: str,
    frame_stride: int,
    max_frames_per_video: int,
    embedder: EmbedderMode,
) -> dict[RagTier, list[MedoidCandidate]]:
    video_meta = parse_video_name(frame_dir)
    frames = discover_frame_files(frame_dir)
    sampled_frames = frames[:: max(1, frame_stride)]
    if max_frames_per_video > 0:
        sampled_frames = sampled_frames[:max_frames_per_video]

    candidates: dict[RagTier, list[MedoidCandidate]] = {
        "T1": [],
        "T2": [],
        "T3": [],
    }

    for frame_index, image_path in sampled_frames:
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        t1_candidate = make_t1_candidate(
            video_path=frame_dir,
            video_meta=video_meta,
            frame=frame,
            frame_index=frame_index,
            labels_kind=labels_kind,
            embedder=embedder,
        )
        candidates["T1"].append(t1_candidate)
        candidates["T2"].append(
            make_t2_visual_candidate(
                video_path=frame_dir,
                video_meta=video_meta,
                frame_index=frame_index,
                visual_vector=t1_candidate.vector,
                labels_kind=labels_kind,
            )
        )

    return candidates


def similarity_matrix(vectors: list[list[float]]) -> np.ndarray:
    if not vectors:
        return np.empty((0, 0), dtype=np.float32)
    matrix = np.array(vectors, dtype=np.float32)
    sims = cosine_similarity(matrix)
    sims = np.nan_to_num(sims, nan=0.0, posinf=1.0, neginf=0.0)
    return np.clip((sims + 1.0) / 2.0, 0.0, 1.0).astype(np.float64)


def require_submodlib() -> dict[str, Any]:
    try:
        from submodlib.functions.facilityLocation import FacilityLocationFunction
        from submodlib.functions.logDeterminant import LogDeterminantFunction
    except ImportError as exc:
        raise RuntimeError(
            "submodlib is required for Okutama medoid distillation. "
            "Install drone_backend/requirements.txt before running this CLI."
        ) from exc

    imports: dict[str, Any] = {
        "facility_location": FacilityLocationFunction,
        "log_determinant": LogDeterminantFunction,
        "mutual_information": None,
    }

    try:
        from submodlib.functions.facilityLocationMutualInformation import (
            FacilityLocationMutualInformationFunction,
        )

        imports["mutual_information"] = FacilityLocationMutualInformationFunction
    except ImportError:
        imports["mutual_information"] = None

    return imports


def greedy_indices(result: list[Any]) -> list[int]:
    indices: list[int] = []
    for item in result:
        if isinstance(item, tuple):
            indices.append(int(item[0]))
        else:
            indices.append(int(item))
    return indices


def select_with_submodlib(
    *,
    tier: RagTier,
    candidates: list[MedoidCandidate],
    budget: int,
    selector: SelectorMode = "auto",
) -> list[MedoidCandidate]:
    if budget <= 0 or not candidates:
        return []

    budget = min(budget, len(candidates))
    try:
        imports = require_submodlib()
    except RuntimeError:
        if selector == "submodlib":
            raise
        return select_with_fallback(
            tier=tier,
            candidates=candidates,
            budget=budget,
        )

    vectors = [candidate.vector for candidate in candidates]
    sijs = similarity_matrix(vectors)
    n = len(candidates)

    if tier == "T1":
        objective = imports["facility_location"](
            n=n,
            mode="dense",
            sijs=sijs,
            separate_rep=False,
        )
    elif tier == "T2":
        objective = imports["log_determinant"](
            n=n,
            mode="dense",
            sijs=sijs,
            lambdaVal=1.0,
        )
    else:
        mutual_information = imports["mutual_information"]
        if mutual_information is None or n < 2:
            objective = imports["facility_location"](
                n=n,
                mode="dense",
                sijs=sijs,
                separate_rep=False,
            )
        else:
            query_count = max(1, int(math.sqrt(n)))
            query_data = np.array(vectors[:query_count], dtype=np.float64)
            data = np.array(vectors, dtype=np.float64)
            objective = mutual_information(
                n=n,
                num_queries=query_count,
                data=data,
                queryData=query_data,
                metric="cosine",
            )

    selected = objective.maximize(
        budget=budget,
        optimizer="NaiveGreedy",
        stopIfZeroGain=False,
        stopIfNegativeGain=False,
        verbose=False,
    )
    return [candidates[index] for index in greedy_indices(selected)]


def select_with_fallback(
    *,
    tier: RagTier,
    candidates: list[MedoidCandidate],
    budget: int,
) -> list[MedoidCandidate]:
    if budget <= 0 or not candidates:
        return []

    budget = min(budget, len(candidates))
    sijs = similarity_matrix([candidate.vector for candidate in candidates])

    if tier == "T1":
        centrality = sijs.mean(axis=1)
        selected_indices = [int(np.argmax(centrality))]
    else:
        selected_indices = [0]

    while len(selected_indices) < budget:
        best_index: int | None = None
        best_score = -float("inf")
        for index in range(len(candidates)):
            if index in selected_indices:
                continue
            similarity_to_selected = float(np.max(sijs[index, selected_indices]))
            current_coverage = np.max(sijs[:, selected_indices], axis=1)
            coverage_gain = float(np.maximum(sijs[:, index] - current_coverage, 0.0).sum())
            diversity = 1.0 - similarity_to_selected
            score = coverage_gain + diversity
            if tier == "T1":
                score += float(sijs[index].mean())
            if score > best_score:
                best_score = score
                best_index = index

        if best_index is None:
            break
        selected_indices.append(best_index)

    return [candidates[index] for index in selected_indices]


def qdrant_vector_config() -> models.VectorParams:
    return models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE)


def ensure_collection(qdrant: QdrantClient) -> None:
    collections = qdrant.get_collections().collections
    collection_names = {collection.name for collection in collections}
    if COLLECTION_NAME in collection_names:
        return
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=qdrant_vector_config(),
    )


def reset_collection(qdrant: QdrantClient) -> None:
    collections = qdrant.get_collections().collections
    collection_names = {collection.name for collection in collections}
    if COLLECTION_NAME in collection_names:
        qdrant.delete_collection(collection_name=COLLECTION_NAME)

    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=qdrant_vector_config(),
    )


def upsert_candidates(
    *,
    qdrant_path: Path,
    candidates: Iterable[MedoidCandidate],
    reset: bool,
) -> list[str]:
    if reset and qdrant_path.exists():
        shutil.rmtree(qdrant_path)

    qdrant = QdrantClient(path=str(qdrant_path))
    ensure_collection(qdrant)

    points: list[models.PointStruct] = []
    medoid_ids: list[str] = []
    for candidate in candidates:
        point_id = str(uuid.uuid4())
        medoid_id = f"{candidate.tier.lower()}-{point_id[:12]}"
        medoid_ids.append(medoid_id)
        points.append(
            models.PointStruct(
                id=point_id,
                vector=candidate.vector,
                payload=build_payload(candidate, medoid_id),
            )
        )

    if points:
        qdrant.upsert(collection_name=COLLECTION_NAME, points=points)

    return medoid_ids


def merge_candidates(
    target: dict[RagTier, list[MedoidCandidate]],
    source: dict[RagTier, list[MedoidCandidate]],
) -> None:
    for tier in ("T1", "T2", "T3"):
        target[tier].extend(source[tier])


def run_ingestion(args: argparse.Namespace) -> IngestionSummary:
    dataset_root = Path(args.dataset_root).expanduser().resolve()
    if not dataset_root.exists():
        raise FileNotFoundError(f"Dataset root does not exist: {dataset_root}")

    media_sources = discover_media_sources(
        dataset_root,
        args.split,
        args.video_glob,
        args.frame_glob,
    )
    all_candidates: dict[RagTier, list[MedoidCandidate]] = {
        "T1": [],
        "T2": [],
        "T3": [],
    }
    skipped_files: list[str] = []
    warnings: list[str] = []
    processed = 0

    for media in media_sources:
        label_path = find_label_file(dataset_root, media, args.labels_kind)

        try:
            if label_path is None and media.kind == "video":
                video_candidates = build_t1_candidates_for_video(
                    video_path=media.path,
                    labels_kind=args.labels_kind,
                    frame_stride=args.frame_stride,
                    max_frames_per_video=args.max_frames_per_video,
                    embedder=args.embedder,
                )
                warnings.append(
                    f"Missing labels for {media.name}; built T1/T2 from visual candidates and skipped T3."
                )
            elif label_path is None and media.kind == "frames":
                video_candidates = build_t1_candidates_for_frame_dir(
                    frame_dir=media.path,
                    labels_kind=args.labels_kind,
                    frame_stride=args.frame_stride,
                    max_frames_per_video=args.max_frames_per_video,
                    embedder=args.embedder,
                )
                warnings.append(
                    f"Missing labels for {media.name}; built T1/T2 from visual candidates and skipped T3."
                )
            elif media.kind == "video":
                video_candidates = build_candidates_for_video(
                    video_path=media.path,
                    label_path=label_path,
                    labels_kind=args.labels_kind,
                    frame_stride=args.frame_stride,
                    max_frames_per_video=args.max_frames_per_video,
                    window_size=args.window_size,
                    embedder=args.embedder,
                )
            else:
                video_candidates = build_candidates_for_frame_dir(
                    frame_dir=media.path,
                    label_path=label_path,
                    labels_kind=args.labels_kind,
                    frame_stride=args.frame_stride,
                    max_frames_per_video=args.max_frames_per_video,
                    window_size=args.window_size,
                    embedder=args.embedder,
                )
        except Exception as exc:
            skipped_files.append(str(media.path))
            warnings.append(f"{media.name}: {exc}")
            continue

        merge_candidates(all_candidates, video_candidates)
        processed += 1

    selected_by_tier: dict[RagTier, list[MedoidCandidate]] = {
        "T1": select_with_submodlib(
            tier="T1",
            candidates=all_candidates["T1"],
            budget=args.budget_t1,
            selector=args.selector,
        ),
        "T2": select_with_submodlib(
            tier="T2",
            candidates=all_candidates["T2"],
            budget=args.budget_t2,
            selector=args.selector,
        ),
        "T3": select_with_submodlib(
            tier="T3",
            candidates=all_candidates["T3"],
            budget=args.budget_t3,
            selector=args.selector,
        ),
    }
    selected = [
        candidate
        for tier in ("T1", "T2", "T3")
        for candidate in selected_by_tier[tier]
    ]

    selected_ids: list[str] = []
    if not args.dry_run:
        selected_ids = upsert_candidates(
            qdrant_path=Path(args.qdrant_path),
            candidates=selected,
            reset=args.reset,
        )

    return IngestionSummary(
        dataset_root=str(dataset_root),
        split=args.split,
        dry_run=args.dry_run,
        reset=args.reset,
        videos_discovered=len(media_sources),
        videos_processed=processed,
        candidates={tier: len(all_candidates[tier]) for tier in ("T1", "T2", "T3")},
        selected={tier: len(selected_by_tier[tier]) for tier in ("T1", "T2", "T3")},
        upserted=0 if args.dry_run else len(selected_ids),
        selected_ids=selected_ids,
        skipped_files=skipped_files,
        warnings=warnings,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Distill Okutama-Action medoids into the local STEAD Qdrant store."
    )
    parser.add_argument("--dataset-root", required=True, help="Local Okutama dataset root.")
    parser.add_argument(
        "--split",
        choices=("train", "test", "all"),
        default="all",
        help="Dataset split to ingest. Uses path-name matching.",
    )
    parser.add_argument(
        "--video-glob",
        default="**/*",
        help="Recursive glob used to discover video files.",
    )
    parser.add_argument(
        "--frame-glob",
        default="**/*",
        help="Recursive glob used to discover extracted image frame files.",
    )
    parser.add_argument(
        "--labels-kind",
        default=DEFAULT_LABELS_KIND,
        help="Preferred Okutama label directory/kind.",
    )
    parser.add_argument("--budget-t1", type=int, default=20)
    parser.add_argument("--budget-t2", type=int, default=40)
    parser.add_argument("--budget-t3", type=int, default=20)
    parser.add_argument(
        "--embedder",
        choices=("opencv", "dinov2"),
        default="opencv",
        help="Image embedder used for T1 spatial medoids.",
    )
    parser.add_argument(
        "--selector",
        choices=("auto", "submodlib", "fallback"),
        default="auto",
        help=(
            "Medoid selector. auto uses submodlib when available and fallback "
            "otherwise; submodlib fails if unavailable."
        ),
    )
    parser.add_argument("--frame-stride", type=int, default=30)
    parser.add_argument("--window-size", type=int, default=30)
    parser.add_argument(
        "--max-frames-per-video",
        type=int,
        default=240,
        help="Safety cap for sampled full-frame candidates per video; <=0 disables cap.",
    )
    parser.add_argument(
        "--qdrant-path",
        default=str(DEFAULT_QDRANT_PATH),
        help="Path to the local Qdrant store.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse, build candidates, and select medoids without writing Qdrant.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Recreate the medoid collection before writing selected medoids.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        summary = run_ingestion(args)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    print(json.dumps({"success": True, "summary": summary.to_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
