from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)

# Sample state
state = {
    "backend_status": True,
    "telemetry_connected": True,
    "mission_running": False,
    "mission_id": None,
    "model": None,
    "prompt": None,
    "frames_processed": 0,
    "detections": 0,
    "altitude": 25.5,
    "groundspeed": 8.2,
    "heading": 42.5,
    "battery_pct": 78.5,
    "gps_fix": True,
}

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "backend": state["backend_status"],
        "telemetry": state["telemetry_connected"],
        "mission": state["mission_running"],
        "stream": True
    })

@app.route("/telemetry", methods=["GET"])
def telemetry():
    return jsonify({
        "altitude": state["altitude"],
        "groundspeed": state["groundspeed"],
        "heading": state["heading"],
        "battery_pct": state["battery_pct"],
        "gps_fix": state["gps_fix"],
        "connected": state["telemetry_connected"]
    })

@app.route("/stream", methods=["GET"])
def stream():
    return jsonify({
        "rtsp_stream": "rtsp://localhost:8554/main",
        "http_stream": None,
        "processed_http_stream": None,
        "resolution": "demo",
        "fps": None,
        "bitrate": None,
        "latency_ms": None,
        "dropped_frames": 0,
    })

@app.route("/models", methods=["GET"])
def models():
    return jsonify(["person_reid", "object_detect"])

@app.route("/missions/status", methods=["GET"])
def mission_status():
    return jsonify({
        "status": "running" if state["mission_running"] else "idle",
        "model": state["model"],
        "prompt": state["prompt"],
        "mission_id": state["mission_id"],
        "frames_processed": state["frames_processed"],
        "detections": state["detections"],
        "started_at": datetime.now().isoformat() if state["mission_running"] else None
    })

@app.route("/mission/state", methods=["GET"])
def mission_state():
    running = state["mission_running"]
    progress = min(100, state["frames_processed"]) if running else 0
    return jsonify({
        "backend_connected": state["backend_status"],
        "camera_connected": True,
        "telemetry_connected": state["telemetry_connected"],
        "stream_connected": True,
        "status": "running" if running else "idle",
        "stage": "ai_inference" if running else "idle",
        "progress": progress,
        "prompt": state["prompt"],
        "runtime": 0,
        "frames_processed": state["frames_processed"],
        "detections": state["detections"],
        "latest_confidence": None,
        "stats": {},
    })

@app.route("/results/latest", methods=["GET"])
def latest_results():
    return jsonify([])

@app.route("/logs/latest", methods=["GET"])
def latest_logs():
    return jsonify({
        "logs": [
            "GCS demo backend online",
            "Telemetry simulator ready",
            "Waiting for mission start",
        ]
    })

@app.route("/missions/start", methods=["POST"])
def start_mission():
    data = request.json
    if state["mission_running"]:
        return jsonify({"error": "Mission already running"}), 409
    
    state["mission_running"] = True
    state["mission_id"] = "mission-" + str(int(datetime.now().timestamp()))
    state["model"] = data.get("model")
    state["prompt"] = data.get("prompt")
    state["frames_processed"] = 0
    state["detections"] = 0
    
    return jsonify({
        "ok": True,
        "mission_id": state["mission_id"],
        "message": "Mission started successfully"
    })

@app.route("/missions/stop", methods=["POST"])
def stop_mission():
    state["mission_running"] = False
    state["frames_processed"] = 0
    state["detections"] = 0
    return jsonify({"ok": True, "message": "Mission stopped"})

if __name__ == "__main__":
    port = int(os.environ.get("GCS_BACKEND_PORT", "5002"))
    print(f"Starting GCS Sample Backend on http://localhost:{port}")
    print("Frontend should connect to this server")
    app.run(debug=False, host="0.0.0.0", port=port)
