// =========================================================================
// SHARED CONFIGURATION â€” config.js
// =====================================================================
// NEW FEATURE
// Shared config module â€” single source of truth for API_BASE_URL and
// polling intervals, previously duplicated in script.js and mission.js.
// Must load BEFORE mission.js and script.js.
// =====================================================================
window.GCS_CONFIG = {
  API_BASE_URL: "http://localhost:5002",
  // T1/T2 IIT Bombay (CORTEX) UI. A directly opened index.html has no
  // hostname and uses file:, so fall back to the local HTTP service.
  CORTEX_URL: `${
    window.location.protocol === "file:" ? "http:" : window.location.protocol
  }//${window.location.hostname || "localhost"}:3000`,

  // Polling intervals (ms). Unchanged from previous values (Task 11).
  REFRESH_INTERVALS: {
    health: 3000,
    telemetry: 1000,
    missionStatus: 1000,
    missionState: 1000,
    results: 2000,
    logs: 2000,
    stream: 5000, // NEW FEATURE: periodic refresh of /stream for live video stats
  },
};
