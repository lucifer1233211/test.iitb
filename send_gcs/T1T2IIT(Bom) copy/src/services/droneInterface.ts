/**
 * IIT Bombay Drone Interface Service
 * Used to communicate with the local Edge node running on the drone.
 */

// In this environment, we proxy the drone API through our main Express server
import { Tier, type Medoid, type RagQueryResult, type RagTier } from '../types';

const DRONE_API_BASE = import.meta.env.VITE_DRONE_API_BASE || "http://127.0.0.1:8001";

export type DroneProcessingResult = RagQueryResult & {
  matched_tier?: string;
  matched_medoids?: string[];
  score?: number;
  verbose_logs?: string[];
};

export interface IngestionParams {
  label: string;
  description: string;
  tier: 'T1' | 'T2' | 'T3';
  metadata?: any;
  vector?: number[];
  image_base64?: string;
  embedder?: 'opencv' | 'dinov2';
}

function toFrontendTier(tier: RagTier | string): Tier {
  if (tier === 'T1' || tier === Tier.T1) return Tier.T1;
  if (tier === 'T2' || tier === Tier.T2) return Tier.T2;
  return Tier.T3;
}

function toApiTier(tier: 'T1' | 'T2' | 'T3' | Tier): 'T1' | 'T2' | 'T3' {
  if (tier === Tier.T1 || tier === 'T1') return 'T1';
  if (tier === Tier.T2 || tier === 'T2') return 'T2';
  return 'T3';
}

function mapMedoid(record: any): Medoid {
  return {
    id: record.id,
    tier: toFrontendTier(record.tier),
    label: record.label,
    description: record.description || '',
    similarity: record.similarity ?? 1,
    thumbnail: record.thumbnail,
    source: record.source,
    vector: record.vector,
    payload: record.payload,
  } as Medoid;
}

/**
 * Registers a new pattern/video in the local RAG database.
 */
export async function ingestToRAG(params: IngestionParams): Promise<boolean> {
  try {
    const response = await fetch(`${DRONE_API_BASE}/api/rag/ingest`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...params,
        tier: toApiTier(params.tier),
        embedder: params.embedder || 'opencv',
      }),
    });

    if (!response.ok) throw new Error("Ingestion failed");
    return true;
  } catch (error) {
    console.error("Ingestion Error:", error);
    return false;
  }
}

/**
 * Fetches the current RAG medoids from the edge node.
 */
export async function getMedoids(): Promise<any[]> {
  try {
    const response = await fetch(`${DRONE_API_BASE}/api/rag/medoids`);
    if (!response.ok) throw new Error("Failed to fetch medoids");
    const records = await response.json();
    return records.map(mapMedoid);
  } catch (error) {
    console.error("Error fetching medoids:", error);
    return [];
  }
}

/**
 * Resets the RAG database on the edge node.
 */
export async function resetRAG(): Promise<boolean> {
  try {
    const response = await fetch(`${DRONE_API_BASE}/api/rag/reset`, { method: "POST" });
    return response.ok;
  } catch (error) {
    console.error("Error resetting RAG:", error);
    return false;
  }
}

/**
 * Sends a captured frame to the local Cortex node on the drone.
 */
export async function queryDroneCortex(frameBase64: string, score: number, forceRagLookup = false): Promise<DroneProcessingResult> {
  try {
    const response = await fetch(`${DRONE_API_BASE}/api/cortex/synthesize`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        signal_id: `gs_trigger_${Date.now()}`,
        score: score,
        image_base64: frameBase64,
        embedder: "dinov2",
        force_rag_lookup: forceRagLookup,
        metadata: {
          timestamp: Date.now() / 1000,
          source: "frontend_upload",
        },
      }),
    });

    if (!response.ok) {
      throw new Error(`Drone Node responded with ${response.status}`);
    }

    return await response.json();
  } catch (error) {
    console.error("Critical Drone Connection Error:", error);
    throw error;
  }
}

/**
 * Health check for the on-drone backend.
 */
export async function getDroneStatus(): Promise<{ status: string; mode: string }> {
  const response = await fetch(`${DRONE_API_BASE}/health`);
  return await response.json();
}
