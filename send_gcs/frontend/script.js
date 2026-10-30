// =========================================================================
// UAV GROUND CONTROL STATION — FRONTEND INTEGRATION
// =========================================================================
// Production-ready frontend for FastAPI backend.
// All data comes from backend endpoints — no hardcoded values.
// =========================================================================

// =========================================================================
// CONFIGURATION
// =========================================================================

// =====================================================================
// Frontend Integration Improvement (Task 10): API_BASE_URL and polling
// intervals now come from the shared config.js (loaded before this file)
// instead of being duplicated here.
// =====================================================================
const API_BASE_URL = (window.GCS_CONFIG && window.GCS_CONFIG.API_BASE_URL) || "http://10.51.26.15:5002";
const REFRESH_INTERVALS = (window.GCS_CONFIG && window.GCS_CONFIG.REFRESH_INTERVALS) || {
  health: 3000, telemetry: 1000, missionStatus: 1000, results: 2000, logs: 2000,
};

// Browser-compatible video stream URLs. Populated from GET /stream.
// Never hardcoded — always fetched from the backend.
let VIDEO_STREAM_URL = "";
// =====================================================================
// NEW FEATURE — Dual Live Stream Panel (Task 1)
// Processed AI stream (bounding boxes / confidence / rank) URL, from
// GET /stream's processed_http_stream. May be absent if not yet deployed
// on the backend — handled gracefully via "Processed AI stream unavailable".
// =====================================================================
let PROCESSED_STREAM_URL = "";

// =========================================================================
// APPLICATION STATE
// =========================================================================

const state = {
  // Connection & health (null = unknown initial state)
  backendOnline: null,
  telemetryOnline: null,
  missionRunning: null,
  streamOnline: null,

  // Mission
  requestPending: false,

  // Video monitoring
  videoConnected: false,
  processedConnected: false, // NEW FEATURE
};

// Interval handles for cleanup
const intervalHandles = {
  health: null,
  telemetry: null,
  missionStatus: null,
  results: null,
  logs: null,
  stream: null, // NEW FEATURE
  clock: null,
};

// =========================================================================
// DOM REFERENCES
// =========================================================================

const dom = {
  // Top bar
  backendDot: document.getElementById("backendDot"),
  backendStatusText: document.getElementById("backendStatusText"),
  telemetryDot: document.getElementById("telemetryDot"),
  telemetryStatusText: document.getElementById("telemetryStatusText"),
  missionDot: document.getElementById("missionDot"),
  missionStatusText: document.getElementById("missionStatusText"),
  currentTime: document.getElementById("currentTime"),

  // Mission control
  modelSelect: document.getElementById("modelSelect"),
  promptInput: document.getElementById("promptInput"),
  streamUrlInput: document.getElementById("streamUrlInput"),
  manualAltitudeGroup: document.getElementById("manualAltitudeGroup"),
  manualAltitudeInput: document.getElementById("manualAltitudeInput"),
  startMissionBtn: document.getElementById("startMissionBtn"),
  stopMissionBtn: document.getElementById("stopMissionBtn"),

  // Mission status card
  msState: document.getElementById("msState"),
  msMissionId: document.getElementById("msMissionId"),
  msModel: document.getElementById("msModel"),
  msPrompt: document.getElementById("msPrompt"),
  msRuntime: document.getElementById("msRuntime"),

  // Video panel (original feed)
  videoFrame: document.getElementById("videoFrame"),
  videoPlaceholder: document.getElementById("videoPlaceholder"),
  videoSpinner: document.getElementById("videoSpinner"), // NEW FEATURE
  videoConnDot: document.getElementById("videoConnDot"),
  videoConnectionIndicator: document.getElementById("videoConnectionIndicator"),
  videoResolution: document.getElementById("videoResolution"),
  videoStreamStatus: document.getElementById("videoStreamStatus"),
  videoLastFrame: document.getElementById("videoLastFrame"),

  // NEW FEATURE — Dual Live Stream Panel (Task 1): processed AI feed
  processedFrame: document.getElementById("processedFrame"),
  processedPlaceholder: document.getElementById("processedPlaceholder"),
  processedSpinner: document.getElementById("processedSpinner"), // NEW FEATURE
  processedConnDot: document.getElementById("processedConnDot"),
  processedConnectionIndicator: document.getElementById("processedConnectionIndicator"),
  processedStreamStatus: document.getElementById("processedStreamStatus"),

  // NEW FEATURE — Video Statistics (only ever populated from real backend data)
  videoFps: document.getElementById("videoFps"),
  videoBitrate: document.getElementById("videoBitrate"),
  videoLatency: document.getElementById("videoLatency"),
  videoDropped: document.getElementById("videoDropped"),

  // Telemetry
  telConnection: document.getElementById("telConnection"),
  telMode: document.getElementById("telMode"),
  telArmed: document.getElementById("telArmed"),
  telAltitude: document.getElementById("telAltitude"),
  telHeading: document.getElementById("telHeading"),
  telGroundspeed: document.getElementById("telGroundspeed"),
  telClimb: document.getElementById("telClimb"),
  telBatteryPct: document.getElementById("telBatteryPct"),
  telBatteryVoltage: document.getElementById("telBatteryVoltage"),
  telGpsFix: document.getElementById("telGpsFix"),
  telSatellites: document.getElementById("telSatellites"),
  telLatitude: document.getElementById("telLatitude"),
  telLongitude: document.getElementById("telLongitude"),

  // Detection results (latest)
  detectionImage: document.getElementById("detectionImage"),
  detectionPlaceholder: document.getElementById("detectionPlaceholder"),
  detConfidence: document.getElementById("detConfidence"),
  detSimilarity: document.getElementById("detSimilarity"), // NEW FEATURE
  detMissionId: document.getElementById("detMissionId"),
  detPrompt: document.getElementById("detPrompt"),
  detTimestamp: document.getElementById("detTimestamp"),
  detBbox: document.getElementById("detBbox"),
  detFrameNumber: document.getElementById("detFrameNumber"),
  detModel: document.getElementById("detModel"),
  detRefresh: document.getElementById("detRefresh"),

  // Detection gallery
  detectionGallery: document.getElementById("detectionGallery"),

  // Image popup
  imagePopup: document.getElementById("imagePopup"),
  popupImage: document.getElementById("popupImage"),
  popupDetails: document.getElementById("popupDetails"),
  popupClose: document.getElementById("popupClose"),
  popupDownload: document.getElementById("popupDownload"), // NEW FEATURE

  // Engineering log
  engineeringLog: document.getElementById("engineeringLog"),

  // Notifications
  notificationArea: document.getElementById("notificationArea"),
};

