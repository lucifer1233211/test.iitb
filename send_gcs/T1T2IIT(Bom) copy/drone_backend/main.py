from __future__ import annotations

from typing import Any, Literal
import time
import uuid

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from qdrant_client.http import models

from contracts import RagQueryResult, RetrievedMedoid, TierAnalysis
from dino_embedding import DINO_MODEL_NAME, DINO_VECTOR_LAYOUT, embed_image_dinov2
from embedding import VECTOR_SIZE, decode_base64_image, embed_base64_image, zero_vector


app = FastAPI(title="IIT Bombay - Drone RAG Edge Node")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

COLLECTION_NAME = "stead_medoids"
DEFAULT_ANOMALY_THRESHOLD = 0.85
TOP_K_PER_TIER = 3
MEDOID_LIST_LIMIT = 500

TIER_THRESHOLDS = {
    "T1": 0.70,
    "T2": 0.75,
    "T3": 0.80,
}

client: QdrantClient | None = None


def get_qdrant() -> QdrantClient | None:
    global client

    if client is None:
        try:
            client = QdrantClient(path="local_qdrant_db")
        except Exception as exc:
            print(f"[QDRANT] Local store unavailable: {exc}")
            return None

    return client


def vector_config() -> models.VectorParams:
    return models.VectorParams(
        size=VECTOR_SIZE,
        distance=models.Distance.COSINE,
    )


def ensure_collection(qdrant: QdrantClient) -> None:
    collections = qdrant.get_collections().collections
    collection_names = {collection.name for collection in collections}

    if COLLECTION_NAME in collection_names:
        return

    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=vector_config(),
    )


def recreate_collection(qdrant: QdrantClient) -> None:
    collections = qdrant.get_collections().collections
    collection_names = {collection.name for collection in collections}
    if COLLECTION_NAME in collection_names:
        qdrant.delete_collection(collection_name=COLLECTION_NAME)

    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=vector_config(),
    )


def clamp_similarity(score: float) -> float:
    return max(0.0, min(1.0, float(score)))


def build_tier_filter(tier: Literal["T1", "T2", "T3"]) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(
                key="tier",
                match=models.MatchValue(value=tier),
            )
        ]
    )


class RagIngestRequest(BaseModel):
    label: str
    description: str
    tier: Literal["T1", "T2", "T3"]
    source: Literal["BASE", "LIVE"] = "LIVE"
    metadata: dict[str, Any] = Field(default_factory=dict)
    vector: list[float] | None = None
    thumbnail: str | None = None
    image_base64: str | None = None
    embedder: Literal["opencv", "dinov2"] = "opencv"


