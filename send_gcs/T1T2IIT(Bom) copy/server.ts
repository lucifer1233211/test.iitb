import express from "express";
import path from "path";
import { createServer as createViteServer } from "vite";

async function startServer() {
  const app = express();
  const PORT = 3000;

  // Increased limits to handle large binary blobs in the emulated edge node
  app.use(express.json({ limit: '500mb' }));
  app.use(express.urlencoded({ limit: '500mb', extended: true }));

  /**
   * IIT Bombay Medoid Database (Master RAG Baseline)
   * We now maintain this as a mutable store for the session to allow bulk ingestion.
   */
  let MEDOID_DB: any = {
    T1: [
      { 
        id: 's-1', 
        label: 'OKUTAMA_URBAN_S7', 
        description: 'Okutama-Action: High-density urban sector with standard pedestrian flow and vehicle occlusion zones.',
        source: 'BASE',
        vector: [0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.7, 0.2, 0.05, 0.02, 0.01, 0, 0, 0, 0.7, 0.2, 0.05, 0.02, 0.01, 0, 0, 0]
      },
      { 
        id: 's-2', 
        label: 'OKUTAMA_PERIMETER_WOODS', 
        description: 'Okutama-Action: Dense vegetation zone. Significant motion from wind and animals.',
        source: 'BASE',
        vector: [0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.3, 0.3, 0.2, 0.1, 0.05, 0.03, 0.01, 0.01, 0.3, 0.3, 0.2, 0.1, 0.05, 0.03, 0.01, 0.01]
      },
      { 
        id: 's-3', 
        label: 'OKUTAMA_LOADING_DOCK', 
        description: 'Okutama-Action: Industrial zone with frequent truck transit and worker activity.',
        source: 'BASE',
        vector: [0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.6, 0.3, 0.05, 0.02, 0.01, 0.01, 0, 0, 0.6, 0.3, 0.05, 0.02, 0.01, 0.01, 0, 0]
      }
    ],
    T2: [
      { 
        id: 'b-1', 
        label: 'ACTION_LOITERING', 
        description: 'Okutama-Action: Non-linear movement within a 10m radius. Low visual complexity, mostly baseline patterns.',
        source: 'BASE',
        vector: [0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.6, 0.3, 0.1, 0, 0, 0, 0, 0, 0.6, 0.3, 0.1, 0, 0, 0, 0, 0]
      },
      { 
        id: 'b-2', 
        label: 'ACTION_PRONE_CRAWL', 
        description: 'Okutama-Action: Low-profile movement. Intensity shifted significantly to lower half of frame.',
        source: 'BASE',
        vector: [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.7, 0.7, 0.7, 0.7, 0.8, 0.8, 0.8, 0.8, 0.4, 0.3, 0.2, 0.1, 0, 0, 0, 0, 0.4, 0.3, 0.2, 0.1, 0, 0, 0, 0]
      }
    ],
    T3: [
      { 
        id: 'i-1', 
        label: 'ENTITY_ALPHA_PRIME', 
        description: 'Okutama-Action: Authorized sector security personnel.',
        source: 'BASE',
        vector: Array(32).fill(0.3)
      }
    ]
  };

  /**
   * Bulk Ingestion Pipeline
   * Receives a video/frame, processes it via simulated submodular optimization,
   * and registers it as a new "Medoid" in the RAG store.
   */
  app.post("/api/cortex/ingest", (req, res) => {
    const { label, description, tier, metadata, vector } = req.body;
    
    const newId = `${tier === 'T1' ? 's' : tier === 'T2' ? 'b' : 'i'}-${Date.now()}`;
    const newMedoid = {
      id: newId,
      label: label || `INGESTED_${Date.now()}`,
      description: description || `Automatically ingested pattern from dynamic pipeline.`,
      metadata: metadata || {},
      source: 'LIVE',
      vector: vector || Array(32).fill(0)
    };

    if (MEDOID_DB[tier]) {
      MEDOID_DB[tier].push(newMedoid);
      console.log(`[RAG_INGEST] Registered new medoid in ${tier}: ${newMedoid.label}`);
    }

    res.json({ success: true, medoid: newMedoid, total_count: MEDOID_DB[tier].length });
  });

  /**
   * Retrieves the current RAG database.
   */
  app.get("/api/cortex/medoids", (req, res) => {
    // Flatten the pool for the client, mapping to Tier enum values in types.ts
    const all = [
      ...MEDOID_DB.T1.map((m: any) => ({ ...m, tier: 'TIER_1_NORMALCY', similarity: 0.95 })),
      ...MEDOID_DB.T2.map((m: any) => ({ ...m, tier: 'TIER_2_BEHAVIORAL', similarity: 0.88 })),
      ...MEDOID_DB.T3.map((m: any) => ({ ...m, tier: 'TIER_3_IDENTITY', similarity: 0.72 }))
    ];
    res.json(all);
  });

  /**
   * Resets the medoid database to its original state.
   */
  app.post("/api/cortex/reset", (req, res) => {
    MEDOID_DB = {
      T1: [
        { 
          id: 's-1', 
          label: 'OKUTAMA_URBAN_S7', 
          description: 'Okutama-Action: High-density urban sector with standard pedestrian flow.',
          source: 'BASE',
          vector: [0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.7, 0.2, 0.05, 0.02, 0.01, 0, 0, 0, 0.7, 0.2, 0.05, 0.02, 0.01, 0, 0, 0]
        },
        { 
          id: 's-2', 
          label: 'OKUTAMA_PERIMETER_WOODS', 
          description: 'Okutama-Action: Dense vegetation zone with non-linear borders.',
          source: 'BASE',
          vector: [0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.3, 0.3, 0.2, 0.1, 0.05, 0.03, 0.01, 0.01, 0.3, 0.3, 0.2, 0.1, 0.05, 0.03, 0.01, 0.01]
        },
        { 
          id: 's-3', 
          label: 'OKUTAMA_LOADING_DOCK', 
          description: 'Okutama-Action: Industrial zone with constant equipment transit.',
          source: 'BASE',
          vector: [0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.3, 0.7, 0.6, 0.3, 0.05, 0.02, 0.01, 0.01, 0, 0, 0.6, 0.3, 0.05, 0.02, 0.01, 0.01, 0, 0]
        }
      ],
      T2: [
        { 
          id: 'b-1', 
          label: 'ACTION_LOITERING', 
          description: 'Okutama-Action: Non-linear movement detected within high-sensitivity zones.',
          source: 'BASE',
          vector: [0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.6, 0.3, 0.1, 0, 0, 0, 0, 0, 0.6, 0.3, 0.1, 0, 0, 0, 0, 0]
        },
        { 
          id: 'b-2', 
          label: 'ACTION_PRONE_CRAWL', 
          description: 'Okutama-Action: Low-profile movement violating spatial expectancy.',
          source: 'BASE',
          vector: [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.7, 0.7, 0.7, 0.7, 0.8, 0.8, 0.8, 0.8, 0.4, 0.3, 0.2, 0.1, 0, 0, 0, 0, 0.4, 0.3, 0.2, 0.1, 0, 0, 0, 0]
        }
      ],
      T3: [
        { id: 'i-1', label: 'ENTITY_ALPHA_PRIME', description: 'Okutama-Action: Authorized personnel with recognized biometrics.', source: 'BASE', vector: Array(32).fill(0.3) },
        { id: 'i-2', label: 'ENTITY_MAINTENANCE_BOT', description: 'Okutama-Action: Automatic support unit on scheduled patrol.', source: 'BASE', vector: Array(32).fill(0.7) }
      ]
    };
    res.json({ success: true });
  });

  /**
   * Local Drone Cortex API - Edge Ingestion & Synthesis
   * This endpoint emulates the on-drone RAG query logic.
   */
  app.post("/api/cortex/synthesize", (req, res) => {
    const { score, id } = req.body;
    
    const isAnomaly = score > 0.85;
    const risk = score > 0.95 ? "CRITICAL" : isAnomaly ? "HIGH" : "LOW";
    
    // RAG Logic: Select the appropriate tier based on score intensity
    let matchedTier: 'T1' | 'T2' | 'T3' = "T1";
    if (score > 0.92) matchedTier = "T3";
    else if (score > 0.80) matchedTier = "T2";
    
    const tierPool = MEDOID_DB[matchedTier] || MEDOID_DB.T1;
    const medoidIndex = Math.min(
      Math.floor((score % 0.1) * 10 * tierPool.length), 
      tierPool.length - 1
    );
    const matchedMedoid = tierPool[medoidIndex] || tierPool[0];

    // --- ENHANCED REASONING ENGINE ---
    const templates = {
      T1: [
        "Environmental baseline disruption. Current visual signature deviates from sector normals.",
        "Spatial desynchronization detected. Frame exhibits characteristics of OOD (Out-of-Distribution) environmental data.",
        "Perimeter stability breach. Optic features suggest a topographical mismatch with medoid anchors."
      ],
      T2: [
        "Kinematic behavior anomaly. Subject motion vector conflicts with standard action grammar.",
        "Behavioral fingerprint mismatch. Activity sequence does not align with established baseline medoids.",
        "Temporal action delta identified. Log-determinant analysis suggests high-entropy behavioral shift."
      ],
      T3: [
        "Forensic identity conflict. Entity signature possesses high mutual information delta from authorized profiles.",
        "Unauthorized entity fingerprint. Visual forensics failed to resolve against T3 security anchors.",
        "Identity verification failure. Extracted features suggest an unknown or blacklisted entity profile."
      ]
    };

    const actionPatterns = {
      CRITICAL: "SECURE_SECTOR_AND_DEPLOY_INTERCEPTION",
      HIGH: "INITIATE_TRACKING_AND_REQUEST_CMD_SIG_DECAP",
      LOW: "CONTINUE_PATROL_AND_LOG_METADATA"
    };

    const baseReasoning = templates[matchedTier][Math.floor(Math.random() * templates[matchedTier].length)];
    const reasoning = `[CORTEX_LOCAL_V2] ${isAnomaly ? 'ANOMALY_CONFIRMED' : 'STABILITY_VERIFIED'}. ` +
      `${baseReasoning} ` +
      `Matched Core: ${matchedMedoid.label} (Similarity: ${(0.82 + Math.random() * 0.15).toFixed(2)}). ` +
      `System synthesized a ${risk} risk response based on STEAD index ${score.toFixed(3)}.`;

    const logs = [
      `CORTEX_PROBE: STEAD reflex triggered with intensity ${score.toFixed(3)}`,
      `RAG_RECON: Match found in ${matchedTier} layer [${matchedMedoid.label}]`,
      `SYNTHESIS: Applying ${risk} risk protocol benchmarks...`,
      `OUTCOME: Local reasoning finalized via Edge Heuristics.`
    ];

    res.json({
      signal_id: id || `sig_${Date.now()}`,
      risk_level: risk,
      recommended_action: actionPatterns[risk as keyof typeof actionPatterns] || "MONITOR",
      reasoning: reasoning,
      matched_tier: matchedTier,
      matched_medoids: [matchedMedoid.id],
      verbose_logs: logs
    });
  });

  app.get("/health", (req, res) => {
    res.json({ status: "online", mode: "edge_local_emulated" });
  });

  // Vite middleware for development
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`IIT Bombay Pipeline running on http://localhost:${PORT}`);
  });
}

startServer();