// =========================================================================
// INITIALIZATION
// =========================================================================

function initialize() {
  attachEventListeners();
  startClock();

  // Initial data loads
  loadModels();
  loadHealth();
  loadStreamConfig();
  loadTelemetry();
  loadMissionStatus();
  loadLatestResults();
  loadLogs();

  // Set up polling intervals
  intervalHandles.health = setInterval(loadHealth, REFRESH_INTERVALS.health);
  intervalHandles.telemetry = setInterval(loadTelemetry, REFRESH_INTERVALS.telemetry);
  intervalHandles.missionStatus = setInterval(loadMissionStatus, REFRESH_INTERVALS.missionStatus);
  intervalHandles.results = setInterval(loadLatestResults, REFRESH_INTERVALS.results);
  intervalHandles.logs = setInterval(loadLogs, REFRESH_INTERVALS.logs);
  // NEW FEATURE: periodic /stream refresh keeps Video Statistics live and
  // guards against a healthy stream never getting reapplied after a
  // silent MediaMTX-side change.
  if (REFRESH_INTERVALS.stream) {
    intervalHandles.stream = setInterval(loadStreamConfig, REFRESH_INTERVALS.stream);
  }

  // Mission Control panel (frontend/mission.js) — independent polling loop
  // against GET /mission/state. Guarded so a missing/failed mission.js
  // load can never break the rest of the dashboard's initialization.
  if (typeof startMissionPolling === "function") {
    startMissionPolling();
  }
}

function attachEventListeners() {
  dom.startMissionBtn.addEventListener("click", startMission);
  dom.stopMissionBtn.addEventListener("click", stopMission);

  // Toggle manual altitude field visibility
  document.querySelectorAll('input[name="altitudeSource"]').forEach((radio) => {
    radio.addEventListener("change", (e) => {
      dom.manualAltitudeGroup.style.display =
        e.target.value === "manual" ? "block" : "none";
    });
  });

  // Popup close handlers
  if (dom.popupClose) {
    dom.popupClose.addEventListener("click", closePopup);
  }
  if (dom.imagePopup) {
    dom.imagePopup.addEventListener("click", (e) => {
      // Close when clicking the overlay background (not the popup content)
      if (e.target === dom.imagePopup) closePopup();
    });
  }

  // Close popup on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePopup();
  });
}

function startClock() {
  const tick = () => {
    dom.currentTime.textContent = new Date().toLocaleTimeString();
  };
  tick();
  intervalHandles.clock = setInterval(tick, 1000);
}

// =========================================================================
// DATA LOADERS
// =========================================================================

/**
 * GET /health — Single source of truth for all status indicators.
 * Backend returns: { backend, telemetry, mission, stream }
 */
