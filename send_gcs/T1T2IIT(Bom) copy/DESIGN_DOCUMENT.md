# IIT Bombay Spatio-Temporal Pipeline: Final Design & Roadmap

## 1. Executive Summary
The **IIT Bombay Spatio-Temporal Pipeline** is a state-of-the-art surveillance architecture designed for autonomous drones. It leverages a "Dual-Loop" cognitive architecture:
1.  **Reflex Loop (STEAD):** Onboard, real-time spatio-temporal anomaly detection.
2.  **Cortex Loop (Agentic RAG):** Contextual reasoning using hierarchical memory Tiers (Spatial, Behavioral, Identity).

This system is optimized for high-bandwidth video ingestion (4K/30FPS) while maintaining a low computational footprint by using **Submodular Distillation**.

---

## 2. System Architecture

### 2.1 Hardware Specification
- **Computing Unit:** NVIDIA Jetson Orin Nano (6-core ARM, 1024-core Ampere GPU).
- **Vision Sensor:** IMX219 (MIPI CSI-2) Global Shutter.
- **Backbone:** GStreamer / OpenCV integration.
- **Storage:** 256GB NVMe (Local Vector Indices).

### 2.2 Software Stack
- **Edge Inference:** ONNX Runtime / TensorRT.
- **Vector DB:** Qdrant (HNSW-based vector search).
- **Sampling:** Submodlib (Facility Location Optimization).
- **Messaging:** FastAPI (Local Node) + WebSockets (Ground Station Link).
- **GUI:** React 18 + Tailwind + Framer Motion.

---

## 3. Detailed Data Flow

1.  **Ingestion:** The drone captures video and fills a 30-frame buffer.
2.  **Distillation:** `Submodlib` selects the "Informative Frame" $F^*$, reducing noise.
3.  **Reflex:** The `STEAD` ONNX model computes $P(\text{anomaly} | \text{buffer})$.
4.  **Cortex:** If $P > 0.85$, the Edge Backend:
    - Embeds $F^*$ into a 512-dim vector.
    - Queries the 3-Tier RAG Registry.
    - Synthesizes a deterministic protocol (Agentic Output).
5.  **Ground Station:** Telemetry and Cortex payloads are pushed to the React dashboard via WebSockets.

---

## 4. Further Steps & Roadmap

### Phase 2: SWARM Intelligence Integration (Q3 2026)
- **Collaborative RAG:** Drones share discovered "Medoids" (anomalous anchors) in real-time. If Drone A detects a suspicious "Action", Drone B updates its local T2 Behavioral DB to watch for similar patterns.
- **Cross-View Triangulation:** Synchronize Cortex agents to provide 3D localized reasoning for the same identity across multiple drones.

### Phase 3: Autonomous Neural Re-Planning (Q4 2026)
- **Closed Loop MAVLink:** The Cortex will no longer just "Suggest" an action; it will directly modify the PX4 flight path. 
- **Example:** If $P(\text{anomaly}) > 0.95$, the Agent triggers an automatic "ORBIT_TARGET" command sent via MAVProxy.

### Phase 4: Federated Model Updates (Q1 2027)
- **Continuous Learning:** Implement on-drone fine-tuning of the STEAD Reflex model.
- **Mechanism:** Human feedback from the Ground Station ("Correct" vs "False Positive") is stored on the drone and used for periodic local gradient updates during charging cycles.

---

## 5. Deployment & Setup Instructions

### Backend (Drone Node)
1.  **Repository Setup:**
    ```bash
    git clone [repo_url]
    cd drone_backend
    pip install -r requirements.txt
    ```
2.  **Initialize DB:**
    ```bash
    python qdrant_setup.py
    ```
3.  **Launch Edge Services:**
    ```bash
    # Terminal 1
    python main.py
    # Terminal 2
    python ingestion.py
    ```

### Frontend (Ground Control Station)
1.  **Install Node Modules:**
    ```bash
    npm install
    ```
2.  **Configure Environment:**
    Set `VITE_DRONE_IP` in `.env` to the drone's actual IP address.
3.  **Start Dashboard:**
    ```bash
    npm run dev
    ```

---

## 6. Porting Checklist
- [ ] Update `rtsp_url` in `ingestion.py` to match MIPI CSI stream.
- [ ] Export PyTorch weights to `models/stead_mobile_v1.onnx`.
- [ ] Verify NVMe write speeds for Qdrant collection stability.
- [ ] Calibrate STEAD Threshold (0.85) against baseline sector data.

**Document Status:** Version 1.2 (IIT Bombay Project Group)
