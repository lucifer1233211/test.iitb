from typing import Any, Literal

from pydantic import BaseModel, Field


RagTier = Literal["T1", "T2", "T3"]
MemorySource = Literal["BASE", "LIVE"]
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class RetrievedMedoid(BaseModel):
    id: str
    tier: RagTier
    label: str
    description: str
    source: MemorySource
    similarity: float = Field(ge=0.0, le=1.0)
    payload: dict[str, Any] = Field(default_factory=dict)
    thumbnail: str | None = None


class TierAnalysis(BaseModel):
    tier: RagTier
    status: Literal["skipped", "searched", "matched", "novel", "empty"]
    top_similarity: float | None = None
    matched_medoid_id: str | None = None
    reason: str


class RagQueryResult(BaseModel):
    signal_id: str
    anomaly_score: float = Field(ge=0.0, le=1.0)
    is_anomaly: bool
    query_vector_dim: int
    retrieved_medoids: list[RetrievedMedoid]
    tier_analysis: list[TierAnalysis]
    risk_level: RiskLevel
    recommended_action: str
    reasoning: str
    verbose_logs: list[str] = Field(default_factory=list)