async function loadHealth() {
  try {
    const response = await fetch(`${API_BASE_URL}/health`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    updateHealthUI(data);
  } catch (error) {
    // If /health itself fails, the backend is offline
    updateHealthUI({
      backend: false,
      telemetry: false,
      mission: false,
      stream: false,
    });
  }
}

/**
 * GET /stream — Fetch stream URLs from backend.
 * Called once during initialization. Frontend never hardcodes stream URLs.
 */
async function loadStreamConfig() {
  try {
    const response = await fetch(`${API_BASE_URL}/stream`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    // Only (re)apply the iframe src when the URL actually changed or we
    // aren't currently connected — periodic polling must refresh stats
    // without flicker-reloading an already-healthy stream.
    if (data.http_stream && (data.http_stream !== VIDEO_STREAM_URL || !state.videoConnected)) {
      VIDEO_STREAM_URL = data.http_stream;
      applyVideoStream();
    } else if (data.http_stream) {
      VIDEO_STREAM_URL = data.http_stream;
    }

    // NEW FEATURE — Dual Live Stream Panel (Task 1): processed AI feed.
    // Only wired up if the backend actually reports a URL; otherwise the
    // panel shows "Processed AI stream unavailable" and never breaks.
    const processedUrlChanged = data.processed_http_stream && data.processed_http_stream !== PROCESSED_STREAM_URL;
    if (data.processed_http_stream) PROCESSED_STREAM_URL = data.processed_http_stream;
    if (processedUrlChanged || !state.processedConnected) {
      applyProcessedVideoStream();
    }

    // Populate the RTSP field automatically — the user should never have
    // to manually copy/paste the RTSP URL.
    if (data.rtsp_stream && dom.streamUrlInput) {
      dom.streamUrlInput.value = data.rtsp_stream;
    }

    // NEW FEATURE — Video Statistics: only rendered if the backend actually
    // includes these fields in /stream. Never estimated or fabricated.
    if (dom.videoResolution) dom.videoResolution.textContent = data.resolution ?? "--";
    if (dom.videoFps) dom.videoFps.textContent = data.fps != null ? `${data.fps} fps` : "--";
    if (dom.videoBitrate) dom.videoBitrate.textContent = data.bitrate != null ? `${data.bitrate} kbps` : "--";
    if (dom.videoLatency) dom.videoLatency.textContent = data.latency_ms != null ? `${data.latency_ms} ms` : "--";
    if (dom.videoDropped) dom.videoDropped.textContent = data.dropped_frames ?? "--";
  } catch (error) {
    console.warn("[GCS] Could not fetch stream config:", error.message);
  }
}

/**
 * GET /models — Load available AI models for the dropdown.
 */
async function loadModels() {
  try {
    const response = await fetch(`${API_BASE_URL}/models`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    const models = Array.isArray(data) ? data : data.models || [];
    dom.modelSelect.innerHTML = "";

    if (models.length === 0) {
      dom.modelSelect.innerHTML =
        '<option value="">No models available</option>';
      return;
    }

    models.forEach((model) => {
      const value = typeof model === "string" ? model : model.id || model.name;
      const label = typeof model === "string" ? model : model.name || model.id;
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      dom.modelSelect.appendChild(option);
    });
  } catch (error) {
    dom.modelSelect.innerHTML =
      '<option value="">Backend Unavailable</option>';
  }
}

/**
 * GET /telemetry — Fetch live telemetry data.
 * Polled every 1000ms.
 */
async function loadTelemetry() {
  try {
    const response = await fetch(`${API_BASE_URL}/telemetry`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    updateTelemetryUI(data);
  } catch (error) {
    updateTelemetryUI(null);
  }
}

/**
 * GET /missions/status — Fetch mission status.
 * Returns: { status, container_name, pid, returncode, started_at?, model?, prompt?, mission_id? }
 * Use data.status === "running" — the backend does not return a "running" field.
 * Polled every 1000ms.
 */
async function loadMissionStatus() {
  try {
    const response = await fetch(`${API_BASE_URL}/missions/status`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    updateMissionUI(data);
  } catch (error) {
    // Health endpoint handles connection status — no action needed here
  }
}

/**
 * GET /results/latest?limit=50 — Fetch latest detection results.
 * Backend returns an array (newest first). Limit raised from 8 so the
 * history gallery has a fuller scrollable list beyond the single pinned
 * featured detection. Same endpoint, same polling interval — just a
 * larger page size.
 * Polled every 2000ms.
 */
async function loadLatestResults() {
  try {
    const response = await fetch(`${API_BASE_URL}/results/latest?limit=50`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    updateResultsUI(data);
  } catch (error) {
    updateResultsUI(null);
  }
}

/**
 * GET /logs/latest?lines=50 — Fetch engineering log entries.
 * Backend returns: { logs: [...] } with newest-first ordering.
 * Polled every 2000ms.
 */
async function loadLogs() {
  try {
    const response = await fetch(`${API_BASE_URL}/logs/latest?lines=50`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    updateLogsUI(data.logs || []);
  } catch (error) {
    // Logs are non-critical — fail silently
  }
}

// =========================================================================
// MISSION ACTIONS
// =========================================================================

async function startMission() {
  if (state.requestPending) return;

  const model = dom.modelSelect.value;
  const prompt = dom.promptInput.value.trim();
  const streamUrl = dom.streamUrlInput.value.trim();
  const altitudeSource = document.querySelector(
    'input[name="altitudeSource"]:checked'
  ).value;
  const manualAltitude = parseFloat(dom.manualAltitudeInput.value);

  // Validation
  if (!model) {
    showNotification("Please select a model before starting the mission.", "warning");
    return;
  }
  if (!streamUrl) {
    showNotification("Please provide an RTSP stream URL.", "warning");
    return;
  }
  if (altitudeSource === "manual" && isNaN(manualAltitude)) {
    showNotification("Please enter a valid manual altitude.", "warning");
    return;
  }

  const body = {
    model: model,
    stream_url: streamUrl,
    prompt: prompt,
    altitude_source: altitudeSource,
    altitude: altitudeSource === "manual" ? manualAltitude : null,
  };

  setRequestPending(true);
  try {
    const response = await fetch(`${API_BASE_URL}/missions/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    loadMissionStatus();
  } catch (error) {
    showNotification(`Mission Failed: ${error.message}`, "error");
  } finally {
    setRequestPending(false);
  }
}

async function stopMission() {
  if (state.requestPending) return;

  setRequestPending(true);
  try {
    const response = await fetch(`${API_BASE_URL}/missions/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    loadMissionStatus();
  } catch (error) {
    showNotification(`Failed to stop mission: ${error.message}`, "error");
  } finally {
    setRequestPending(false);
  }
}

function setRequestPending(pending) {
  state.requestPending = pending;
  dom.startMissionBtn.disabled = pending;
  dom.stopMissionBtn.disabled = pending;
}

// =========================================================================
// UI UPDATERS
// =========================================================================

/**
 * Update all status indicators from /health response.
 * Fires state-change notifications when status transitions occur.
 */
function updateHealthUI(data) {
  // --- Backend ---
  const prevBackend = state.backendOnline;
  state.backendOnline = !!data.backend;
  dom.backendDot.className = `dot ${data.backend ? "online" : "offline"}`;
  dom.backendStatusText.textContent = data.backend
    ? "Backend Online"
    : "Backend Offline";

  if (prevBackend !== null && prevBackend !== state.backendOnline) {
    if (state.backendOnline) {
      showNotification("Backend Connected", "success");
    } else {
      showNotification("Backend Lost", "error");
    }
  }

  // --- Telemetry ---
  const prevTelemetry = state.telemetryOnline;
  state.telemetryOnline = !!data.telemetry;
  if (dom.telemetryDot) {
    dom.telemetryDot.className = `dot ${data.telemetry ? "online" : "offline"}`;
  }
  if (dom.telemetryStatusText) {
    dom.telemetryStatusText.textContent = data.telemetry
      ? "Telemetry OK"
      : "Telemetry Lost";
  }

  if (prevTelemetry !== null && prevTelemetry !== state.telemetryOnline) {
    if (state.telemetryOnline) {
      showNotification("Telemetry Restored", "success");
    } else {
      showNotification("Telemetry Lost", "error");
    }
  }

  // --- Stream ---
  // Video status must never be driven by video code itself (req. 6) — only
  // /health is authoritative. If the stream just came back online, reload
  // the iframe automatically so MediaMTX restarts are picked up.
  const prevStream = state.streamOnline;
  state.streamOnline = !!data.stream;
  if (prevStream === false && state.streamOnline === true) {
    applyVideoStream();
    if (PROCESSED_STREAM_URL) applyProcessedVideoStream(); // NEW FEATURE
  }
}

/**
 * Update telemetry dashboard cards from /telemetry response.
 */
function updateTelemetryUI(data) {
  if (!data) {
    // Telemetry unavailable — show placeholder values
    dom.telConnection.textContent = "Unavailable";
    dom.telConnection.className = "t-value alert";
    [
      dom.telMode, dom.telArmed, dom.telAltitude, dom.telHeading,
      dom.telGroundspeed, dom.telClimb, dom.telBatteryPct,
      dom.telBatteryVoltage, dom.telGpsFix, dom.telSatellites,
      dom.telLatitude, dom.telLongitude,
    ].forEach((el) => {
      el.textContent = "--";
      el.className = "t-value";
    });
    return;
  }

  // Connection
  const connected = !!data.connected;
  dom.telConnection.textContent = connected ? "Connected" : "Disconnected";
  dom.telConnection.className = `t-value ${connected ? "ok" : "alert"}`;

  // Flight data
  dom.telMode.textContent = data.mode ?? "--";
  dom.telArmed.textContent = data.armed ? "ARMED" : "DISARMED";
  dom.telArmed.className = `t-value ${data.armed ? "alert" : "ok"}`;
  dom.telAltitude.textContent = formatNumber(data.altitude, "m");
  dom.telHeading.textContent = formatNumber(data.heading, "°");
  dom.telGroundspeed.textContent = formatNumber(data.groundspeed, "m/s");
  dom.telClimb.textContent = formatNumber(data.climb, "m/s");

  // Battery
  dom.telBatteryPct.textContent =
    data.battery_remaining != null ? `${data.battery_remaining}%` : "--";
  dom.telBatteryPct.className = `t-value ${
    data.battery_remaining != null && data.battery_remaining < 20 ? "alert" : ""
  }`;
  dom.telBatteryVoltage.textContent = formatNumber(data.battery_voltage, "V");

  // GPS
  dom.telGpsFix.textContent = data.gps_fix != null ? data.gps_fix : "--";
  dom.telSatellites.textContent =
    data.satellites != null ? data.satellites : "--";
  dom.telLatitude.textContent =
    data.latitude != null ? data.latitude.toFixed(6) : "--";
  dom.telLongitude.textContent =
    data.longitude != null ? data.longitude.toFixed(6) : "--";
}

/**
 * Update mission status card and topbar pill from /missions/status response.
 * Runtime is calculated from the backend's started_at field.
 */
function updateMissionUI(data) {
  if (!data) return;

  // Backend contract: status / container_name / pid / returncode.
  // There is no "running" field — derive it from status.
  const running = data.status === "running";
  const wasRunning = state.missionRunning;
  state.missionRunning = running;

  // Topbar mission status pill
  dom.missionStatusText.textContent = running
    ? "Mission Running"
    : "Mission Idle";
  dom.missionDot.className = `dot ${running ? "online" : ""}`;

  // Mission status card — only display fields the backend actually sends.
  dom.msState.textContent = running ? "Running" : "Stopped";
  dom.msMissionId.textContent = data.mission_id ?? "--";
  dom.msModel.textContent = data.model ?? "--";
  dom.msPrompt.textContent = data.prompt ?? "--";

  // Calculate runtime from backend's started_at timestamp
  if (running && data.started_at) {
    dom.msRuntime.textContent = formatRuntime(data.started_at);
  } else {
    dom.msRuntime.textContent = "--";
  }

  // State-change notifications (only after initial load)
  if (wasRunning !== null && wasRunning !== running) {
    if (running) {
      showNotification("Mission Started", "success");
    } else {
      showNotification("Mission Stopped", "success");
    }
  }
}

/**
 * Update latest detection and detection gallery from /results/latest response.
 * Handles both array and single-object responses for backward compatibility.
 */
function updateResultsUI(data) {
  // Normalize: backend may return an array or a single object
  const results = Array.isArray(data) ? data : data ? [data] : [];
  const latest = results.length > 0 ? results[0] : null;

  // --- Update Latest Detection ---
  if (!latest || !latest.image) {
    dom.detectionImage.classList.remove("active");
    dom.detectionPlaceholder.style.display = "flex";
    dom.detectionPlaceholder.textContent = "Waiting for Detection...";
    dom.detConfidence.textContent = "--";
    if (dom.detSimilarity) dom.detSimilarity.textContent = "--";
    dom.detMissionId.textContent = "--";
    dom.detPrompt.textContent = "--";
    dom.detTimestamp.textContent = "--";
    dom.detBbox.textContent = "--";
    if (dom.detFrameNumber) dom.detFrameNumber.textContent = "--";
    if (dom.detModel) dom.detModel.textContent = "--";
    dom.detRefresh.textContent = new Date().toLocaleTimeString();
    updateGallery([]);
    return;
  }

  // Construct image URL with cache-busting
  const imageUrl = buildImageUrl(latest.image);
  dom.detectionImage.src = imageUrl;
  dom.detectionImage.classList.add("active");
  dom.detectionPlaceholder.style.display = "none";

  // Backend contract guarantees 'confidence' on every result.
  const confidence = latest.confidence;
  dom.detConfidence.textContent =
    confidence != null ? `${(confidence * 100).toFixed(1)}%` : "--";
  // NEW FEATURE: Similarity Score — only rendered if backend supplies it,
  // never fabricated.
  if (dom.detSimilarity) {
    const sim = latest.similarity_score ?? latest.similarity;
    dom.detSimilarity.textContent = sim != null ? `${(Number(sim) * 100).toFixed(1)}%` : "--";
  }
  dom.detMissionId.textContent = latest.mission_id ?? "--";
  dom.detPrompt.textContent = latest.prompt ?? "--";
  dom.detTimestamp.textContent = latest.timestamp ?? "--";
  dom.detBbox.textContent = latest.bbox
    ? JSON.stringify(latest.bbox)
    : "--";
  // NEW FEATURE — Detection Results Panel (Task 2): frame number + model,
  // shown only if the backend includes them (never fabricated).
  if (dom.detFrameNumber) dom.detFrameNumber.textContent = latest.frame_number ?? "--";
  if (dom.detModel) dom.detModel.textContent = latest.model ?? "--";
  dom.detRefresh.textContent = new Date().toLocaleTimeString();

  // --- Update Detection History (gallery) ---
  // NEW FEATURE: exactly one featured thumbnail — the newest detection,
  // shown large above. The gallery below shows every other detection
  // (no artificial cap), scrollable.
  updateGallery(results.slice(1));
}

/**
 * Populate the detection history gallery with thumbnail images.
 * Each thumbnail shows Mission ID, Confidence, and Timestamp, and is
 * clickable to open the extended popup.
 */
function updateGallery(results) {
  if (!dom.detectionGallery) return;
  dom.detectionGallery.innerHTML = "";

  if (!results.length) {
    const empty = document.createElement("div");
    empty.className = "gallery-empty";
    empty.textContent = "No earlier detections yet.";
    dom.detectionGallery.appendChild(empty);
    return;
  }

  results.forEach((result, index) => {
    if (!result || !result.image) return;

    const item = document.createElement("div");
    item.className = "gallery-item";
    item.addEventListener("click", () => openPopup(result));
    item.title = `Detection ${index + 1}`;

    const img = document.createElement("img");
    img.src = buildImageUrl(result.image);
    img.alt = `Detection ${index + 1}`;
    img.loading = "lazy";
    item.appendChild(img);

    // Confidence badge overlay
    const conf = result.confidence;
    if (conf != null) {
      const badge = document.createElement("span");
      badge.className = "gallery-confidence";
      badge.textContent = `${(conf * 100).toFixed(1)}%`;
      item.appendChild(badge);
    }

    // Mission badge overlay
    if (result.mission_id != null) {
      const missionBadge = document.createElement("span");
      missionBadge.className = "gallery-mission-badge";
      missionBadge.textContent = `#${result.mission_id}`;
      item.appendChild(missionBadge);
    }

    // NEW FEATURE: timestamp badge, shown only if backend provides it
    if (result.timestamp) {
      const tsBadge = document.createElement("span");
      tsBadge.className = "gallery-timestamp";
      tsBadge.textContent = result.timestamp;
      item.appendChild(tsBadge);
    }

    dom.detectionGallery.appendChild(item);
  });
}

/**
 * =====================================================================
 * NEW FEATURE — Engineering Log Classification (Task 5)
 * =====================================================================
 * Classifies each raw log line into a category (SYSTEM/MISSION/VIDEO/AI/
 * DETECTION/WARNING/ERROR) using keyword matching, and renders an icon +
 * color-coded entry. Decoder warnings are intentionally classified as
 * WARNING, not ERROR, so they don't read as fatal. /logs/latest already
 * returns newest-first, so entries are appended in that order (newest
 * stays on top) without needing to reverse anything here.
 */
const LOG_CATEGORIES = [
  { key: "ERROR",     icon: "\u26D4", test: /\berror\b|\bexception\b|\btraceback\b|\bfatal\b|\bfailed to\b/i },
  { key: "WARNING",   icon: "\u26A0\uFE0F", test: /\bwarn(ing)?\b|\breconnect\b|\bdecoder reset\b|\bretry\b/i },
  { key: "DETECTION", icon: "\uD83C\uDFAF", test: /\bdetection\b|\bconfidence\b|\bmatch(ed)?\b|\bbounding box\b/i },
  { key: "AI",        icon: "\uD83E\uDD16", test: /\binference\b|\bmodel\b|\bfeature\b|\bembedding\b|\bre-id\b/i },
  { key: "VIDEO",     icon: "\uD83D\uDCF9", test: /\brtsp\b|\bframe\b|\bstream\b|\bcamera\b|\bcodec\b/i },
  { key: "MISSION",   icon: "\uD83D\uDEEB", test: /\bmission\b|\baltitude\b|\btelemetry\b/i },
  { key: "SYSTEM",    icon: "\u2699\uFE0F", test: /\bdocker\b|\bcontainer\b|\bstartup\b|\bshutdown\b/i },
];

function classifyLogLine(line) {
  for (const cat of LOG_CATEGORIES) {
    if (cat.test.test(line)) return cat;
  }
  return { key: "SYSTEM", icon: "\u2699\uFE0F" };
}

function updateLogsUI(logs) {
  if (!dom.engineeringLog) return;

  // Only auto-scroll to top if the user hasn't scrolled down to read
  // older entries — avoids yanking the view away mid-read (Task 5).
  const wasAtTop = dom.engineeringLog.scrollTop <= 4;

  dom.engineeringLog.innerHTML = "";

  if (!logs || logs.length === 0) {
    const empty = document.createElement("div");
    empty.className = "log-entry";
    empty.textContent = "No log entries available.";
    dom.engineeringLog.appendChild(empty);
    return;
  }

  let lastLine = null;
  logs.forEach((line) => {
    if (line === lastLine) return; // skip duplicate consecutive entries
    lastLine = line;

    const category = classifyLogLine(line);
    const entry = document.createElement("div");
    entry.className = `log-entry log-${category.key.toLowerCase()}`;
    entry.innerHTML =
      `<span class="log-icon">${category.icon}</span>` +
      `<span class="log-tag">${category.key}</span>` +
      `<span class="log-text"></span>`;
    entry.querySelector(".log-text").textContent = line; // textContent avoids HTML injection
    dom.engineeringLog.appendChild(entry);
  });

  if (wasAtTop) dom.engineeringLog.scrollTop = 0;
}

// =========================================================================
// VIDEO STREAM
// =========================================================================

/**
 * Apply the video stream URL to the iframe.
 * The stream is served by MediaMTX over WebRTC (WHEP) and is only
 * embeddable as a page (iframe), not as an <img> source.
 * Manages Loading, Connected, Disconnected, and Reconnecting states.
 *
 * NEW FEATURE — automatic reconnect with backoff: if a connection attempt
 * times out, the stream retries on its own (5s, 10s, 15s... capped at 20s)
 * without any page refresh, showing a "Reconnecting (attempt N)" indicator
 * until it succeeds or the stream URL is cleared.
 */
let videoLoadTimeout = null;
let videoRetryTimer = null;
let videoRetryCount = 0;
const MAX_RETRY_DELAY_MS = 20000;
const BASE_RETRY_DELAY_MS = 5000;

function applyVideoStream() {
  clearTimeout(videoLoadTimeout);
  clearTimeout(videoRetryTimer);

  if (!VIDEO_STREAM_URL) {
    dom.videoFrame.removeAttribute("src");
    state.videoConnected = false;
    videoRetryCount = 0;
    setVideoState("disconnected", "No Video Source");
    return;
  }

  state.videoConnected = false;
  setVideoState(videoRetryCount > 0 ? "reconnecting" : "loading",
    videoRetryCount > 0 ? `Reconnecting (attempt ${videoRetryCount})...` : "Connecting...");

  // Cache-bust on every apply so a reconnect (e.g. after MediaMTX restarts)
  // forces a real iframe reload instead of being a no-op same-src assignment.
  const sep = VIDEO_STREAM_URL.includes("?") ? "&" : "?";
  dom.videoFrame.src = `${VIDEO_STREAM_URL}${sep}_t=${Date.now()}`;

  // iframe.onload only confirms the MediaMTX page itself loaded, not that
  // video frames are flowing — but it's the only signal available across
  // the cross-origin WHEP boundary. If it never fires, surface "Stream
  // Unavailable" and automatically schedule a retry.
  videoLoadTimeout = setTimeout(() => {
    if (!state.videoConnected) {
      setVideoState("error", "Stream Unavailable — retrying...");
      videoRetryCount += 1;
      const delay = Math.min(BASE_RETRY_DELAY_MS * videoRetryCount, MAX_RETRY_DELAY_MS);
      videoRetryTimer = setTimeout(applyVideoStream, delay);
    }
  }, 8000);

  dom.videoFrame.onload = () => {
    clearTimeout(videoLoadTimeout);
    clearTimeout(videoRetryTimer);
    state.videoConnected = true;
    videoRetryCount = 0;
    setVideoState("connected", "Connected");
    dom.videoLastFrame.textContent = new Date().toLocaleTimeString();
  };
}

/**
 * NEW FEATURE — Dual Live Stream Panel (Task 1)
 * Applies the processed AI stream (bounding boxes / confidence / rank),
 * mirroring applyVideoStream()'s connection lifecycle including automatic
 * reconnect with backoff. If the backend doesn't provide a processed
 * stream URL, shows a clear unavailable message instead of a broken iframe.
 */
let processedLoadTimeout = null;
let processedRetryTimer = null;
let processedRetryCount = 0;

function applyProcessedVideoStream() {
  if (!dom.processedFrame) return;
  clearTimeout(processedLoadTimeout);
  clearTimeout(processedRetryTimer);

  if (!PROCESSED_STREAM_URL) {
    dom.processedFrame.removeAttribute("src");
    processedRetryCount = 0;
    setProcessedVideoState("disconnected", "Processed AI stream unavailable");
    return;
  }

  setProcessedVideoState(processedRetryCount > 0 ? "reconnecting" : "loading",
    processedRetryCount > 0 ? `Reconnecting (attempt ${processedRetryCount})...` : "Connecting...");

  const sep = PROCESSED_STREAM_URL.includes("?") ? "&" : "?";
  dom.processedFrame.src = `${PROCESSED_STREAM_URL}${sep}_t=${Date.now()}`;

  processedLoadTimeout = setTimeout(() => {
    setProcessedVideoState("error", "Processed AI stream unavailable — retrying...");
    processedRetryCount += 1;
    const delay = Math.min(BASE_RETRY_DELAY_MS * processedRetryCount, MAX_RETRY_DELAY_MS);
    processedRetryTimer = setTimeout(applyProcessedVideoStream, delay);
  }, 8000);

  dom.processedFrame.onload = () => {
    clearTimeout(processedLoadTimeout);
    clearTimeout(processedRetryTimer);
    processedRetryCount = 0;
    setProcessedVideoState("connected", "Connected");
  };
}

function setProcessedVideoState(status, label) {
  if (!dom.processedFrame) return;
  state.processedConnected = status === "connected";
  const dotClass = status === "connected" ? "online" :
    (status === "loading" || status === "reconnecting") ? "warning" : "offline";
  if (dom.processedConnDot) dom.processedConnDot.className = `dot ${dotClass}`;
  if (dom.processedConnectionIndicator) {
    const textNode = dom.processedConnectionIndicator.childNodes[dom.processedConnectionIndicator.childNodes.length - 1];
    if (textNode) textNode.textContent = ` ${label}`;
  }
  if (dom.processedStreamStatus) dom.processedStreamStatus.textContent = label;

  // NEW FEATURE: spinner only visible while actively connecting/reconnecting
  if (dom.processedSpinner) {
    dom.processedSpinner.style.display = (status === "loading" || status === "reconnecting") ? "block" : "none";
  }

  if (status === "connected") {
    dom.processedFrame.classList.add("active");
    if (dom.processedPlaceholder) dom.processedPlaceholder.style.display = "none";
  } else {
    dom.processedFrame.classList.remove("active");
    if (dom.processedPlaceholder) {
      dom.processedPlaceholder.style.display = "flex";
      dom.processedPlaceholder.textContent = label;
    }
  }
}

/**
 * Update video panel visual state.
 * @param {"connected"|"disconnected"|"loading"|"reconnecting"|"error"} status
 * @param {string} label - Text shown in overlay and metadata
 */
function setVideoState(status, label) {
  const dotClass =
    status === "connected" ? "online" :
    (status === "loading" || status === "reconnecting") ? "warning" :
    "offline";

  dom.videoConnDot.className = `dot ${dotClass}`;

  // Update overlay text (the text node after the dot span)
  const indicator = dom.videoConnectionIndicator;
  if (indicator) {
    // Keep the dot span, replace only the text
    const textNode = indicator.childNodes[indicator.childNodes.length - 1];
    if (textNode) textNode.textContent = ` ${label}`;
  }

  dom.videoStreamStatus.textContent = label;

  // NEW FEATURE: spinner only visible while actively connecting/reconnecting
  if (dom.videoSpinner) {
    dom.videoSpinner.style.display = (status === "loading" || status === "reconnecting") ? "block" : "none";
  }

  if (status === "connected") {
    dom.videoFrame.classList.add("active");
    dom.videoPlaceholder.style.display = "none";
  } else {
    dom.videoFrame.classList.remove("active");
    dom.videoPlaceholder.style.display = "flex";
    dom.videoPlaceholder.textContent =
      (status === "loading" || status === "reconnecting") ? "Connecting to stream..." :
      status === "error" ? "Stream Unavailable" :
      "No Video Source Configured";
  }
}

// =========================================================================
// IMAGE POPUP
// =========================================================================

/**
 * Open the full-image popup for a detection result.
 */
function openPopup(result) {
  if (!dom.imagePopup || !result) return;

  const imageUrl = buildImageUrl(result.image);
  dom.popupImage.src = imageUrl;

  const confidence = result.confidence;
  const sim = result.similarity_score ?? result.similarity;
  dom.popupDetails.innerHTML = [
    statusRow("Mission ID", result.mission_id ?? "--"),
    statusRow("Prompt", result.prompt ?? "--"),
    statusRow("Confidence", confidence != null ? `${(confidence * 100).toFixed(1)}%` : "--"),
    statusRow("Similarity Score", sim != null ? `${(Number(sim) * 100).toFixed(1)}%` : "--"),
    statusRow("Bounding Box", result.bbox ? JSON.stringify(result.bbox) : "--"),
    statusRow("Timestamp", result.timestamp ?? "--"),
    // NEW FEATURE: Frame Number + Model Name in the extended popup
    statusRow("Frame Number", result.frame_number ?? "--"),
    statusRow("Model", result.model ?? "--"),
  ].join("");

  // NEW FEATURE: Download button — links directly to the full-size image
  if (dom.popupDownload) {
    dom.popupDownload.href = imageUrl;
    const missionPart = result.mission_id != null ? `mission${result.mission_id}_` : "";
    const framePart = result.frame_number != null ? `frame${result.frame_number}` : Date.now();
    dom.popupDownload.setAttribute("download", `detection_${missionPart}${framePart}.jpg`);
  }

  dom.imagePopup.style.display = "flex";
}

/**
 * Close the image popup.
 */
function closePopup() {
  if (!dom.imagePopup) return;
  dom.imagePopup.style.display = "none";
}

/**
 * Helper: build a status-row HTML string for the popup.
 */
function statusRow(label, value) {
  return `<div class="status-row"><span>${label}</span><span>${value}</span></div>`;
}

// =========================================================================
// NOTIFICATIONS
// =========================================================================

/**
 * Show a toast notification that auto-hides after 4 seconds.
 * @param {string} message
 * @param {"success"|"error"|"warning"|"info"} type
 */
function showNotification(message, type = "info") {
  const note = document.createElement("div");
  note.className = `notification ${type}`;
  note.textContent = message;
  dom.notificationArea.appendChild(note);

  setTimeout(() => {
    // Slide-out animation before removal
    note.style.opacity = "0";
    note.style.transform = "translateX(20px)";
    note.style.transition = "opacity 0.3s ease, transform 0.3s ease";
    setTimeout(() => note.remove(), 300);
  }, 4000);
}

// =========================================================================
// HELPERS
// =========================================================================

/**
 * Format a numeric value with a unit string.
 * Returns "--" if the value is null or NaN.
 */
function formatNumber(value, unit) {
  if (value == null || isNaN(value)) return "--";
  return `${Number(value).toFixed(1)} ${unit}`;
}

/**
 * Calculate a human-readable runtime string from an ISO timestamp.
 * Returns HH:MM:SS format.
 */
function formatRuntime(startTimeIso) {
  if (!startTimeIso) return "--";
  const start = new Date(startTimeIso).getTime();
  if (isNaN(start)) return "--";
  const seconds = Math.max(0, Math.floor((Date.now() - start) / 1000));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

/**
 * Build a full image URL with cache-busting query parameter.
 * Handles absolute URLs, root-relative paths, and bare paths.
 * Uses API_BASE_URL as the base for relative paths.
 */
function buildImageUrl(imagePath) {
  if (!imagePath) return "";

  // Already a full URL — just append cache-buster
  if (imagePath.startsWith("http://") || imagePath.startsWith("https://")) {
    const sep = imagePath.includes("?") ? "&" : "?";
    return `${imagePath}${sep}t=${Date.now()}`;
  }

  // Relative path — prefix with API_BASE_URL
  const base = API_BASE_URL.replace(/\/+$/, "");
  const path = imagePath.startsWith("/") ? imagePath : `/${imagePath}`;
  return `${base}${path}?t=${Date.now()}`;
}

// =========================================================================
// ENTRY POINT
// =========================================================================

document.addEventListener("DOMContentLoaded", initialize);
