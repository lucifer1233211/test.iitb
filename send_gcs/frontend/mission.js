// =========================================================================
// MISSION CONTROL PANEL � frontend/mission.js  (v2 � refinement pass)
// =========================================================================
// Polls GET /mission/state and drives the Mission Control card.
// Self-contained: does not read or modify any state/DOM owned by script.js.
// Only startMissionPolling()/stopMissionPolling() are exposed globally.
// =========================================================================

(function () {
  "use strict";

  // ---------------------------------------------------------------------
  // Frontend Integration Improvement: shared config (Task 10) — pulls
  // API_BASE_URL and the poll interval from config.js instead of
  // redeclaring them here.
  // ---------------------------------------------------------------------
  const API_BASE_URL = (window.GCS_CONFIG && window.GCS_CONFIG.API_BASE_URL) || "http://10.51.26.15:5002";
  const POLL_INTERVAL_MS = (window.GCS_CONFIG && window.GCS_CONFIG.REFRESH_INTERVALS.missionState) || 1000;

  let pollHandle = null;

  // -----------------------------------------------------------------------
  // NEW FEATURE — Mission Timeline
  // Derives a chronological event log purely from stage transitions already
  // present in /mission/state. No backend changes required. Events are
  // recorded the first time a stage is seen during a mission run, then the
  // seen-set resets once the mission returns to idle/stopped so the next
  // run starts a fresh timeline.
  // -----------------------------------------------------------------------
  const TIMELINE_LABELS = {
    connecting_camera: "Camera Connected",
    loading_model: "Model Loaded",
    model_ready: "Model Loaded",
    initializing: "Mission Started",
    mission_started: "Mission Started",
    running: "Receiving Frames",
    inference_running: "Receiving Frames",
    searching: "Searching",
    target_detected: "Detection Found",
    tracking: "Detection Found",
    saving_detection: "Image Saved",
    completed: "Published Results",
    mission_completed: "Published Results",
  };
  let timelineEvents = [];
  let seenStages = new Set();

  function recordTimelineEvent(stageKey) {
    if (!stageKey || stageKey === "idle" || stageKey === "waiting" ||
        stageKey === "stopped" || stageKey === "mission_stopped") {
      seenStages.clear(); // next mission run starts a fresh timeline
      return;
    }
    if (seenStages.has(stageKey)) return;
    seenStages.add(stageKey);

    const label = TIMELINE_LABELS[stageKey];
    if (!label) return;
    const last = timelineEvents[timelineEvents.length - 1];
    if (last && last.label === label) return; // avoid consecutive duplicates

    timelineEvents.push({ label, time: new Date() });
    if (timelineEvents.length > 20) timelineEvents.shift();
    renderTimeline();
  }

  function renderTimeline() {
    const el = $("mcTimeline");
    if (!el) return;
    if (!timelineEvents.length) {
      el.innerHTML = '<div class="mc-timeline-empty">No mission events yet.</div>';
      return;
    }
    el.innerHTML = timelineEvents.map(ev =>
      `<div class="mc-timeline-item">
        <span class="mc-timeline-dot"></span>
        <span class="mc-timeline-label">${ev.label}</span>
        <span class="mc-timeline-time">${ev.time.toLocaleTimeString()}</span>
      </div>`
    ).join("");
  }

  // -----------------------------------------------------------------------
  // STAGE METADATA
  // -----------------------------------------------------------------------
  const STAGE_CONFIG = {
    idle: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Waiting", pipelineStage: 0,
      desc: "System idle. Waiting for operator to configure and start a mission.",
      activity: "Standing by.",
      next: "Mission Initialization"
    },
    waiting: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Waiting", pipelineStage: 0,
      desc: "System idle. Waiting for operator to configure and start a mission.",
      activity: "Standing by.",
      next: "Mission Initialization"
    },
    connecting_camera: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Connecting Camera", pipelineStage: 1,
      desc: "Establishing connection to the onboard video source over RTSP.",
      activity: "Opening RTSP stream and verifying frame delivery.",
      next: "AI Model Loading"
    },
    loading_model: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Loading AI Model", pipelineStage: 2,
      desc: "Initializing the Person Re-ID neural network and loading model weights into memory.",
      activity: "Loading model weights into inference engine.",
      next: "Inference Start"
    },
    model_ready: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Model Ready", pipelineStage: 2,
      desc: "AI model initialized and ready for real-time inference.",
      activity: "Model ready. Awaiting first frame.",
      next: "Inference Running"
    },
    initializing: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Mission Initializing", pipelineStage: 2,
      desc: "Mission configuration verified. Building inference pipeline.",
      activity: "Preparing mission pipeline.",
      next: "Inference Running"
    },
    mission_started: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Mission Started", pipelineStage: 2,
      desc: "Mission configuration complete. Pipeline building.",
      activity: "Preparing mission pipeline.",
      next: "Inference Running"
    },
    running: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Inference Running", pipelineStage: 3,
      desc: "Receiving live frames from the RTSP stream and passing them to the AI model.",
      activity: "Decoding incoming video frames.",
      next: "Target Detection"
    },
    inference_running: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Inference Running", pipelineStage: 3,
      desc: "Receiving live frames from the RTSP stream and passing them to the AI model.",
      activity: "Decoding incoming video frames.",
      next: "Target Detection"
    },
    searching: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Searching for Target", pipelineStage: 4,
      desc: "Processing every incoming frame, extracting visual features and comparing them against the requested target description.",
      activity: null, // generated dynamically with prompt
      next: "Target Detection"
    },
    target_detected: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Target Detected", pipelineStage: 5,
      desc: "A potential target match has been identified. Verifying match quality.",
      activity: "Verifying detected match against prompt criteria.",
      next: "Save Detection"
    },
    tracking: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Tracking Target", pipelineStage: 5,
      desc: "Maintaining a continuous lock on the identified target across incoming frames.",
      activity: "Maintaining lock on tracked target.",
      next: "Detection Save"
    },
    saving_detection: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Saving Detection", pipelineStage: 6,
      desc: "Writing detection image, bounding box coordinates and confidence score to persistent storage.",
      activity: "Writing detection record to disk.",
      next: "Publishing Results"
    },
    completed: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Mission Completed", pipelineStage: 8,
      desc: "Mission finished successfully. All results have been saved.",
      activity: "Mission complete.",
      next: "�"
    },
    mission_completed: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Mission Completed", pipelineStage: 8,
      desc: "Mission finished successfully. All results have been saved.",
      activity: "Mission complete.",
      next: "�"
    },
    stopped: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Mission Stopped", pipelineStage: 0,
      desc: "Mission was terminated by the operator.",
      activity: "Mission stopped.",
      next: "�"
    },
    mission_stopped: {
      icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Mission Stopped", pipelineStage: 0,
      desc: "Mission was terminated by the operator.",
      activity: "Mission stopped.",
      next: "�"
    },
  };
  const DEFAULT_STAGE = {
    icon: '<i class="fa-solid fa-circle-dot"></i>', title: "Unknown Stage", pipelineStage: -1,
    desc: "Mission stage in progress.", activity: "Processing...", next: "Unknown"
  };

  // AI Pipeline steps � index matches pipelineStage in STAGE_CONFIG
  const PIPELINE_STEPS = [
    "Receiving RTSP Frames",
    "Connecting Camera",
    "Loading AI Model",
    "Decoding Video Stream",
    "Running Person Re-ID & Feature Extraction",
    "Similarity Comparison & Detection Decision",
    "Saving Detection Image",
    "Publishing Results",
    "Mission Complete",
  ];

  function $(id) { return document.getElementById(id); }

  function normalizeStage(stage) {
    return String(stage || "idle").trim().toLowerCase().replace(/[\s-]+/g, "_");
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  }

  async function fetchMissionState() {
    const response = await fetch(`${API_BASE_URL}/mission/state`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  // -----------------------------------------------------------------------
  // HEALTH / CONNECTION STATUS
  // -----------------------------------------------------------------------
  function setIndicator(prefix, connected, onLabel, offLabel) {
    const icon = $(`${prefix}Icon`);
    const text = $(`${prefix}Text`);
    if (!icon || !text) return;
    if (connected === null) {
      icon.textContent = "?";
      text.textContent = "Unknown";
      return;
    }
    icon.innerHTML = connected ? '<i class="fa-solid fa-check-circle" style="color:var(--success)"></i>' : '<i class="fa-solid fa-times-circle" style="color:var(--danger)"></i>';
    text.textContent = connected ? onLabel : offLabel;
  }

  function renderConnectionStatus(data, offline) {
    const banner = $("mcOfflineBanner");
    if (banner) banner.classList.toggle("active", !!offline);

    if (offline || !data) {
      setIndicator("mcBackend",   false, "Operational",           "Backend Offline");
      setIndicator("mcCamera",    false, "Live Feed Available",   "No Feed");
      setIndicator("mcTelemetry", false, "Receiving Flight Data", "No Signal");
      setIndicator("mcStream",    false, "Streaming Frames",      "RTSP Offline");
      setIndicator("mcMission",   false, "Mission Running",       "Mission Unavailable");
      return;
    }

    setIndicator("mcBackend",   !!data.backend_connected,   "Operational",           "Backend Offline");
    setIndicator("mcCamera",    !!data.camera_connected,    "Live Feed Available",   "No Feed");
    setIndicator("mcTelemetry", !!data.telemetry_connected, "Receiving Flight Data", "No Signal");
    setIndicator("mcStream",    !!data.stream_connected,    "Streaming Frames",      "RTSP Offline");

    const missionIcon = $("mcMissionIcon");
    const missionText = $("mcMissionText");
    if (missionIcon && missionText) {
      if (data.status === "running") {
        missionIcon.innerHTML = '<i class="fa-solid fa-circle-play" style="color:var(--success)"></i>'; missionText.textContent = "Running";
      } else if (data.status === "stopped") {
        missionIcon.innerHTML = '<i class="fa-solid fa-circle-stop" style="color:var(--danger)"></i>'; missionText.textContent = "Stopped";
      } else {
        missionIcon.innerHTML = '<i class="fa-solid fa-circle-pause" style="color:var(--text-muted)"></i>'; missionText.textContent = "Idle";
      }
    }
  }

  // -----------------------------------------------------------------------
  // MISSION PROGRESS
  // -----------------------------------------------------------------------
  function renderMissionProgress(data) {
    const stageKey = normalizeStage(data && data.stage);
    const config = STAGE_CONFIG[stageKey] || DEFAULT_STAGE;
    const progress = data ? Math.max(0, Math.min(100, Number(data.progress) || 0)) : 0;
    const isComplete = progress >= 100;

    if ($("mcStageIcon")) $("mcStageIcon").innerHTML = config.icon;
    if ($("mcStageTitle")) $("mcStageTitle").textContent = config.title;
    if ($("mcProgressFill")) $("mcProgressFill").style.width = `${progress}%`;
    if ($("mcProgressPercent")) $("mcProgressPercent").textContent = `${progress.toFixed(0)}%`;

    // Target prompt
    const prompt = (data && data.prompt) || "�";
    if ($("mcTargetPrompt")) $("mcTargetPrompt").textContent = prompt;

    // Stage explanation � swap for completion summary if done
    if (isComplete && data) {
      const stats = data.stats || {};
      if ($("mcStageExplanation")) {
        $("mcStageExplanation").innerHTML =
          `<strong>? Mission Completed Successfully</strong><br>` +
          `Runtime: ${formatDuration(data.runtime)} � ` +
          `Frames: ${data.frames_processed ?? "--"} � ` +
          `Detections: ${data.detections ?? "--"} � ` +
          `Avg FPS: ${stats.average_fps != null ? Number(stats.average_fps).toFixed(1) : "--"} � ` +
          `Confidence: ${data.latest_confidence != null ? (Number(data.latest_confidence) * 100).toFixed(1) + "%" : "--"}`;
      }
      if ($("mcAiActivity")) $("mcAiActivity").textContent = "Mission complete. All results saved.";
      if ($("mcNextStep")) $("mcNextStep").textContent = "�";
    } else {
      if ($("mcStageExplanation")) $("mcStageExplanation").textContent = config.desc;

      let activity = config.activity;
      if (!activity) {
        activity = `Analyzing incoming frames for: "${prompt}"`;
      }
      if ($("mcAiActivity")) $("mcAiActivity").textContent = activity;
      if ($("mcNextStep")) $("mcNextStep").textContent = config.next || "�";
    }
  }

  // -----------------------------------------------------------------------
  // AI PIPELINE STATUS
  // NEW FEATURE: builds the pipeline DOM once, then on every poll only
  // toggles classNames on the steps/connectors whose state actually
  // changed — avoids recreating the entire DOM every polling cycle.
  // -----------------------------------------------------------------------
  let pipelineBuilt = false;
  let pipelineStepEls = [];
  let pipelineConnectorEls = [];
  let lastPipelineIdx = null;

  function buildPipelineDom(pipelineEl) {
    pipelineEl.innerHTML = PIPELINE_STEPS.map((label, i) => {
      const connector = i < PIPELINE_STEPS.length - 1
        ? `<div class="mc-pipe-connector" data-connector="${i}"></div>`
        : "";
      return `<div class="mc-pipe-step" data-step="${i}">
        <span class="mc-pipe-dot"></span>
        <span class="mc-pipe-label">${label}</span>
      </div>${connector}`;
    }).join("");
    pipelineStepEls = Array.from(pipelineEl.querySelectorAll("[data-step]"));
    pipelineConnectorEls = Array.from(pipelineEl.querySelectorAll("[data-connector]"));
    pipelineBuilt = true;
  }

  function renderPipeline(data) {
    const pipelineEl = $("mcPipeline");
    if (!pipelineEl) return;

    if (!pipelineBuilt) buildPipelineDom(pipelineEl);

    const stageKey = normalizeStage(data && data.stage);
    const config = STAGE_CONFIG[stageKey] || DEFAULT_STAGE;
    const currentIdx = config.pipelineStage;

    if (currentIdx === lastPipelineIdx) return; // nothing changed, skip DOM work
    lastPipelineIdx = currentIdx;

    pipelineStepEls.forEach((el, i) => {
      let cls = "mc-pipe-step";
      if (i < currentIdx) cls += " mc-pipe-done";
      else if (i === currentIdx) cls += " mc-pipe-active";
      el.className = cls;
    });
    pipelineConnectorEls.forEach((el, i) => {
      el.className = `mc-pipe-connector ${i < currentIdx ? "mc-pipe-connector-done" : ""}`;
    });
  }

  // -----------------------------------------------------------------------
  // TIMING
  // -----------------------------------------------------------------------
  function renderMissionTiming(data) {
    if (!data) {
      ["mcRuntime","mcStartTime","mcEta","mcCompletion","mcCurrentFps","mcAvgFps"].forEach(id => {
        if ($(id)) $(id).textContent = id === "mcEta" ? "Learning mission pace..." : "--";
      });
      return;
    }

    const progress = Math.max(0, Math.min(100, Number(data.progress) || 0));
    const runtime  = Number(data.runtime) || 0;
    const frames   = Number(data.frames_processed) || 0;
    const stats    = data.stats || {};

    if ($("mcRuntime"))   $("mcRuntime").textContent   = formatDuration(runtime);
    if ($("mcStartTime")) $("mcStartTime").textContent = data.mission_start_time
      ? new Date(data.mission_start_time * 1000).toLocaleTimeString() : "--";
    if ($("mcCurrentFps")) $("mcCurrentFps").textContent =
      data.fps != null ? `${Number(data.fps).toFixed(1)} fps` : "--";
    if ($("mcAvgFps")) $("mcAvgFps").textContent =
      stats.average_fps != null ? `${Number(stats.average_fps).toFixed(1)} fps` : "--";

    const etaEl        = $("mcEta");
    const completionEl = $("mcCompletion");

    if (progress >= 100) {
      if (etaEl)        etaEl.textContent        = "Complete";
      if (completionEl) completionEl.textContent = new Date().toLocaleTimeString();
    } else if (progress >= 15 && runtime >= 15 && frames >= 100) {
      const estimatedTotal = (runtime * 100) / progress;
      const remaining      = Math.max(0, estimatedTotal - runtime);
      if (etaEl)        etaEl.textContent        = `${formatDuration(remaining)} remaining`;
      if (completionEl) completionEl.textContent = new Date(Date.now() + remaining * 1000).toLocaleTimeString();
    } else {
      if (etaEl)        etaEl.textContent        = "Learning mission pace...";
      if (completionEl) completionEl.textContent = "--";
    }
  }

  // -----------------------------------------------------------------------
  // STATISTICS
  // -----------------------------------------------------------------------
  function renderMissionStatistics(data) {
    const IDS = ["mcStatPrompt","mcStatModel","mcStatMissionId","mcStatFrames",
                 "mcStatDetections","mcStatFps","mcStatAvgFps","mcStatConfidence",
                 "mcStatRuntime","mcStatDetRate"];
    if (!data) {
      IDS.forEach(id => { if ($(id)) $(id).textContent = "--"; });
      return;
    }

    const stats = data.stats || {};
    if ($("mcStatPrompt"))     $("mcStatPrompt").textContent     = data.prompt || "--";
    if ($("mcStatModel"))      $("mcStatModel").textContent      = data.model_name || "--";
    if ($("mcStatMissionId"))  $("mcStatMissionId").textContent  = data.mission_id || "--";
    if ($("mcStatFrames"))     $("mcStatFrames").textContent     = data.frames_processed ?? "--";
    if ($("mcStatDetections")) $("mcStatDetections").textContent = data.detections ?? "--";
    if ($("mcStatFps"))        $("mcStatFps").textContent        = stats.fps != null ? Number(stats.fps).toFixed(1) : "--";
    if ($("mcStatAvgFps"))     $("mcStatAvgFps").textContent     = stats.average_fps != null ? Number(stats.average_fps).toFixed(1) : "--";
    if ($("mcStatConfidence")) {
      $("mcStatConfidence").textContent =
        data.latest_confidence != null ? `${(Number(data.latest_confidence) * 100).toFixed(1)}%` : "--";
    }
    if ($("mcStatRuntime")) $("mcStatRuntime").textContent = formatDuration(data.runtime);

    // Detection rate (detections/min)
    if ($("mcStatDetRate")) {
      const runtime = Number(data.runtime) || 0;
      const dets    = Number(data.detections) || 0;
      $("mcStatDetRate").textContent =
        (runtime > 0 && dets > 0) ? `${((dets / runtime) * 60).toFixed(2)}/min` : "--";
    }
  }

  // -----------------------------------------------------------------------
  // COORDINATOR
  // -----------------------------------------------------------------------
  function updateMissionUI(data, offline = false) {
    renderConnectionStatus(data, offline);
    renderMissionProgress(data);
    renderPipeline(data);
    renderMissionTiming(data);
    renderMissionStatistics(data);
    // NEW FEATURE: only record timeline events from live, valid data —
    // skip while offline so a backend hiccup doesn't reset the timeline.
    if (!offline) recordTimelineEvent(normalizeStage(data && data.stage));
  }

  async function pollTick() {
    try {
      const data = await fetchMissionState();
      updateMissionUI(data, false);
    } catch (error) {
      updateMissionUI(null, true);
    }
  }

  function startMissionPolling() {
    if (pollHandle !== null) return;
    pollTick();
    pollHandle = setInterval(pollTick, POLL_INTERVAL_MS);
  }

  function stopMissionPolling() {
    if (pollHandle === null) return;
    clearInterval(pollHandle);
    pollHandle = null;
  }

  window.startMissionPolling = startMissionPolling;
  window.stopMissionPolling  = stopMissionPolling;
})();