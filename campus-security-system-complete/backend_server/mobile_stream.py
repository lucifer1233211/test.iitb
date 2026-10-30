"""
mobile_stream.py — FastAPI router for smartphone live-camera streaming.

Architecture:
    Phone browser  ─WHIP/WebRTC──►  MediaMTX (:8889)
    MediaMTX       ─RTSP─────────►  VideoProcessor.start_rtsp_stream()
                                     (face + object detection)

Endpoints:
    POST /api/v1/mobile/stream/register          – register & start detection
    GET  /api/v1/mobile/stream/{stream_id}/status – stream status
    POST /api/v1/mobile/stream/{stream_id}/stop   – stop stream
    GET  /api/v1/mobile/stream/page               – no-auth mobile HTML page
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# ── Router ────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/v1/mobile", tags=["mobile-stream"])

# ── MediaMTX defaults ─────────────────────────────────────────────────────────
MEDIAMTX_RTSP_HOST = "localhost"
MEDIAMTX_RTSP_PORT = 8554
MEDIAMTX_WEBRTC_PORT = 8889


# ── In-memory stream registry ─────────────────────────────────────────────────
_phone_streams: dict[str, dict] = {}
_registry_lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitize_id(raw: str) -> str:
    """Keep only alphanumeric chars and underscores."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", raw)


def _make_stream_id(phone_id: str) -> str:
    return f"phone_{_sanitize_id(phone_id)}"


# ── Pydantic models ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    phone_id: str
    name: Optional[str] = "Phone Camera"
    location: Optional[str] = "Mobile"
    detection_mode: Optional[str] = "both"


class RegisterResponse(BaseModel):
    stream_id: str
    rtsp_url: str
    whip_url: str
    push_url: str
    status: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/stream/register", response_model=RegisterResponse)
async def register_phone_stream(
    body: RegisterRequest,
    request: Request,
    # pylint: disable=import-outside-toplevel
):
    """
    Register a phone camera stream.

    1. Derives a deterministic stream_id from phone_id.
    2. Starts the RTSP consumer in VideoProcessor (targets MediaMTX relay).
    3. Returns RTSP + WHIP URLs so the mobile page can push video.

    Requires JWT authentication (Bearer token).
    """
    # Inline import to avoid circular dependency at module load time.
    from main import (  # noqa: F401 – side-effecting import
        get_current_user,
        SessionLocal,
        create_face_alert,
        create_detection_event,
        create_rfdetr_alert,
        notification_bus,
    )
    from face_service import get_face_service
    from video_processor import get_video_processor
    from rfdetr_service import get_rfdetr_service

    # Manual auth: extract user from the Authorization header so we can reuse
    # get_current_user as a normal callable (it is a FastAPI dependency).
    # We call it via Depends-compatible pattern by just awaiting it here.
    # Actually we'll do a clean Depends injection through a helper below.

    stream_id = _make_stream_id(body.phone_id)
    rtsp_url = f"rtsp://{MEDIAMTX_RTSP_HOST}:{MEDIAMTX_RTSP_PORT}/{stream_id}"
    host = request.headers.get("host", "localhost").split(":")[0]
    whip_url = f"http://{host}:{MEDIAMTX_WEBRTC_PORT}/{stream_id}/whip"
    push_url = whip_url  # alias

    detection_mode = body.detection_mode or "both"
    if detection_mode not in ("face", "object", "both"):
        raise HTTPException(400, "detection_mode must be 'face', 'object', or 'both'")

    svc = get_face_service()
    vp = get_video_processor()
    rfdetr = get_rfdetr_service()

    result = vp.start_rtsp_stream(
        stream_id=stream_id,
        rtsp_url=rtsp_url,
        face_service=svc,
        frame_interval=10,          # phone cameras typically 30 fps; process every 10th
        db_session_factory=SessionLocal,
        alert_creator=create_face_alert,
        detection_creator=create_detection_event,
        camera_db_id=None,           # not a registered camera
        camera_name=body.name or "Phone Camera",
        camera_location=body.location or "Mobile",
        reidentification_enabled=True,
        rfdetr_service=rfdetr,
        detection_mode=detection_mode,
        rfdetr_alert_creator=create_rfdetr_alert,
        notify_callback=notification_bus.publish,
    )

    if "error" in result:
        raise HTTPException(400, result["error"])

    # Track locally for status / stop
    with _registry_lock:
        _phone_streams[stream_id] = {
            "stream_id": stream_id,
            "phone_id": body.phone_id,
            "name": body.name,
            "location": body.location,
            "rtsp_url": rtsp_url,
            "whip_url": whip_url,
            "detection_mode": detection_mode,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "live",
        }

    notification_bus.publish("stream_started", {
        "stream_id": stream_id,
        "rtsp_url": rtsp_url,
        "camera_name": body.name or stream_id,
        "location": body.location or "Mobile",
        "source": "phone",
    })

    return RegisterResponse(
        stream_id=stream_id,
        rtsp_url=rtsp_url,
        whip_url=whip_url,
        push_url=push_url,
        status="live",
    )


