# IIT Bombay: Spatio-Temporal Agentic Surveillance
## STEAD-Cortex Technical Architecture & Blueprint

### 1. System Philosophy
The system is split into two cognitive loops:
- **The Reflex (Edge):** Low-latency, high-frequency spatio-temporal change detection (STEAD). It runs onboard the drone to filter noise and detect anomalies.
- **The Cortex (Agentic):** High-level reasoning that synthesizes "Reflex" signals with historical data (RAG) to determine intent and ROI (Risk of Incident).

---

### 2. Multi-Modal 3-Tier RAG Structure
To work on a drone with limited memory, the RAG is partitioned:

| Tier | Name | Engine | Data Type | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **T1** | **Spatial** | HNSW Index | Latent Embeddings | Is this place normal? (Geofencing/Baseline) |
| **T2** | **Behavioral** | Submodlib | Temporal Vectors | Is this movement normal? (Loitering/Aggression) |
| **T3** | **Identity** | Relational DB | Entity Schemata | Is this person/object known? (Whitelist/Blacklist) |

---

### 3. The Ingestion Pipeline (Drone-Side)
1.  **Capture:** 4K RTSP stream @ 30FPS via GStreamer.
2.  **Distillation (Submodlib):** Every 30 frames ($ \sim $1 second), the pipeline performs **Facility Location Optimization** (Submodlib) to select the single most representative frame. This reduces cognitive load on the Cortex by 97% while preserving high-entropy events.
3.  **Reflex Scoring (STEAD):** A spatio-temporal ONNX model (exported from PyTorch) analyzes the entire 30-frame temporal window to detect out-of-distribution patterns. It generates a "Surprise Score" [0.0 - 1.0].
4.  **Trigger:** If Score > Threshold (default 0.85), the "Informative Frame" and its temporal context are transmitted to the **Cortex Agent**.

---

### 4. Agentic Framework (The Decision Logic)
The Agent behaves as an orchestrator:
- **Condition:** Anomaly Detected.
- **Action 1:** Query T1 (Check geography).
- **Action 2:** Query T2 (Check behavioral history).
- **Metadata Fusion:** Combine scores into a prompt/context.
- **Execution:** 
    - *Online:* Forward to Gemini-1.5-Flash for complex "Curation" and "Intent Analysis".
    - *Offline:* Forward to Local Gemma-2B for deterministic protocol execution (e.g., "Return to Home", "Follow Target").

---

### 5. Deployment Specs
- **Hardware:** Jetson Orin Nano / Xavier NX (Drone) + Ground Station (Laptop/Tablet).
- **Transport:** MAVLink (Telemetry) + WebRTC (Video) + MQTT (Event Logs).
- **Storage:** Qdrant (Vector Store) on NVMe SSD.
- **Frameworks:** React (Frontend), FastAPI (Middle-tier), PyTorch (Inference).
