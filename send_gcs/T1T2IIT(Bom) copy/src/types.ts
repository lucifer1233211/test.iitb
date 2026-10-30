/**
 * IIT Bombay Spatio-Temporal Pipeline Types
 */

export enum Tier {
  T1 = 'TIER_1_NORMALCY',
  T2 = 'TIER_2_BEHAVIORAL',
  T3 = 'TIER_3_IDENTITY'
}

export interface CurationMetadata {
  method: string;
  samplingRate: string;
  reductionPercentage: number;
  status: 'idle' | 'running' | 'complete';
}

export interface AnomalySignal {
  id: string;
  timestamp: number;
  score: number;
  type: string;
  vector: number[];
  actionLabel?: string;
  location?: string;
  image?: string;
  mimeType?: string;
  retrievedMedoids?: string[];
}

export interface Medoid {
  id: string;
  tier: Tier;
  label: string;
  description: string;
  similarity: number;
  thumbnail?: string;
  source?: 'BASE' | 'LIVE';
  vector?: number[];
}

export interface SystemProcess {
  step: string;
  status: 'idle' | 'processing' | 'matched' | 'alert';
  detail: string;
}

/**
 * Real RAG API Contract
 */

export type RagTier = 'T1' | 'T2' | 'T3';

export type MemorySource = 'BASE' | 'LIVE';

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export interface RetrievedMedoid {
  id: string;
  tier: RagTier;
  label: string;
  description: string;
  source: MemorySource;
  similarity: number;
  payload?: Record<string, unknown>;
  thumbnail?: string;
}

export interface TierAnalysis {
  tier: RagTier;
  status: 'skipped' | 'searched' | 'matched' | 'novel' | 'empty';
  top_similarity: number | null;
  matched_medoid_id?: string;
  reason: string;
}

export interface RagQueryResult {
  signal_id: string;
  anomaly_score: number;
  is_anomaly: boolean;
  query_vector_dim: number;
  retrieved_medoids: RetrievedMedoid[];
  tier_analysis: TierAnalysis[];
  risk_level: RiskLevel;
  recommended_action: string;
  reasoning: string;
  verbose_logs: string[];
}