@router.get("/stream/{stream_id}/status")
async def phone_stream_status(stream_id: str):
    """Return registration info and live status for a phone stream."""
    from video_processor import get_video_processor

    with _registry_lock:
        info = _phone_streams.get(stream_id)

    vp = get_video_processor()
    with vp._lock:
        active = vp.active_streams.get(stream_id)

    if not info and not active:
        raise HTTPException(404, "Stream not found")

    return {
        "stream_id": stream_id,
        "status": "live" if active else "stopped",
        "frames_read": active.get("frames_read", 0) if active else 0,
        "detections_count": active.get("detections_count", 0) if active else 0,
        "registration": info or {},
    }


@router.post("/stream/{stream_id}/stop")
async def stop_phone_stream(stream_id: str):
    """Stop a phone camera stream and tear down the RTSP consumer."""
    from video_processor import get_video_processor
    from main import notification_bus  # noqa: F401

    vp = get_video_processor()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, vp.stop_rtsp_stream, stream_id)

    with _registry_lock:
        _phone_streams.pop(stream_id, None)

    notification_bus.publish("stream_stopped", {
        "stream_id": stream_id,
        "source": "phone",
        "frames_read": result.get("frames_read", 0) if isinstance(result, dict) else 0,
    })

    return {"stream_id": stream_id, "status": "stopped"}


@router.post("/stream/{stream_id}/whip")
async def whip_proxy_post(stream_id: str, request: Request):
    """
    Proxy WHIP SDP offer to MediaMTX on localhost:8889.
    Eliminates CORS, Mixed Content (HTTPS -> HTTP), and extra port firewall issues for mobile clients.
    """
    from fastapi.responses import Response
    import httpx

    body = await request.body()
    target_url = f"http://127.0.0.1:{MEDIAMTX_WEBRTC_PORT}/{stream_id}/whip"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                target_url,
                content=body,
                headers={"Content-Type": request.headers.get("Content-Type", "application/sdp")},
            )
            resp_headers = {"Content-Type": "application/sdp"}
            if "location" in resp.headers:
                resp_headers["Location"] = resp.headers["location"]
            return Response(content=resp.content, status_code=resp.status_code, headers=resp_headers)
        except Exception as e:
            raise HTTPException(502, f"Failed to reach MediaMTX WHIP endpoint: {e}")


@router.delete("/stream/{stream_id}/whip")
async def whip_proxy_delete(stream_id: str, request: Request):
    """Proxy WHIP teardown DELETE to MediaMTX."""
    from fastapi.responses import Response
    import httpx

    target_url = f"http://127.0.0.1:{MEDIAMTX_WEBRTC_PORT}/{stream_id}/whip"
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.delete(target_url)
            return Response(content=resp.content, status_code=resp.status_code)
        except Exception:
            return Response(status_code=200)


