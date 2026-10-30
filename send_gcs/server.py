from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import os

app = FastAPI()

# Enable CORS so your laptop browser can talk to the Jetson smoothly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LOG_FILE = "/home/mdm/GCS_UAV_test/inference_mock.log"

@app.post("/api/start/{model_name}")
async def start_model(model_name: str):
    # Mock commands that write 'Hello World from [Model]' to a log file
    commands = {
        "multi_cam_tracking": f"echo 'Hello World: Starting Multi-Cam Tracking' >> {LOG_FILE}",
        "marathi_ocr": f"echo 'Hello World: Starting Marathi OCR Engine' >> {LOG_FILE}",
        "person_reid": f"echo 'Hello World: Starting Person Re-ID' >> {LOG_FILE}"
    }
    
    cmd = commands.get(model_name)
    if not cmd:
        return {"status": "error", "message": "Unknown model selective option"}

    # Trigger the background shell command
    subprocess.Popen(cmd, shell=True)
    
    return {
        "status": "success", 
        "message": f"Successfully triggered {model_name} on Jetson!"
    }

@app.post("/api/stop")
async def stop_model():
    cmd = f"echo 'Hello World: Stopping all inference loops' >> {LOG_FILE}"
    subprocess.Popen(cmd, shell=True)
    return {"status": "success", "message": "All mock tasks stopped successfully."}


STREAM_MGR_CONTAINER_NAME = os.environ.get(
    "STREAM_MGR_CONTAINER_NAME", "gcs_uav_test-stream-mgr-1"
)


@app.post("/api/restart-stream-manager")
async def restart_stream_manager():
    """
    FINAL recovery step for the stream_mgr watchdog. Called by stream_mgr.py
    itself (over HTTP) once every in-container recovery mechanism has been
    exhausted (Level 5 escalation). Runs on the host side, outside the
    container, so stream_mgr.py never needs the Docker socket mounted in.
    """
    try:
        result = subprocess.run(
            ["docker", "restart", STREAM_MGR_CONTAINER_NAME],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": str(exc)},
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": f"docker restart exited with code {result.returncode}",
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )

    return {
        "status": "success",
        "message": f"Container '{STREAM_MGR_CONTAINER_NAME}' restarted.",
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
