from __future__ import annotations

import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
import sys
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import okutama_ingest as ingest
import dino_embedding
from embedding import VECTOR_SIZE


class OkutamaIngestUnitTests(unittest.TestCase):
    def test_parse_label_row_with_multiple_actions(self) -> None:
        row = '7 10 20 110 220 42 0 1 0 "Person" Running Carrying'

        parsed = ingest.parse_okutama_label_row(row)

        self.assertEqual(parsed.track_id, 7)
        self.assertEqual(parsed.bbox, (10.0, 20.0, 110.0, 220.0))
        self.assertEqual(parsed.frame, 42)
        self.assertEqual(parsed.label, "Person")
        self.assertEqual(parsed.actions, ("Running", "Carrying"))
        self.assertEqual(parsed.occluded, 1)

    def test_parse_video_name_metadata(self) -> None:
        metadata = ingest.parse_video_name(Path("1.2.15.mp4"))

        self.assertEqual(metadata.drone_number, 1)
        self.assertEqual(metadata.day_part, 2)
        self.assertEqual(metadata.scenario, 15)

    def test_build_payload_shape(self) -> None:
        candidate = ingest.MedoidCandidate(
            tier="T3",
            label="OKUTAMA_T3_PROXY_TRACK_2",
            description="Proxy entity/session anchor, not biometric identity.",
            vector=[0.0] * VECTOR_SIZE,
            thumbnail="data:image/jpeg;base64,abc",
            metadata={"dataset": "Okutama-Action", "track_id": 2},
        )

        payload = ingest.build_payload(candidate, "t3-test")

        self.assertEqual(payload["id"], "t3-test")
        self.assertEqual(payload["tier"], "T3")
        self.assertEqual(payload["source"], "BASE")
        self.assertEqual(payload["metadata"]["track_id"], 2)
        self.assertIn("created_at", payload)

    def test_temporal_candidate_vector_dimensionality(self) -> None:
        records = [
            ingest.parse_okutama_label_row(
                f'1 {10 + i} {20 + i} {110 + i} {220 + i} {i} 0 0 0 "Person" Running'
            )
            for i in range(3)
        ]

        candidate = ingest.make_t2_candidate(
            video_path=Path("1.1.1.mp4"),
            video_meta=ingest.VideoNameMetadata(1, 1, 1),
            track_records=records,
            visual_vector=[0.1] * VECTOR_SIZE,
            labels_kind=ingest.DEFAULT_LABELS_KIND,
        )

        self.assertEqual(candidate.tier, "T2")
        self.assertEqual(len(candidate.vector), VECTOR_SIZE)
        self.assertEqual(candidate.metadata["window_size"], 3)

    def test_visual_t2_candidate_uses_t1_style_vector(self) -> None:
        vector = ingest.normalize_vector(np.array([0.1, 0.2, 0.3], dtype=np.float32))

        candidate = ingest.make_t2_visual_candidate(
            video_path=Path("drone1 3"),
            video_meta=ingest.VideoNameMetadata(None, None, None),
            frame_index=12,
            visual_vector=vector,
            labels_kind=ingest.DEFAULT_LABELS_KIND,
        )

        self.assertEqual(candidate.tier, "T2")
        self.assertEqual(candidate.vector, vector)
        self.assertEqual(candidate.metadata["frame"], 12)
        self.assertEqual(
            candidate.metadata["vector_layout"],
            ingest.T2_VISUAL_VECTOR_LAYOUT,
        )

    def test_fallback_selector_returns_budgeted_candidates(self) -> None:
        candidates = [
            ingest.MedoidCandidate(
                tier="T1",
                label=f"candidate-{index}",
                description="candidate",
                vector=ingest.normalize_vector(np.array([index, index + 1], dtype=np.float32)),
                thumbnail=None,
                metadata={},
            )
            for index in range(5)
        ]

        selected = ingest.select_with_fallback(tier="T1", candidates=candidates, budget=3)

        self.assertEqual(len(selected), 3)
        self.assertEqual(len({candidate.label for candidate in selected}), 3)

    def test_dino_vector_is_padded_to_512_with_reserved_slots(self) -> None:
        native = np.arange(dino_embedding.DINO_NATIVE_SIZE, dtype=np.float32)

        vector = dino_embedding.dino_to_512(native)

        self.assertEqual(len(vector), VECTOR_SIZE)
        self.assertTrue(np.any(np.array(vector[: dino_embedding.DINO_NATIVE_SIZE]) != 0))
        self.assertTrue(np.allclose(vector[dino_embedding.DINO_NATIVE_SIZE :], 0.0))
        self.assertAlmostEqual(float(np.linalg.norm(np.array(vector))), 1.0, places=5)

    def test_t1_candidate_records_dino_metadata(self) -> None:
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        fake_embedding = dino_embedding.DinoEmbeddingResult(
            vector=[0.0] * VECTOR_SIZE,
            thumbnail=None,
        )

        with patch.object(ingest, "embed_image_dinov2", return_value=fake_embedding):
            candidate = ingest.make_t1_candidate(
                video_path=Path("1.2.6"),
                video_meta=ingest.VideoNameMetadata(1, 2, 6),
                frame=frame,
                frame_index=12,
                labels_kind=ingest.DEFAULT_LABELS_KIND,
                embedder="dinov2",
            )

        self.assertEqual(candidate.metadata["embedder"], dino_embedding.DINO_MODEL_NAME)
        self.assertEqual(candidate.metadata["vector_layout"], dino_embedding.DINO_VECTOR_LAYOUT)
        self.assertEqual(len(candidate.vector), VECTOR_SIZE)