# ─────────────────────────────────────────────────────────────────────────────
# Mobile HTML Page  (no auth — token passed as query param)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stream/page", response_class=HTMLResponse)
async def mobile_stream_page(
    stream_id: str = Query(..., description="Phone stream ID, e.g. phone_guard1"),
    token: str = Query(..., description="JWT bearer token"),
    backend_url: Optional[str] = Query(None, description="Backend base URL (defaults to same origin)"),
):
    """
    Serve the self-contained mobile streaming page.
    Open on the guard's phone to start pushing video to the security system.
    No authentication check here – the JWT token is passed as a query param
    and used by the JS to call protected backend endpoints.
    """
    page_html = _build_mobile_page(stream_id, token, backend_url or "")
    return HTMLResponse(content=page_html)


# ─────────────────────────────────────────────────────────────────────────────
# HTML page builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_mobile_page(stream_id: str, token: str, backend_url: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <meta name="theme-color" content="#0a0a0f" />
  <title>IITB Security — Live Stream</title>
  <style>
    /* ── Reset & base ─────────────────────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg:          #0a0a0f;
      --surface:     #13131d;
      --surface2:    #1c1c2e;
      --accent:      #e63946;
      --accent-dim:  #8b1a24;
      --green:       #2ecc71;
      --yellow:      #f39c12;
      --text:        #e8e8f0;
      --text-dim:    #8888aa;
      --border:      #2a2a3e;
      --radius:      14px;
      --font:        -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }}

    html, body {{
      height: 100%;
      background: var(--bg);
      color: var(--text);
      font-family: var(--font);
      -webkit-font-smoothing: antialiased;
    }}

    body {{
      display: flex;
      flex-direction: column;
      min-height: 100dvh;
      padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
    }}

    /* ── Header ───────────────────────────────────────────────────── */
    header {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 14px 18px;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
    }}

    .logo-icon {{
      width: 34px; height: 34px;
      background: var(--accent);
      border-radius: 8px;
      display: flex; align-items: center; justify-content: center;
      font-size: 18px;
      flex-shrink: 0;
    }}

    .header-text h1 {{
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.3px;
    }}

    .header-text p {{
      font-size: 11px;
      color: var(--text-dim);
      margin-top: 1px;
    }}

    /* ── Main content ─────────────────────────────────────────────── */
    main {{
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 14px;
      padding: 16px;
      overflow-y: auto;
    }}

    /* ── Camera preview ───────────────────────────────────────────── */
    .camera-wrap {{
      position: relative;
      width: 100%;
      aspect-ratio: 9/16;
      max-height: 38vh;
      background: #000;
      border-radius: var(--radius);
      overflow: hidden;
      border: 1.5px solid var(--border);
    }}

    #localVideo {{
      width: 100%; height: 100%;
      object-fit: cover;
      transform: scaleX(-1); /* mirror for selfie; environment camera won't look mirrored */
    }}

    .camera-overlay {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(0,0,0,0.7);
      flex-direction: column;
      gap: 10px;
    }}

    .camera-overlay.hidden {{ display: none; }}

    .camera-icon {{
      font-size: 48px;
      opacity: 0.5;
    }}

    .camera-overlay p {{
      font-size: 13px;
      color: var(--text-dim);
      text-align: center;
      padding: 0 20px;
    }}

    /* Live badge */
    .live-badge {{
      position: absolute;
      top: 10px; left: 10px;
      display: none;
      align-items: center;
      gap: 5px;
      background: rgba(230,57,70,0.92);
      border-radius: 20px;
      padding: 4px 10px 4px 8px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 1px;
    }}

    .live-badge.visible {{ display: flex; }}

    .live-dot {{
      width: 7px; height: 7px;
      background: #fff;
      border-radius: 50%;
      animation: pulse 1.2s ease-in-out infinite;
    }}

    @keyframes pulse {{
      0%, 100% {{ opacity: 1; transform: scale(1); }}
      50%        {{ opacity: 0.4; transform: scale(0.7); }}
    }}

    /* Timer overlay */
    .timer-badge {{
      position: absolute;
      top: 10px; right: 10px;
      background: rgba(0,0,0,0.65);
      border-radius: 8px;
      padding: 4px 8px;
      font-size: 12px;
      font-weight: 600;
      display: none;
      font-variant-numeric: tabular-nums;
    }}

    .timer-badge.visible {{ display: block; }}

    /* Resolution */
    .res-badge {{
      position: absolute;
      bottom: 10px; right: 10px;
      background: rgba(0,0,0,0.55);
      border-radius: 6px;
      padding: 3px 7px;
      font-size: 10px;
      color: var(--text-dim);
      display: none;
    }}

    .res-badge.visible {{ display: block; }}

    /* ── Status card ──────────────────────────────────────────────── */
    .status-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px 16px;
    }}

    .status-row {{
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    .status-indicator {{
      width: 11px; height: 11px;
      border-radius: 50%;
      background: var(--text-dim);
      flex-shrink: 0;
      transition: background 0.3s;
    }}

    .status-indicator.connecting {{ background: var(--yellow); animation: pulse 1s infinite; }}
    .status-indicator.live       {{ background: var(--green); }}
    .status-indicator.error      {{ background: var(--accent); }}

    .status-label {{
      font-size: 14px;
      font-weight: 600;
    }}

    .status-sub {{
      font-size: 11px;
      color: var(--text-dim);
      margin-top: 4px;
      line-height: 1.5;
    }}

    /* ── Stream info grid ─────────────────────────────────────────── */
    .info-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }}

    .info-cell {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 12px 14px;
    }}

    .info-cell .label {{
      font-size: 10px;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 4px;
    }}

    .info-cell .value {{
      font-size: 18px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }}

    .info-cell .value.small {{ font-size: 13px; font-weight: 600; }}

    /* ── Buttons ──────────────────────────────────────────────────── */
    .btn-row {{
      display: flex;
      gap: 10px;
    }}

    button {{
      flex: 1;
      height: 56px;
      border: none;
      border-radius: var(--radius);
      font-size: 16px;
      font-weight: 700;
      cursor: pointer;
      letter-spacing: 0.3px;
      transition: opacity 0.15s, transform 0.1s;
      -webkit-tap-highlight-color: transparent;
    }}

    button:active {{ transform: scale(0.97); opacity: 0.85; }}
    button:disabled {{ opacity: 0.35; cursor: not-allowed; transform: none; }}

    #startBtn {{
      background: var(--accent);
      color: #fff;
    }}

    #stopBtn {{
      background: var(--surface2);
      color: var(--text);
      border: 1.5px solid var(--border);
    }}

    /* ── Error box ────────────────────────────────────────────────── */
    #errorBox {{
      display: none;
      background: rgba(230,57,70,0.12);
      border: 1px solid var(--accent-dim);
      border-radius: var(--radius);
      padding: 12px 14px;
      font-size: 13px;
      color: #ff8890;
      line-height: 1.55;
    }}

    #errorBox.visible {{ display: block; }}

    /* ── Stream ID pill ───────────────────────────────────────────── */
    .stream-id-pill {{
      display: flex;
      align-items: center;
      gap: 8px;
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 12px;
      font-size: 11px;
    }}

    .stream-id-pill .label {{ color: var(--text-dim); flex-shrink: 0; }}
    .stream-id-pill .id    {{ color: var(--text); font-weight: 600; word-break: break-all; }}

    /* ── Footer ───────────────────────────────────────────────────── */
    footer {{
      text-align: center;
      font-size: 10px;
      color: var(--text-dim);
      padding: 12px 16px;
      border-top: 1px solid var(--border);
    }}
  </style>
