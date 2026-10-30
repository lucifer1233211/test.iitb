# IIT Bombay STEAD-Cortex Drone Porting & Deployment Guide

This guide details the system architecture of the current prototype and provides comprehensive instructions on porting the data ingestion, backend services, and the React Ground Station application to a production-grade drone and ground-control environment.

## 1. Detailed System Architecture

### The Concept
The STEAD-Cortex is a spatio-temporal predictive surveillance system designed to operate on autonomous drones in air-gapped or network-constrained environments. It addresses the massive computational overhead of continuous video surveillance by splitting processing into a **Reflex** (low-fidelity, fast) and a **Cortex** (high-fidelity, reasoning).

### The Ingestion Pipeline (The Reflex)
1. **RTSP Stream:** High-resolution video is streamed via hardware cameras (e.g., MIPI CSI cameras).
2. **Submodular Distillation:** Instead of processing 30-60 frames per second on heavy models, we use Facility Location Optimization (Submodlib) across a rolling buffer of frames. This identifies the 1 or 2 most statistically informative frames over an interval, discarding redundant spatial data.
3. **STEAD Trigger Model:** This chosen frame is passed to a localized, highly quantized Spatio-Temporal model. The model computes a simple output: "Is this frame out-of-distribution compared to the baseline?". It produces an Anomaly Score (0.0 - 1.0). If the score eclipses a threshold (e.g., `0.85`), the frame is forwarded to the Cortex.

### The Agentic Cortex & RAG (The Decision Logic)
When an anomaly is detected, the Cortex engages:
1. **Vectorization:** The anomalous frame is embedded into a 512-dim latent space.
2. **3-Tier RAG Lookup (Qdrant NVMe DB):**
   - **T1 Spatial:** The vector is compared against geographic baselines.
   - **T2 Behavioral:** The temporal motion sequence is compared against logged actions (e.g., loitering, crawling).
   - **T3 Identity:** Relational identity datasets are matched.
3. **Agentic Synthesis:** The queried context and trigger score are bundled into a prompt. 
   - *If connected to Cloud:* Routed to Gemini via 5G/Satellite for deep intent classification.
   - *If Air-gapped:* Routed to a local quantized LLM (like Gemma-2B or Phi-3) executing on the local Neural Processing Unit (NPU) to deduce risk and suggest deterministic actions (e.g., `TRACK`, `RETURN_HOME`).

---

## 2. Drone Hardware Prerequisites

To deploy this, the drone requires:
- **Compute payload:** NVIDIA Jetson Orin Nano / Jetson Xavier NX / IGX.
- **Camera:** MIPI CSI-2 interface cameras (e.g., IMX477 / IMX219) running GStreamer.
- **Storage:** Minimum 256GB NVMe SSD (Crucial for local Qdrant Vector lookups without I/O bottlenecks).
- **Control Interface:** Pixhawk / PX4 controller communicating over MAVLink for telemetry.

---

## 3. Backend Deployment (On the Drone)

The required logic has been packaged in the `drone_backend/` folder.

### Step 1: Environment Setup
SSH into your Jetson device and instantiate a Python virtual environment.
```bash
python3 -m venv stead_env
source stead_env/bin/activate
cd drone_backend
pip install -r requirements.txt
```

### Step 2: Initialize Local RAG Database
Before starting the system, initialize the localized Qdrant databases. This script sets up a file-based vector structure on the NVMe.
```bash
python qdrant_setup.py
```

### Step 3: Start the Cortex API Node
The Cortex reasoning API runs locally on the drone (serving traffic on `localhost:8000`).
```bash
python main.py
```

### Step 4: Start the Ingestion Pipeline
In a separate terminal, launch the camera ingestion script. This connects to the video feed, performs Submodular sampling, runs the STEAD heuristic, and triggers the Cortex.
*Note: In `ingestion.py`, update `rtsp_url="0"` to your GStreamer pipeline or actual RTSP IP if needed.*
```bash
python ingestion.py
```

---

## 4. Porting the React App (Ground Station)

The current React Web App represents the **Ground Station Dashboard**.

### Modifying the Architecture
By default, the React app uses mock data or calls the Gemini SDK natively if you use the toggle switch. To integrate it truly as a ground station interacting with the Edge Drone:

1. **Host the App:** Deploy the Vite/React application on a ruggedized laptop or ground control tablet. Use Docker or deploy it as a statically built bundle.
2. **WebSocket Integration:** Currently, the App polls or relies on user clicks. You must replace this with a WebSocket listener. 
   - Extend the `FastAPI` instance on the Drone (`main.py`) to serve WebSockets.
   - Ground Station connects to `ws://[DRONE_IP]:8000/ws`.
   - When `ingestion.py` triggers an anomaly, broadcast it over the WebSocket instead of just returning JSON.
3. **Updating `services/aegisService.ts`:**
   Modify the simulation loop in the React app so it no longer generates random pulses, but instead reacts directly to the JSON payloads received from the drone's WebSocket.
4. **Telemetry Setup:** Integrate MAVLink parsing. The drone backend should stream drone coordinates (Lat/Lon/Alt/Heading) using ROS2 or PyMAVLink, feeding the data directly into the Ground Station dashboard UI.

---

## 5. Integrating the Real STEAD Engine (ONNX/TensorRT)

The provided code in `drone_backend/` is already configured for production deployment. `ingestion.py` uses `stead_model.py` which wraps **ONNX Runtime** for hardware-accelerated inference.

### Step 1: Export your PyTorch Model to ONNX
Train your custom STEAD model and export it to an ONNX binary. Ensure the input shape matches the `preprocess` method in `stead_model.py` (Default: `[1, 3, 30, 224, 224]`).
```python
import torch

# Shape: [Batch, Channels, Time, Height, Width] 
dummy_input = torch.randn(1, 3, 30, 224, 224) 
torch.onnx.export(model, dummy_input, "models/stead_mobile_v1.onnx", opset_version=14)
```

### Step 2: Configure Accelerator
On NVIDIA Jetson platforms, edit `stead_model.py` to enable the TensorRT or CUDA Execution Providers for maximum performance.
```python
# In stead_model.py
self.session = ort.InferenceSession(model_path, providers=['TensorrtExecutionProvider', 'CUDAExecutionProvider'])
```

### Step 3: Deployment
Simply place your `stead_mobile_v1.onnx` file in a `models/` directory inside `drone_backend/` and run the pipeline as described in Section 3. The system will automatically switch from simulation to live hardware inference.