class RagQueryRequest(BaseModel):
    signal_id: str | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    vector: list[float] | None = None
    mode: Literal["local", "gemini"] = "local"
    anomaly_threshold: float = Field(default=DEFAULT_ANOMALY_THRESHOLD, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    image_base64: str | None = None
    embedder: Literal["opencv", "dinov2"] = "opencv"
    force_rag_lookup: bool = False


def embed_request_image(image_base64: str, embedder: Literal["opencv", "dinov2"]):
    if embedder == "dinov2":
        image = decode_base64_image(image_base64)
        return embed_image_dinov2(image)

    return embed_base64_image(image_base64)


def embedder_metadata(embedder: Literal["opencv", "dinov2"]) -> dict[str, str]:
    if embedder == "dinov2":
        return {
            "embedder": DINO_MODEL_NAME,
            "vector_layout": DINO_VECTOR_LAYOUT,
        }

    return {
        "embedder": "opencv",
        "vector_layout": "opencv_features_512",
    }


def build_medoid_payload(
    *,
    medoid_id: str,
    request: RagIngestRequest,
    thumbnail: str | None,
) -> dict[str, Any]:
    return {
        "id": medoid_id,
        "tier": request.tier,
        "label": request.label,
        "description": request.description,
        "source": request.source,
        "thumbnail": thumbnail,
        "metadata": request.metadata,
        "created_at": time.time(),
    }


def point_to_retrieved_medoid(
    point: Any,
    fallback_tier: Literal["T1", "T2", "T3"],
) -> RetrievedMedoid:
    payload = point.payload or {}

    return RetrievedMedoid(
        id=str(payload.get("id", point.id)),
        tier=payload.get("tier", fallback_tier),
        label=payload.get("label", "UNKNOWN_MEDOID"),
        description=payload.get("description", ""),
        source=payload.get("source", "LIVE"),
        similarity=clamp_similarity(point.score),
        payload=payload,
        thumbnail=payload.get("thumbnail"),
    )



def record_to_medoid(record: Any) -> dict[str, Any]:
    payload = record.payload or {}

    return {
        "id": str(payload.get("id", record.id)),
        "tier": payload.get("tier", "T1"),
        "label": payload.get("label", "UNKNOWN_MEDOID"),
        "description": payload.get("description", ""),
        "source": payload.get("source", "LIVE"),
        "similarity": 1.0,
        "thumbnail": payload.get("thumbnail"),
        "payload": payload,
        "point_id": str(record.id),
    }



def get_medoid_count(qdrant: QdrantClient) -> int:
    ensure_collection(qdrant)
    return int(qdrant.count(collection_name=COLLECTION_NAME, exact=True).count)


def search_tier(
    *,
    qdrant: QdrantClient,
    tier: Literal["T1", "T2", "T3"],
    query_vector: list[float],
) -> list[RetrievedMedoid]:
    if hasattr(qdrant, "query_points"):
        response = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=build_tier_filter(tier),
            limit=TOP_K_PER_TIER,
            with_payload=True,
            with_vectors=False,
        )
        points = response.points
    else:
        points = qdrant.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            query_filter=build_tier_filter(tier),
            limit=TOP_K_PER_TIER,
            with_payload=True,
            with_vectors=False,
        )

    return [
        point_to_retrieved_medoid(point, tier)
        for point in points
    ]



def build_tier_analysis(
    *,
    tier: Literal["T1", "T2", "T3"],
    results: list[RetrievedMedoid],
) -> TierAnalysis:
    if not results:
        return TierAnalysis(
            tier=tier,
            status="empty",
            top_similarity=None,
            reason=f"No medoids found in {tier}.",
        )

    top_result = results[0]
    threshold = TIER_THRESHOLDS[tier]
    matched = top_result.similarity >= threshold

    return TierAnalysis(
        tier=tier,
        status="matched" if matched else "novel",
        top_similarity=top_result.similarity,
        matched_medoid_id=top_result.id if matched else None,
        reason=(
            f"Top {tier} match {top_result.label} scored {top_result.similarity:.3f}."
            if matched
            else f"Top {tier} score {top_result.similarity:.3f} is below threshold {threshold:.3f}."
        ),
    )


@app.get("/health")
def health_check() -> dict[str, Any]:
    qdrant = get_qdrant()
    medoid_count = get_medoid_count(qdrant) if qdrant else 0

    return {
        "status": "online",
        "mode": "edge_rag",
        "qdrant": "connected" if qdrant else "unavailable",
        "collection": COLLECTION_NAME,
        "vector_size": VECTOR_SIZE,
        "medoid_count": medoid_count,
    }


@app.post("/api/rag/ingest")
def ingest_rag(request: RagIngestRequest) -> dict[str, Any]:
    qdrant = get_qdrant()

    if qdrant is None:
        return {
            "success": False,
            "error": "Qdrant is unavailable",
        }

    embedding = embed_request_image(request.image_base64, request.embedder) if request.image_base64 else None
    vector = request.vector or (embedding.vector if embedding else zero_vector())
    thumbnail = request.thumbnail or (embedding.thumbnail if embedding else None)

    if len(vector) != VECTOR_SIZE:
        return {
            "success": False,
            "error": f"Expected vector size {VECTOR_SIZE}, received {len(vector)}",
        }

    ensure_collection(qdrant)

    point_id = str(uuid.uuid4())
    medoid_id = f"{request.tier.lower()}-{point_id[:12]}"
    request.metadata.update(embedder_metadata(request.embedder))
    payload = build_medoid_payload(
        medoid_id=medoid_id,
        request=request,
        thumbnail=thumbnail,
    )

    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            models.PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )
        ],
    )

    return {
        "success": True,
        "medoid": payload,
        "point_id": point_id,
        "vector_dim": len(vector),
    }