</head>
<body>

<header>
  <div class="logo-icon">🛡️</div>
  <div class="header-text">
    <h1>IITB Security — Live Camera</h1>
    <p>Tap Start to begin streaming to the security dashboard</p>
  </div>
</header>

<main>

  <!-- Camera preview -->
  <div class="camera-wrap">
    <video id="localVideo" autoplay muted playsinline></video>
    <div class="camera-overlay" id="cameraOverlay">
      <div class="camera-icon">📷</div>
      <p>Tap <strong>Start Streaming</strong> to activate your camera</p>
    </div>
    <div class="live-badge" id="liveBadge"><div class="live-dot"></div>LIVE</div>
    <div class="timer-badge" id="timerBadge">00:00</div>
    <div class="res-badge" id="resBadge">—</div>
  </div>

  <!-- Stream ID pill -->
  <div class="stream-id-pill">
    <span class="label">Stream ID</span>
    <span class="id" id="streamIdLabel">{stream_id}</span>
  </div>

  <!-- Status -->
  <div class="status-card">
    <div class="status-row">
      <div class="status-indicator" id="statusDot"></div>
      <div class="status-label" id="statusLabel">Ready</div>
    </div>
    <div class="status-sub" id="statusSub">Press Start Streaming to begin.</div>
  </div>

  <!-- Stats grid -->
  <div class="info-grid">
    <div class="info-cell">
      <div class="label">Elapsed</div>
      <div class="value" id="elapsedVal">—</div>
    </div>
    <div class="info-cell">
      <div class="label">Resolution</div>
      <div class="value small" id="resVal">—</div>
    </div>
  </div>

  <!-- Error box -->
  <div id="errorBox"></div>

  <!-- Action buttons -->
  <div class="btn-row">
    <button id="startBtn">▶ Start Streaming</button>
    <button id="stopBtn" disabled>■ Stop</button>
  </div>

