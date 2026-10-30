import { Tier, Medoid } from '../types';

/**
 * 3-Tier RAG Database Structure
 * Designed for edge deployment on Drone NPU/TPU.
 */

export const T1_SPATIAL_DB: Medoid[] = [
  { 
    id: 's-1', 
    tier: Tier.T1, 
    label: 'OKUTAMA_URBAN_S7', 
    description: 'Okutama-Action: High-density urban sector with standard pedestrian flow and vehicle occlusion zones.',
    similarity: 0.99,
    source: 'BASE',
    // 16 Intensity (0.4 avg), 8 H-Gradient (sparse), 8 V-Gradient (sparse)
    vector: [0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.7, 0.2, 0.05, 0.02, 0.01, 0, 0, 0, 0.7, 0.2, 0.05, 0.02, 0.01, 0, 0, 0]
  },
  { 
    id: 's-2', 
    tier: Tier.T1, 
    label: 'OKUTAMA_PERIMETER_WOODS', 
    description: 'Okutama-Action: Dense vegetation zone. Significant motion from wind and animals.',
    similarity: 0.95,
    source: 'BASE',
    // 16 Intensity (0.6 avg), High complexity in gradients (leaves)
    vector: [0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.3, 0.3, 0.2, 0.1, 0.05, 0.03, 0.01, 0.01, 0.3, 0.3, 0.2, 0.1, 0.05, 0.03, 0.01, 0.01]
  },
  { 
    id: 's-3', 
    tier: Tier.T1, 
    label: 'OKUTAMA_LOADING_DOCK', 
    description: 'Okutama-Action: Industrial zone with frequent truck transit and worker activity.',
    similarity: 0.98,
    source: 'BASE',
    // Variable pattern intensity
    vector: [0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.6, 0.3, 0.05, 0.02, 0.01, 0.01, 0, 0, 0.6, 0.3, 0.05, 0.02, 0.01, 0.01, 0, 0]
  },
  {
    id: 's-4',
    tier: Tier.T1,
    label: 'OKUTAMA_STATIC_INTERIOR',
    description: 'Okutama-Action: Controlled indoor environment with artificial lighting and minimal motion.',
    similarity: 0.99,
    source: 'BASE',
    vector: [0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.9, 0.1, 0, 0, 0, 0, 0, 0, 0.9, 0.1, 0, 0, 0, 0, 0, 0]
  }
];

export const T2_BEHAVIORAL_DB: Medoid[] = [
  { 
    id: 'b-1', 
    tier: Tier.T2, 
    label: 'ACTION_LOITERING', 
    description: 'Okutama-Action: Non-linear movement within a 10m radius. Low visual complexity, mostly baseline patterns.',
    similarity: 0.88,
    source: 'BASE',
    // Low intensity variance (mostly flat baseline), very low high-freq gradients
    vector: [0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.6, 0.3, 0.1, 0, 0, 0, 0, 0, 0.6, 0.3, 0.1, 0, 0, 0, 0, 0]
  },
  { 
    id: 'b-2', 
    tier: Tier.T2, 
    label: 'ACTION_PRONE_CRAWL', 
    description: 'Okutama-Action: Low-profile movement. Intensity shifted significantly to lower half of frame.',
    similarity: 0.94,
    source: 'BASE',
    // High intensity in lower 2 rows of the 4x4 grid (indices 8-15)
    vector: [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.7, 0.7, 0.7, 0.7, 0.8, 0.8, 0.8, 0.8, 0.4, 0.3, 0.2, 0.1, 0, 0, 0, 0, 0.4, 0.3, 0.2, 0.1, 0, 0, 0, 0]
  },
  { 
    id: 'b-5', 
    tier: Tier.T2, 
    label: 'ACTION_BURGLARY_PENETRATION', 
    description: 'Okutama-Action: Forced entry. High structural complexity and flickering intensity.',
    similarity: 0.95,
    source: 'BASE',
    // High variance in intensity (flashing/moving), high high-freq gradients
    vector: [0.8, 0.2, 0.8, 0.2, 0.8, 0.2, 0.8, 0.2, 0.8, 0.2, 0.8, 0.2, 0.8, 0.2, 0.8, 0.2, 0.1, 0.1, 0.2, 0.4, 0.5, 0.4, 0.2, 0.1, 0.1, 0.1, 0.2, 0.4, 0.5, 0.4, 0.2, 0.1]
  },
  {
    id: 'b-6',
    tier: Tier.T2,
    label: 'ACTION_FIGHT_VIOLENCE',
    description: 'Okutama-Action: High-velocity chaotic movement. Extreme gradient distribution across bins.',
    similarity: 0.97,
    source: 'BASE',
    // Chaotic intensity, max complexity in gradients (limb movement)
    vector: [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.05, 0.05, 0.1, 0.2, 0.4, 0.6, 0.4, 0.2, 0.05, 0.05, 0.1, 0.2, 0.4, 0.6, 0.4, 0.2]
  },
  {
    id: 'b-7',
    tier: Tier.T2,
    label: 'ACTION_ATM_BURGLARY',
    description: 'Okutama-Action: Mechanical tampering targeting ATMs. Spatially localized irregularity.',
    similarity: 0.98,
    source: 'BASE',
    // High intensity localized (indices 5, 6, 9, 10 - middle), specific high-freq peaks
    vector: [0.2, 0.2, 0.2, 0.2, 0.2, 0.9, 0.9, 0.2, 0.2, 0.9, 0.9, 0.2, 0.2, 0.2, 0.2, 0.2, 0.1, 0.1, 0.1, 0.5, 0.7, 0.5, 0.2, 0, 0.1, 0.1, 0.1, 0.5, 0.7, 0.5, 0.2, 0]
  }
];

export const T3_IDENTITY_DB: Medoid[] = [
  { 
    id: 'i-1', 
    tier: Tier.T3, 
    label: 'ENTITY_ALPHA_PRIME', 
    description: 'Okutama-Action: Authorized sector security personnel. Biometric height: 185cm.',
    similarity: 0.99,
    source: 'BASE',
    vector: Array(32).fill(0.3)
  },
  { 
    id: 'i-2', 
    tier: Tier.T3, 
    label: 'ENTITY_MAINTENANCE_BOT', 
    description: 'Okutama-Action: Automatic floor-cleaning unit. Serial: XB-90.',
    similarity: 0.97,
    source: 'BASE',
    vector: Array(32).fill(0.7)
  },
  { 
    id: 'i-3', 
    tier: Tier.T3, 
    label: 'ENTITY_UNIDENTIFIED_TACTICAL', 
    description: 'Okutama-Action: Subject matching unauthorized entry profile E-42.',
    similarity: 0.72,
    source: 'BASE',
    vector: Array(32).fill(0.5)
  }
];

export const ALL_MEDOIDS = [...T1_SPATIAL_DB, ...T2_BEHAVIORAL_DB, ...T3_IDENTITY_DB];

export const searchRAG = (tier: Tier | 'ALL') => {
  if (tier === 'ALL') return ALL_MEDOIDS;
  return ALL_MEDOIDS.filter(m => m.tier === tier);
};