@app.post("/api/rag/query")
def query_rag(request: RagQueryRequest) -> RagQueryResult:
    signal_id = request.signal_id or f"sig_{int(time.time())}"
    anomaly_score = request.score if request.score is not None else 0.0
    is_anomaly = anomaly_score >= request.anomaly_threshold
    should_search_rag = is_anomaly or request.force_rag_lookup

    embedding = embed_request_image(request.image_base64, request.embedder) if request.image_base64 else None
    query_vector = request.vector or (embedding.vector if embedding else zero_vector())

    if len(query_vector) != VECTOR_SIZE:
        return RagQueryResult(
            signal_id=signal_id,
            anomaly_score=anomaly_score,
            is_anomaly=is_anomaly,
            query_vector_dim=len(query_vector),
            retrieved_medoids=[],
            tier_analysis=[
                TierAnalysis(
                    tier="T1",
                    status="skipped",
                    top_similarity=None,
                    reason=f"Invalid query vector size: expected {VECTOR_SIZE}, received {len(query_vector)}.",
                )
            ],
            risk_level="LOW",
            recommended_action="REJECT_QUERY_VECTOR",
            reasoning="Query rejected because vector dimension does not match the RAG index.",
            verbose_logs=[
                "RAG_API: Query rejected.",
                f"VECTOR_DIM_ERROR: expected={VECTOR_SIZE}, received={len(query_vector)}",
            ],
        )

    if not should_search_rag:
        return RagQueryResult(
            signal_id=signal_id,
            anomaly_score=anomaly_score,
            is_anomaly=False,
            query_vector_dim=len(query_vector),
            retrieved_medoids=[],
            tier_analysis=[
                TierAnalysis(
                    tier="T1",
                    status="skipped",
                    top_similarity=None,
                    reason="Signal is below anomaly threshold; retrieval skipped to save compute.",
                ),
                TierAnalysis(
                    tier="T2",
                    status="skipped",
                    top_similarity=None,
                    reason="Signal is below anomaly threshold; behavior retrieval skipped.",
                ),
                TierAnalysis(
                    tier="T3",
                    status="skipped",
                    top_similarity=None,
                    reason="Signal is below anomaly threshold; identity retrieval skipped.",
                ),
            ],
            risk_level="LOW",
            recommended_action="MAINTAIN_PATROL_AND_LOG",
            reasoning=(
                f"[RAG_BACKEND] Signal {signal_id} scored {anomaly_score:.3f}, "
                f"below threshold {request.anomaly_threshold:.3f}. Retrieval skipped."
            ),
            verbose_logs=[
                "RAG_API: Query request accepted.",
                f"STEAD_GATE: anomaly_score={anomaly_score:.3f}",
                "RAG_SKIP: Below anomaly threshold.",
                f"MODE: {request.mode}",
                f"EMBEDDER: {request.embedder}",
            ],
        )

    qdrant = get_qdrant()

    if qdrant is None:
        return RagQueryResult(
            signal_id=signal_id,
            anomaly_score=anomaly_score,
            is_anomaly=True,
            query_vector_dim=len(query_vector),
            retrieved_medoids=[],
            tier_analysis=[
                TierAnalysis(
                    tier="T1",
                    status="empty",
                    top_similarity=None,
                    reason="Qdrant is unavailable; retrieval could not run.",
                ),
                TierAnalysis(
                    tier="T2",
                    status="empty",
                    top_similarity=None,
                    reason="Qdrant is unavailable; retrieval could not run.",
                ),
                TierAnalysis(
                    tier="T3",
                    status="empty",
                    top_similarity=None,
                    reason="Qdrant is unavailable; retrieval could not run.",
                ),
            ],
            risk_level="HIGH",
            recommended_action="ALERT_GROUND_STATION_AND_TRACK",
            reasoning="Anomaly detected, but RAG memory store is unavailable.",
            verbose_logs=[
                "RAG_API: Query request accepted.",
                "QDRANT_ERROR: unavailable.",
                *(
                    ["RAG_FORCE: Frontend anomaly decision requested retrieval."]
                    if request.force_rag_lookup and not is_anomaly
                    else []
                ),
            ],
        )

    ensure_collection(qdrant)

    retrieved_medoids: list[RetrievedMedoid] = []
    tier_analysis: list[TierAnalysis] = []

    for tier in ("T1", "T2", "T3"):
        tier_results = search_tier(
            qdrant=qdrant,
            tier=tier,
            query_vector=query_vector,
        )
        retrieved_medoids.extend(tier_results)
        tier_analysis.append(
            build_tier_analysis(
                tier=tier,
                results=tier_results,
            )
        )

    matched_tiers = [
        analysis.tier
        for analysis in tier_analysis
        if analysis.status == "matched"
    ]

    risk_level = "HIGH" if matched_tiers else "MEDIUM"
    recommended_action = (
        "ALERT_GROUND_STATION_AND_TRACK"
        if matched_tiers
        else "ESCALATE_FOR_OPERATOR_REVIEW"
    )

    reasoning = (
        f"[RAG_BACKEND] Signal {signal_id} scored {anomaly_score:.3f}. "
        f"Retrieved {len(retrieved_medoids)} medoids across T1/T2/T3. "
        f"Matched tiers: {', '.join(matched_tiers) if matched_tiers else 'none'}."
    )

    return RagQueryResult(
        signal_id=signal_id,
        anomaly_score=anomaly_score,
        is_anomaly=is_anomaly,
        query_vector_dim=len(query_vector),
        retrieved_medoids=retrieved_medoids,
        tier_analysis=tier_analysis,
        risk_level=risk_level,
        recommended_action=recommended_action,
        reasoning=reasoning,
        verbose_logs=[
            "RAG_API: Query request accepted.",
            f"STEAD_GATE: anomaly_score={anomaly_score:.3f}",
            *(
                ["RAG_FORCE: Frontend anomaly decision requested retrieval."]
                if request.force_rag_lookup and not is_anomaly
                else []
            ),
            f"VECTOR_DIM: {len(query_vector)}",
            f"RAG_RETRIEVED: {len(retrieved_medoids)} medoids",
            f"MODE: {request.mode}",
            f"EMBEDDER: {request.embedder}",
        ],
    )


@app.get("/api/rag/medoids")
def list_medoids() -> list[dict[str, Any]]:
    qdrant = get_qdrant()

    if qdrant is None:
        return []

    ensure_collection(qdrant)

    records, _ = qdrant.scroll(
        collection_name=COLLECTION_NAME,
        limit=MEDOID_LIST_LIMIT,
        with_payload=True,
        with_vectors=False,
    )

    return [record_to_medoid(record) for record in records]


@app.post("/api/rag/reset")
def reset_rag() -> dict[str, Any]:
    qdrant = get_qdrant()

    if qdrant is None:
        return {
            "success": False,
            "error": "Qdrant is unavailable",
        }

    recreate_collection(qdrant)

    return {
        "success": True,
        "message": "RAG collection reset successfully.",
        "collection": COLLECTION_NAME,
        "medoid_count": get_medoid_count(qdrant),
    }


@app.post("/api/cortex/synthesize")
def synthesize_cortex(request: RagQueryRequest) -> RagQueryResult:
    return query_rag(request)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