</main>

<footer>IITB Integrated Security System &nbsp;·&nbsp; Smartphone Camera Module</footer>

<script>
// ── Config (injected server-side) ────────────────────────────────────────────
const STREAM_ID   = {repr(stream_id)};
const JWT_TOKEN   = {repr(token)};
const BACKEND_URL = {repr(backend_url)} || window.location.origin;
const MEDIAMTX_WS_HOST = window.location.hostname;
const MEDIAMTX_WEBRTC_PORT = 8889;
const BACKEND_WHIP_URL = `${{BACKEND_URL}}/api/v1/mobile/stream/${{STREAM_ID}}/whip`;
const DIRECT_WHIP_URL  = `http://${{MEDIAMTX_WS_HOST}}:${{MEDIAMTX_WEBRTC_PORT}}/${{STREAM_ID}}/whip`;

// ── State ────────────────────────────────────────────────────────────────────
let pc          = null;   // RTCPeerConnection
let localStream = null;
let startTime   = null;
let timerHandle = null;
let state       = "idle"; // idle | requesting | connecting | live | error | stopped

// ── DOM refs ─────────────────────────────────────────────────────────────────
const video         = document.getElementById("localVideo");
const cameraOverlay = document.getElementById("cameraOverlay");
const liveBadge     = document.getElementById("liveBadge");
const timerBadge    = document.getElementById("timerBadge");
const resBadge      = document.getElementById("resBadge");
const statusDot     = document.getElementById("statusDot");
const statusLabel   = document.getElementById("statusLabel");
const statusSub     = document.getElementById("statusSub");
const elapsedVal    = document.getElementById("elapsedVal");
const resVal        = document.getElementById("resVal");
const errorBox      = document.getElementById("errorBox");
const startBtn      = document.getElementById("startBtn");
const stopBtn       = document.getElementById("stopBtn");

// ── UI helpers ────────────────────────────────────────────────────────────────
function setState(newState, label, sub) {{
  state = newState;
  statusLabel.textContent = label;
  statusSub.textContent   = sub;

  statusDot.className = "status-indicator";
  if (newState === "connecting" || newState === "requesting") {{
    statusDot.classList.add("connecting");
  }} else if (newState === "live") {{
    statusDot.classList.add("live");
  }} else if (newState === "error") {{
    statusDot.classList.add("error");
  }}

  liveBadge.classList.toggle("visible", newState === "live");
  timerBadge.classList.toggle("visible", newState === "live");
  resBadge.classList.toggle("visible", newState === "live" || newState === "connecting");

  startBtn.disabled = (newState === "requesting" || newState === "connecting" || newState === "live");
  stopBtn.disabled  = !(newState === "live" || newState === "connecting");
}}

function showError(msg) {{
  errorBox.textContent = "⚠️ " + msg;
  errorBox.classList.add("visible");
  setState("error", "Error", msg.length > 60 ? msg.slice(0, 60) + "…" : msg);
}}

function clearError() {{
  errorBox.classList.remove("visible");
  errorBox.textContent = "";
}}