class OkutamaIngestSyntheticVideoTests(unittest.TestCase):
    def test_build_candidates_from_tiny_video_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "train" / "Videos" / "1.1.1.mp4"
            label_path = root / "train" / ingest.DEFAULT_LABELS_KIND / "1.1.1.txt"
            video_path.parent.mkdir(parents=True)
            label_path.parent.mkdir(parents=True)

            writer = cv2.VideoWriter(
                str(video_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                5.0,
                (64, 64),
            )
            for index in range(8):
                frame = np.full((64, 64, 3), index * 20, dtype=np.uint8)
                cv2.rectangle(frame, (10 + index, 10), (30 + index, 35), (255, 255, 255), -1)
                writer.write(frame)
            writer.release()

            label_path.write_text(
                "\n".join(
                    [
                        f'{track_id} {10 + frame} 10 {30 + frame} 35 {frame} 0 0 0 "Person" Running'
                        for track_id in (1, 2)
                        for frame in range(8)
                    ]
                )
            )

            candidates = ingest.build_candidates_for_video(
                video_path=video_path,
                label_path=label_path,
                labels_kind=ingest.DEFAULT_LABELS_KIND,
                frame_stride=2,
                max_frames_per_video=4,
                window_size=4,
                embedder="opencv",
            )

            self.assertGreaterEqual(len(candidates["T1"]), 1)
            self.assertGreaterEqual(len(candidates["T2"]), 1)
            self.assertGreaterEqual(len(candidates["T3"]), 1)
            for tier in ("T1", "T2", "T3"):
                for candidate in candidates[tier]:
                    self.assertEqual(len(candidate.vector), VECTOR_SIZE)

    def test_dry_run_summary_with_mocked_selector(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video_path = root / "train" / "Videos" / "1.1.1.mp4"
            label_path = root / "train" / ingest.DEFAULT_LABELS_KIND / "1.1.1.txt"
            video_path.parent.mkdir(parents=True)
            label_path.parent.mkdir(parents=True)

            writer = cv2.VideoWriter(
                str(video_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                5.0,
                (64, 64),
            )
            for index in range(6):
                writer.write(np.full((64, 64, 3), index * 30, dtype=np.uint8))
            writer.release()

            label_path.write_text(
                "\n".join(
                    [
                        f'1 8 8 32 32 {frame} 0 0 0 "Person" Walking'
                        for frame in range(6)
                    ]
                )
            )

            args = Namespace(
                dataset_root=str(root),
                split="train",
                video_glob="**/*",
                frame_glob="**/*",
                labels_kind=ingest.DEFAULT_LABELS_KIND,
                budget_t1=1,
                budget_t2=1,
                budget_t3=1,
                embedder="opencv",
                selector="fallback",
                frame_stride=2,
                max_frames_per_video=3,
                window_size=3,
                qdrant_path=str(root / "qdrant"),
                dry_run=True,
                reset=False,
            )

            def first_selector(*, candidates, budget, **_kwargs):
                return candidates[:budget]

            with patch.object(ingest, "select_with_submodlib", side_effect=first_selector):
                summary = ingest.run_ingestion(args)

            self.assertTrue(summary.dry_run)
            self.assertEqual(summary.videos_processed, 1)
            self.assertEqual(summary.upserted, 0)
            self.assertEqual(summary.selected["T1"], 1)

    def test_build_candidates_from_extracted_frame_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_dir = root / "Noon" / "Extracted-Frames-1280x720" / "1.2.6"
            label_path = root / "Noon" / ingest.DEFAULT_LABELS_KIND / "1.2.6.txt"
            frame_dir.mkdir(parents=True)
            label_path.parent.mkdir(parents=True)

            for index in range(6):
                frame = np.full((64, 64, 3), index * 30, dtype=np.uint8)
                cv2.rectangle(frame, (8 + index, 8), (32 + index, 32), (255, 255, 255), -1)
                cv2.imwrite(str(frame_dir / f"{index}.jpg"), frame)

            label_path.write_text(
                "\n".join(
                    [
                        f'1 {8 + frame} 8 {32 + frame} 32 {frame} 0 0 0 "Person" Walking'
                        for frame in range(6)
                    ]
                )
            )

            sources = ingest.discover_media_sources(root, "all", "**/*", "**/*")
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].kind, "frames")
            self.assertEqual(sources[0].stem, "1.2.6")

            found_label = ingest.find_label_file(root, sources[0], ingest.DEFAULT_LABELS_KIND)
            self.assertEqual(found_label, label_path)

            candidates = ingest.build_candidates_for_frame_dir(
                frame_dir=frame_dir,
                label_path=label_path,
                labels_kind=ingest.DEFAULT_LABELS_KIND,
                frame_stride=2,
                max_frames_per_video=3,
                window_size=3,
                embedder="opencv",
            )

            self.assertGreaterEqual(len(candidates["T1"]), 1)
            self.assertGreaterEqual(len(candidates["T2"]), 1)
            self.assertGreaterEqual(len(candidates["T3"]), 1)
            for tier in ("T1", "T2", "T3"):
                for candidate in candidates[tier]:
                    self.assertEqual(len(candidate.vector), VECTOR_SIZE)

    def test_missing_labels_frame_directory_can_build_t1_and_t2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame_dir = root / "Noon" / "Extracted-Frames-1280x720" / "1.2.6"
            frame_dir.mkdir(parents=True)

            for index in range(6):
                frame = np.full((64, 64, 3), index * 30, dtype=np.uint8)
                cv2.imwrite(str(frame_dir / f"{index}.jpg"), frame)

            args = Namespace(
                dataset_root=str(root),
                split="all",
                video_glob="**/*",
                frame_glob="**/*",
                labels_kind=ingest.DEFAULT_LABELS_KIND,
                budget_t1=1,
                budget_t2=1,
                budget_t3=1,
                embedder="opencv",
                selector="fallback",
                frame_stride=2,
                max_frames_per_video=3,
                window_size=3,
                qdrant_path=str(root / "qdrant"),
                dry_run=True,
                reset=False,
            )

            def first_selector(*, candidates, budget, **_kwargs):
                return candidates[:budget]

            with patch.object(ingest, "select_with_submodlib", side_effect=first_selector):
                summary = ingest.run_ingestion(args)

            self.assertEqual(summary.videos_discovered, 1)
            self.assertEqual(summary.videos_processed, 1)
            self.assertGreaterEqual(summary.candidates["T1"], 1)
            self.assertGreaterEqual(summary.candidates["T2"], 1)
            self.assertEqual(summary.candidates["T3"], 0)
            self.assertEqual(summary.selected["T1"], 1)
            self.assertEqual(summary.selected["T2"], 1)
            self.assertIn("built T1/T2", summary.warnings[0])

    def test_t2_submodlib_selector_uses_logdeterminant(self) -> None:
        class FakeObjective:
            def maximize(self, **_kwargs):
                return [(1, 0.5)]

        class FakeLogDeterminant:
            calls = []

            def __init__(self, **kwargs):
                self.calls.append(kwargs)

            def maximize(self, **kwargs):
                return FakeObjective().maximize(**kwargs)

        candidates = [
            ingest.MedoidCandidate(
                tier="T2",
                label=f"candidate-{index}",
                description="candidate",
                vector=ingest.normalize_vector(
                    np.array([index + 1, index + 2], dtype=np.float32)
                ),
                thumbnail=None,
                metadata={},
            )
            for index in range(3)
        ]

        imports = {
            "facility_location": object,
            "log_determinant": FakeLogDeterminant,
            "mutual_information": None,
        }

        with patch.object(ingest, "require_submodlib", return_value=imports):
            selected = ingest.select_with_submodlib(
                tier="T2",
                candidates=candidates,
                budget=1,
                selector="submodlib",
            )

        self.assertEqual([candidate.label for candidate in selected], ["candidate-1"])
        self.assertEqual(FakeLogDeterminant.calls[0]["n"], 3)
        self.assertEqual(FakeLogDeterminant.calls[0]["mode"], "dense")
        self.assertEqual(FakeLogDeterminant.calls[0]["lambdaVal"], 1.0)


if __name__ == "__main__":
    unittest.main()