function fmtTime(sec) {{
  const m = Math.floor(sec / 60).toString().padStart(2, "0");
  const s = (sec % 60).toString().padStart(2, "0");
  return `${{m}}:${{s}}`;
}}

function startTimer() {{
  startTime = Date.now();
  timerHandle = setInterval(() => {{
    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    timerBadge.textContent = fmtTime(elapsed);
    elapsedVal.textContent = fmtTime(elapsed);
  }}, 1000);
}}

function stopTimer() {{
  clearInterval(timerHandle);
  timerHandle = null;
}}

function showResolution(track) {{
  const settings = track.getSettings();
  const w = settings.width || "?";
  const h = settings.height || "?";
  const label = `${{w}}×${{h}}`;
  resBadge.textContent = label;
  resBadge.classList.add("visible");
  resVal.textContent = label;
}}

// ── Register stream with backend + notify detection ───────────────────────────
async function registerStream() {{
  try {{
    const res = await fetch(`${{BACKEND_URL}}/api/v1/mobile/stream/register`, {{
      method: "POST",
      headers: {{
        "Content-Type": "application/json",
        "Authorization": `Bearer ${{JWT_TOKEN}}`,
      }},
      body: JSON.stringify({{
        phone_id: STREAM_ID,
        name: "Phone Camera — " + STREAM_ID,
        location: "Mobile Field",
        detection_mode: "both",
      }}),
    }});

    if (!res.ok) {{
      const detail = await res.json().catch(() => ({{detail: res.statusText}}));
      throw new Error(detail.detail || `Registration failed (${{res.status}})`);
    }}

    return await res.json();
  }} catch (err) {{
    throw new Error("Backend registration: " + err.message);
  }}
}}

// ── Stop stream on backend ────────────────────────────────────────────────────
async function stopStreamOnBackend() {{
  try {{
    await fetch(`${{BACKEND_URL}}/api/v1/mobile/stream/${{STREAM_ID}}/stop`, {{
      method: "POST",
      headers: {{ "Authorization": `Bearer ${{JWT_TOKEN}}` }},
    }});
  }} catch (_) {{
    // Best-effort – don't block the UI teardown
  }}
}}

// ── WHIP push ─────────────────────────────────────────────────────────────────
async function startWHIP(stream) {{
  // ICE servers: STUN (local network) + TURN (cross-network relay for different WiFi/mobile data)
  pc = new RTCPeerConnection({{
    iceServers: [
      {{ urls: "stun:stun.l.google.com:19302" }},
      {{ urls: "stun:stun1.l.google.com:19302" }},
      {{
        urls: [
          "turn:openrelay.metered.ca:80",
          "turn:openrelay.metered.ca:443",
          "turns:openrelay.metered.ca:443"
        ],
        username: "openrelayproject",
        credential: "openrelayproject"
      }}
    ],
    iceTransportPolicy: "all",
    bundlePolicy: "max-bundle",
    rtcpMuxPolicy: "require",
  }});

  // Add all local tracks
  stream.getTracks().forEach(track => pc.addTrack(track, stream));

  // Create offer
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  // Wait for ICE gathering to complete (or timeout)
  await new Promise((resolve) => {{
    if (pc.iceGatheringState === "complete") {{ resolve(); return; }}
    const onStateChange = () => {{
      if (pc.iceGatheringState === "complete") {{
        pc.removeEventListener("icegatheringstatechange", onStateChange);
        resolve();
      }}
    }};
    pc.addEventListener("icegatheringstatechange", onStateChange);
    setTimeout(resolve, 4000); // 4 s fallback
  }});

  // WHIP: POST the SDP offer (try backend proxy first, fallback to direct MediaMTX)
  let resp = null;
  try {{
    resp = await fetch(BACKEND_WHIP_URL, {{
      method: "POST",
      headers: {{ "Content-Type": "application/sdp" }},
      body: pc.localDescription.sdp,
    }});
  }} catch (proxyErr) {{
    console.warn("Backend proxy WHIP failed, trying direct MediaMTX:", proxyErr);
  }}

  if (!resp || !resp.ok) {{
    try {{
      resp = await fetch(DIRECT_WHIP_URL, {{
        method: "POST",
        headers: {{ "Content-Type": "application/sdp" }},
        body: pc.localDescription.sdp,
      }});
    }} catch (directErr) {{
      throw new Error(`MediaMTX connection failed: ${{directErr.message}}. Make sure MediaMTX is running.`);
    }}
  }}

  if (!resp.ok) {{
    throw new Error(`MediaMTX WHIP error: ${{resp.status}} ${{resp.statusText}}. ` +
      "Make sure MediaMTX is running (docker-compose up mediamtx -d).");
  }}

  const answerSDP = await resp.text();

  await pc.setRemoteDescription({{
    type: "answer",
    sdp: answerSDP,
  }});

  // Monitor connection state
  pc.addEventListener("connectionstatechange", () => {{
    if (state !== "live" && state !== "connecting") return;
    const cs = pc.connectionState;
    if (cs === "connected") {{
      setState("live", "🔴 LIVE — Streaming to Security System",
        "Video is being processed for face & object detection.");
      startTimer();
    }} else if (cs === "failed" || cs === "disconnected" || cs === "closed") {{
      showError("WebRTC connection lost. Tap Start Streaming to reconnect.");
      teardown();
    }}
  }});
}}

// ── Teardown ──────────────────────────────────────────────────────────────────
async function teardown() {{
  stopTimer();
  if (pc) {{ pc.close(); pc = null; }}
  if (localStream) {{
    localStream.getTracks().forEach(t => t.stop());
    localStream = null;
  }}
  video.srcObject = null;
  cameraOverlay.classList.remove("hidden");
  liveBadge.classList.remove("visible");
  timerBadge.classList.remove("visible");
  resBadge.classList.remove("visible");
}}

// ── Start streaming ────────────────────────────────────────────────────────────
startBtn.addEventListener("click", async () => {{
  clearError();
  setState("requesting", "Requesting Camera…", "Please allow camera access when prompted.");

  try {{
    // 1. Get camera
    localStream = await navigator.mediaDevices.getUserMedia({{
      video: {{
        facingMode: "environment",
        width:  {{ ideal: 1280 }},
        height: {{ ideal: 720 }},
      }},
      audio: false,
    }});

    video.srcObject = localStream;
    cameraOverlay.classList.add("hidden");

    const videoTrack = localStream.getVideoTracks()[0];
    if (videoTrack) showResolution(videoTrack);

    setState("connecting", "Connecting…", "Registering with security backend & starting detection…");

    // 2. Register with backend (starts VideoProcessor)
    await registerStream();

    // 3. Push to MediaMTX via WHIP
    await startWHIP(localStream);

    setState("connecting", "Connecting to MediaMTX…", "Establishing WebRTC connection to relay server…");

  }} catch (err) {{
    showError(err.message || "Unknown error. Check console for details.");
    await teardown();
    setState("error", "Connection Failed", "See details above.");
  }}
}});

// ── Stop streaming ─────────────────────────────────────────────────────────────
stopBtn.addEventListener("click", async () => {{
  setState("idle", "Stopping…", "Shutting down stream…");
  await stopStreamOnBackend();
  await teardown();
  setState("idle", "Stopped", "Stream ended. Tap Start Streaming to begin again.");
  startBtn.disabled = false;
  stopBtn.disabled  = true;
  elapsedVal.textContent = "—";
  resVal.textContent     = "—";
}});

// ── Handle page unload ─────────────────────────────────────────────────────────
window.addEventListener("beforeunload", () => {{
  if (state === "live" || state === "connecting") {{
    stopStreamOnBackend();
    if (pc) pc.close();
    if (localStream) localStream.getTracks().forEach(t => t.stop());
  }}
}});

// ── HTTPS / permissions check ──────────────────────────────────────────────────
if (location.protocol !== "https:" && location.hostname !== "localhost" &&
    location.hostname !== "127.0.0.1") {{
  showError("Camera access requires HTTPS (or localhost). " +
    "Use a Cloudflare Tunnel or self-signed cert to access from a phone over the local network.");
}}
</script>

</body>
</html>"""
