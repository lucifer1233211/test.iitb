#!/bin/bash
# entrypoint.sh - Jetson Stream Manager container entrypoint.
#
# Starts MediaMTX, a self-healing FFmpeg relay watchdog, and the
# stream-mgr process/pipeline watchdog daemon, then hands off to the
# container's foreground command. All three background services are
# tracked by PID and cleanly signaled/reaped on container stop so the
# operator never has to manually restart anything or reboot the Jetson.
#
# UTF-8 throughout; safe to re-run (guards against duplicate FFmpeg/
# MediaMTX instances left over from an unclean previous exit).

set -e

echo "=================================================="
echo "  Jetson Stream Manager"
echo "=================================================="

# ------------------------------------------------------------------
# Config (overridable via environment - no hardcoded deployment
# assumptions beyond the defaults already baked into this image).
# ------------------------------------------------------------------
CAMERA_SOURCE="${CAMERA_SOURCE:-rtsp://192.168.144.25:8554/main.264}"
RELAY_TARGET="${RELAY_TARGET:-rtsp://localhost:8554/main}"
RELAY_RESTART_DELAY="${RELAY_RESTART_DELAY:-2}"
WATCHDOG_FRAME_TIMEOUT="${WATCHDOG_FRAME_TIMEOUT:-15}"
WATCHDOG_INTERVAL="${WATCHDOG_INTERVAL:-1}"

# MediaMTX API + readiness/publication-check tuning.
MEDIAMTX_API="${MEDIAMTX_API:-http://127.0.0.1:9997}"
MEDIAMTX_READY_TIMEOUT="${MEDIAMTX_READY_TIMEOUT:-30}"   # max wait for API to answer
PATH_READY_TIMEOUT="${PATH_READY_TIMEOUT:-15}"           # max time ffmpeg may run without "main" publishing
PATH_CHECK_INTERVAL="${PATH_CHECK_INTERVAL:-2}"

# Stream verification tuning (Section 4): a lone decoded frame can be a
# decoder fluke, so recovery requires FRAME_VERIFY_CONSECUTIVE consecutive
# non-empty decoded frames spanning at least FRAME_VERIFY_STABLE_S seconds
# before the relay is declared recovered.
FRAME_VERIFY_CONSECUTIVE="${FRAME_VERIFY_CONSECUTIVE:-3}"
FRAME_VERIFY_STABLE_S="${FRAME_VERIFY_STABLE_S:-2}"
FRAME_VERIFY_TIMEOUT="${FRAME_VERIFY_TIMEOUT:-8}"

# RTSP session cleanup (Section 3): how long to wait for MediaMTX to
# confirm the old publisher is actually gone before a new ffmpeg publisher
# is allowed to launch, so overlapping publishers can never race.
PUBLISHER_REMOVAL_TIMEOUT="${PUBLISHER_REMOVAL_TIMEOUT:-8}"

HAVE_CURL=1
command -v curl >/dev/null 2>&1 || HAVE_CURL=0

# jq gives robust JSON parsing (Section 3 of the hardening pass); the
# grep/cut parsing below is kept as an automatic fallback so a missing
# jq binary never breaks the watchdog - only degrades its parsing.
HAVE_JQ=1
command -v jq >/dev/null 2>&1 || HAVE_JQ=0

# Blocks until MediaMTX's HTTP API responds, or MEDIAMTX_READY_TIMEOUT
# elapses. Returns 1 on timeout/no-curl; caller decides whether that's fatal.
wait_for_mediamtx_api() {
    if [ "$HAVE_CURL" -eq 0 ]; then
        echo "[entrypoint] WARN: curl not available - cannot verify MediaMTX API readiness."
        return 1
    fi
    local waited=0
    while [ "$waited" -lt "$MEDIAMTX_READY_TIMEOUT" ]; do
        if curl -fsS -o /dev/null "$MEDIAMTX_API/v3/paths/list" 2>/dev/null; then
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    return 1
}

# Returns 0 if the "main" path is currently registered AND actively
# publishing (ready=true) in MediaMTX. Checking for the path *name* alone
# was a false-positive trap: MediaMTX can leave a stale path entry around
# (ready=false, source gone) right after a stall, which made the old
# check think the relay was fine when it wasn't.
path_is_published() {
    [ "$HAVE_CURL" -eq 1 ] || return 1
    local body
    body="$(curl -fsS "$MEDIAMTX_API/v3/paths/get/main" 2>/dev/null)" || return 1
    if [ "$HAVE_JQ" -eq 1 ]; then
        [ "$(echo "$body" | jq -r '.ready // false' 2>/dev/null)" = "true" ] && return 0
        return 1
    fi
    echo "$body" | grep -q '"ready":true'
}

# Echoes the current bytesReceived counter for "main", or nothing on failure.
# Used to catch a publisher that reports ready=true but has actually
# stopped moving bytes - the exact "everything's alive but frontend shows
# no stream" failure mode this script exists to catch.
path_bytes_received() {
    [ "$HAVE_CURL" -eq 1 ] || return 1
    local body
    body="$(curl -fsS "$MEDIAMTX_API/v3/paths/get/main" 2>/dev/null)" || return 1
    if [ "$HAVE_JQ" -eq 1 ]; then
        echo "$body" | jq -r '.bytesReceived // empty' 2>/dev/null && return 0
    fi
    echo "$body" | grep -o '"bytesReceived":[0-9]*' | head -1 | cut -d: -f2
}

# Same idea, output side. bytesReceived only proves ffmpeg->MediaMTX is
# moving bytes; a stall further downstream (e.g. MediaMTX stuck delivering
# to readers/WebRTC) can leave bytesReceived climbing while bytesSent is
# flat. Checking both sides is required to catch stalls on either leg.
path_bytes_sent() {
    [ "$HAVE_CURL" -eq 1 ] || return 1
    local body
    body="$(curl -fsS "$MEDIAMTX_API/v3/paths/get/main" 2>/dev/null)" || return 1
    if [ "$HAVE_JQ" -eq 1 ]; then
        echo "$body" | jq -r '.bytesSent // empty' 2>/dev/null && return 0
    fi
    echo "$body" | grep -o '"bytesSent":[0-9]*' | head -1 | cut -d: -f2
}

# Number of active readers currently attached to "main", across every
# reader protocol MediaMTX supports (RTSP, WebRTC, HLS, SRT, ...) - the
# API's "readers" array on a path already aggregates all of them, so one
# call covers every protocol without extra requests. This is the ONLY
# correct way to know whether anyone is consuming the stream.
#
# WHY THIS MATTERS: bytesSent is a function of both (a) MediaMTX having
# something to send and (b) someone asking for it. With zero readers,
# MediaMTX has nothing to push and bytesSent legitimately sits at zero
# forever - that is expected idle behaviour, not a stall. Only once a
# reader attaches does bytesSent become a meaningful health signal;
# treating it as one before that yields a false-positive "stall" purely
# because nobody happened to be watching.
#
# Always echoes an integer (defaults to 0 on any failure/parse miss) so
# callers can safely do arithmetic/comparisons without extra guards.
path_subscriber_count() {
    if [ "$HAVE_CURL" -eq 0 ]; then
        echo 0
        return
    fi
    local body
    body="$(curl -fsS "$MEDIAMTX_API/v3/paths/get/main" 2>/dev/null)" || { echo 0; return; }
    if [ "$HAVE_JQ" -eq 1 ]; then
        local n
        n="$(echo "$body" | jq -r '(.readers // []) | length' 2>/dev/null)"
        if [ -n "$n" ] && [ "$n" -eq "$n" ] 2>/dev/null; then
            echo "$n"
            return
        fi
    fi
    # Fallback: no jq (or it failed to parse) - isolate the "readers"
    # array and count reader objects by counting their "type" key, which
    # every reader entry has exactly one of.
    local readers_block
    readers_block="$(echo "$body" | grep -o '"readers":\[[^]]*\]')"
    if [ -z "$readers_block" ]; then
        echo 0
        return
    fi
    echo "$readers_block" | grep -o '"type"' | wc -l | tr -d ' '
}

# RTSP session cleanup (Section 3): confirm MediaMTX has actually dropped
# the "main" publisher before a new ffmpeg is allowed to launch. Killing
# the old ffmpeg PID is not enough by itself - a lingering publisher/
# session in MediaMTX can race a brand-new publish attempt and produce
# overlapping-publisher failures. Best-effort: proceeds after timeout
# regardless, since the caller has already done a hard process-level kill.
wait_publisher_removed() {
    [ "$HAVE_CURL" -eq 1 ] || return 0
    local waited=0
    while [ "$waited" -lt "$PUBLISHER_REMOVAL_TIMEOUT" ]; do
        local body
        body="$(curl -fsS "$MEDIAMTX_API/v3/paths/get/main" 2>/dev/null)" || return 0
        if [ "$HAVE_JQ" -eq 1 ]; then
            [ "$(echo "$body" | jq -r '.source // "null"' 2>/dev/null)" = "null" ] && return 0
        else
            echo "$body" | grep -q '"source":null' && return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    return 0
}

# Structured event logger. A single format makes field debugging out of
# raw container logs (grep/jq-able) practical instead of hunting through
# free-text lines that each say something slightly different.
# Usage: log_event REASON key1=val1 key2=val2 ...
log_event() {
    local reason="$1"; shift
    echo "[entrypoint] [$(date '+%Y-%m-%d %H:%M:%S')] event=$reason $*"
}

# Real frame verification: publisher-ready + advancing byte counters still
# don't prove a *decodable* frame reaches a consumer (corrupt stream,
# wrong codec params, etc. can all pass those checks). This is the final,
# authoritative check - it's what a real downstream reader (pipeline
# worker, frontend player) actually needs to succeed. Uses OpenCV (already
# a dependency of pipeline_worker.py) via a short-lived subprocess so a
# hung VideoCapture can't wedge the watchdog itself.
verify_stream_frames() {
    FRAME_VERIFY_CONSECUTIVE="$FRAME_VERIFY_CONSECUTIVE" \
    FRAME_VERIFY_STABLE_S="$FRAME_VERIFY_STABLE_S" \
    timeout "$FRAME_VERIFY_TIMEOUT" python3 - <<'PYEOF' 2>/dev/null
import cv2, os, sys, time
need = int(os.environ.get("FRAME_VERIFY_CONSECUTIVE", "3"))
stable_s = float(os.environ.get("FRAME_VERIFY_STABLE_S", "2"))
cap = cv2.VideoCapture("rtsp://localhost:8554/main", cv2.CAP_FFMPEG)
ok = False
deadline = time.time() + 5
consecutive = 0
streak_start = None
try:
    while time.time() < deadline:
        ret, frame = cap.read()
        if ret and frame is not None and frame.size > 0:
            consecutive += 1
            streak_start = streak_start or time.time()
            if consecutive >= need and (time.time() - streak_start) >= stable_s:
                ok = True
                break
        else:
            consecutive = 0
            streak_start = None
        time.sleep(0.2)
finally:
    cap.release()
sys.exit(0 if ok else 1)
PYEOF
}

# PIDs of every background service this script owns, so shutdown can
# reap them all instead of leaving orphans/zombies behind.
MEDIAMTX_PID=""
FFMPEG_WATCHDOG_PID=""
FOREGROUND_PID=""

# Tracks the last-logged subscriber presence ("" | "none" | "active") so
# NO_ACTIVE_SUBSCRIBERS/OUTPUT_IDLE_NO_VIEWERS are only emitted on a real
# transition, not every polling cycle.
LAST_SUBSCRIBER_STATE=""

# ------------------------------------------------------------------
# Duplicate-instance guard: if the container was restarted without a
# clean shutdown (e.g. `docker kill`), a previous MediaMTX/ffmpeg may
# still be alive on a shared PID namespace. Clear them before starting
# new ones so we never end up with duplicate relays/servers.
# ------------------------------------------------------------------
pkill -f "/opt/mediamtx/mediamtx" 2>/dev/null || true
pkill -f "$RELAY_TARGET" 2>/dev/null || true
sleep 1

# ------------------------------------------------------------------
# Cleanup / signal handling.
#
# We deliberately do NOT `exec "$@"` at the end of this script. exec
# would replace this shell's process image, and every background job
# started below (MediaMTX, the ffmpeg watchdog loop, its ffmpeg child)
# would keep running as orphans with nothing left to forward SIGTERM
# to them on `docker stop`. Instead we run the foreground command as a
# tracked job and `wait` on it, so this trap can catch the signal and
# cleanly tear down every child before the container exits.
# ------------------------------------------------------------------
cleanup() {
    echo "[entrypoint] Caught shutdown signal - stopping child processes..."
    # Stop the stream-mgr watchdog daemon first so it doesn't try to
    # "helpfully" restart anything we're about to kill.
    if command -v stream-mgr >/dev/null 2>&1; then
        stream-mgr watchdog --stop >/dev/null 2>&1 || true
    fi
    [ -n "$FOREGROUND_PID" ] && kill -TERM "$FOREGROUND_PID" 2>/dev/null || true
    [ -n "$FFMPEG_WATCHDOG_PID" ] && kill -TERM "$FFMPEG_WATCHDOG_PID" 2>/dev/null || true
    pkill -TERM -f "$RELAY_TARGET" 2>/dev/null || true
    [ -n "$MEDIAMTX_PID" ] && kill -TERM "$MEDIAMTX_PID" 2>/dev/null || true
    # Give everything a moment to exit gracefully, then reap.
    wait "$FOREGROUND_PID" 2>/dev/null || true
    wait "$FFMPEG_WATCHDOG_PID" 2>/dev/null || true
    wait "$MEDIAMTX_PID" 2>/dev/null || true
    echo "[entrypoint] Shutdown complete."
    exit 0
}
trap cleanup SIGTERM SIGINT

echo "[entrypoint] Starting MediaMTX..."
/opt/mediamtx/mediamtx /opt/mediamtx/mediamtx.yml &
MEDIAMTX_PID=$!

if ! kill -0 "$MEDIAMTX_PID" 2>/dev/null; then
    echo "[entrypoint] ERROR: MediaMTX failed to start."
    exit 1
fi

echo "[entrypoint] Waiting for MediaMTX API to become ready..."
if ! wait_for_mediamtx_api; then
    log_event "MEDIAMTX_UNAVAILABLE" "phase=startup" "timeout_s=$MEDIAMTX_READY_TIMEOUT"
    echo "[entrypoint] ERROR: MediaMTX API did not respond within ${MEDIAMTX_READY_TIMEOUT}s."
    exit 1
fi
echo "[entrypoint] MediaMTX API ready."

echo "[entrypoint] Starting RTSP relay (with watchdog)..."

# Chains every health signal we have into one recovery gate: a restart is
# only "complete" once a real, decodable frame is confirmed - matching the
# requirement that publisher-ready/bytes-moving alone are not sufficient
# proof the relay actually works end to end.
verify_recovery() {
    local pid="$1" recovery_start waited=0
    recovery_start=$(date +%s)
    log_event "RECOVERY_STARTED" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT"

    while [ "$waited" -lt "$PATH_READY_TIMEOUT" ]; do
        path_is_published && break
        kill -0 "$pid" 2>/dev/null || return 1
        sleep "$PATH_CHECK_INTERVAL"; waited=$((waited + PATH_CHECK_INTERVAL))
    done
    if ! path_is_published; then
        log_event "NO_PUBLISHER" "phase=recovery_verify" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT"
        log_event "RECOVERY_FAILED" "reason=NO_PUBLISHER" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT" \
            "recovery_duration_s=$(( $(date +%s) - recovery_start ))"
        return 1
    fi
    log_event "PUBLISHER_CREATED" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT"

    local r1 s1 r2 s2 subs
    r1="$(path_bytes_received)"; s1="$(path_bytes_sent)"
    sleep "$PATH_CHECK_INTERVAL"
    r2="$(path_bytes_received)"; s2="$(path_bytes_sent)"
    subs="$(path_subscriber_count)"
    if [ -n "$r1" ] && [ "$r1" = "$r2" ]; then
        log_event "INPUT_STREAM_STALLED" "phase=recovery_verify" \
            "bytesReceived_prev=$r1" "bytesReceived_cur=$r2" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT"
        log_event "BYTES_STALLED" "leg=input" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT"
        log_event "RECOVERY_FAILED" "reason=INPUT_STREAM_STALLED" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT" \
            "recovery_duration_s=$(( $(date +%s) - recovery_start ))"
        return 1
    fi
    # bytesSent only means something once someone is actually reading the
    # stream (see path_subscriber_count() docstring). With zero readers,
    # a flat bytesSent is expected idle behaviour, not a failure - only
    # gate recovery on it when subscribers are actually present.
    if [ "${subs:-0}" -gt 0 ] && [ -n "$s1" ] && [ "$s1" = "$s2" ]; then
        log_event "OUTPUT_STREAM_STALLED" "phase=recovery_verify" \
            "bytesSent_prev=$s1" "bytesSent_cur=$s2" "subscriber_count=$subs" \
            "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT"
        log_event "BYTES_STALLED" "leg=output" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT"
        log_event "RECOVERY_FAILED" "reason=OUTPUT_STREAM_STALLED" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT" \
            "recovery_duration_s=$(( $(date +%s) - recovery_start ))"
        return 1
    fi
    log_event "PUBLISHER_READY" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT" \
        "bytesReceived=$r2" "bytesSent=$s2" "subscriber_count=${subs:-0}"

    if ! verify_stream_frames; then
        log_event "NO_FRAME_DECODE" "phase=recovery_verify" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT"
        log_event "FRAME_DECODE_FAILED" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT"
        log_event "RECOVERY_FAILED" "reason=NO_FRAME_DECODE" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT" \
            "recovery_duration_s=$(( $(date +%s) - recovery_start ))"
        return 1
    fi
    log_event "STREAM_VERIFIED" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT"

    if [ "${subs:-0}" -gt 0 ]; then
        log_event "RECOVERY_VERIFIED" "reason=PUBLISHER_HEALTHY_ACTIVE_VIEWERS" \
            "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT" "subscriber_count=$subs"
    else
        log_event "RECOVERY_VERIFIED" "reason=PUBLISHER_HEALTHY_NO_VIEWERS" \
            "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT"
    fi

    log_event "RECOVERY_COMPLETE" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT" \
        "recovery_duration_s=$(( $(date +%s) - recovery_start ))" \
        "bytesReceived=$r2" "bytesSent=$s2"
    log_event "RECOVERY_COMPLETED" "ffmpeg_pid=$pid" "restart_count=$RESTART_COUNT" \
        "recovery_duration_s=$(( $(date +%s) - recovery_start ))" \
        "bytesReceived=$r2" "bytesSent=$s2"
    return 0
}

# ------------------------------------------------------------------
# Watchdog function: runs ffmpeg in the background and restarts it
# whenever it exits OR whenever it's alive but not actually publishing
# the "main" path (verified against the live MediaMTX API). This never
# returns, so it must be launched in the background.
# ------------------------------------------------------------------
run_ffmpeg_watchdog() {
    # Disable 'set -e' locally: ffmpeg exiting non-zero must NOT kill this
    # loop or the script - that's the whole point of the watchdog.
    set +e
    RESTART_COUNT=-1
    LAST_CAMERA_STATE=""   # "", "up", "down" - tracks CAMERA_CONNECTED/CAMERA_LOST transitions
    while true; do
        RESTART_COUNT=$((RESTART_COUNT + 1))

        # RTSP session cleanup (Section 3): before launching a new ffmpeg,
        # confirm MediaMTX has actually dropped any previous "main"
        # publisher/session, so a new publish attempt never races a
        # not-yet-cleared old one (never allow overlapping publishers).
        wait_publisher_removed

        local spawn_start_ts
        spawn_start_ts=$(date +%s)
        ffmpeg -y \
            -rtsp_transport tcp \
            -fflags nobuffer \
            -flags low_delay \
            -analyzeduration 0 \
            -probesize 32 \
            -rtsp_flags prefer_tcp \
            -max_delay 500000 \
            -i "$CAMERA_SOURCE" \
            -c:v libx264 \
            -preset ultrafast \
            -tune zerolatency \
            -pix_fmt yuv420p \
            -f rtsp "$RELAY_TARGET" &
        local ffmpeg_pid=$!

        # Give ffmpeg a beat to fail fast (bad camera creds, unreachable
        # source, etc.) before we invest in the full recovery-verification
        # chain below - an immediate exit here is a camera-side problem,
        # not a relay/MediaMTX one, and deserves its own reason in logs.
        sleep 1
        if ! kill -0 "$ffmpeg_pid" 2>/dev/null; then
            log_event "CAMERA_UNAVAILABLE" "camera_source=$CAMERA_SOURCE" \
                "restart_count=$RESTART_COUNT"
            log_event "FFMPEG_EXITED" "ffmpeg_pid=$ffmpeg_pid" "restart_count=$RESTART_COUNT" \
                "reason=immediate_exit"
            if [ "$LAST_CAMERA_STATE" != "down" ]; then
                log_event "CAMERA_LOST" "camera_source=$CAMERA_SOURCE"
                LAST_CAMERA_STATE="down"
            fi
        else
            log_event "FFMPEG_STARTED" "ffmpeg_pid=$ffmpeg_pid" "restart_count=$RESTART_COUNT"
            if [ "$LAST_CAMERA_STATE" != "up" ]; then
                log_event "CAMERA_CONNECTED" "camera_source=$CAMERA_SOURCE"
                LAST_CAMERA_STATE="up"
            fi
            # Recovery is not "done" just because ffmpeg is running. Chain:
            # publisher ready -> bytesReceived advancing -> bytesSent
            # advancing -> a real decodable frame. Each step rules out one
            # more way this can silently be broken; only NO_FRAME_DECODE
            # actually proves a downstream consumer would succeed.
            verify_recovery "$ffmpeg_pid"
        fi

        # Poll the MediaMTX API while ffmpeg runs. A running ffmpeg process
        # is not proof of a working relay (bad camera, auth failure, stalled
        # source, etc. can all leave ffmpeg alive but never publishing) -
        # validate the "main" path actually shows up, and keep validating it
        # stays up for as long as ffmpeg runs.
        local unpublished_for=0
        local stalled_for=0
        local last_bytes_recv=""
        local last_bytes_sent=""
        local stall_start_ts=""
        while kill -0 "$ffmpeg_pid" 2>/dev/null; do
            if path_is_published; then
                unpublished_for=0

                # Publisher is "ready" per MediaMTX, but is it actually
                # moving bytes on the input leg? bytesReceived alone only
                # proves ffmpeg->MediaMTX; that's the one leg that must
                # always be advancing regardless of viewers.
                #
                # bytesSent is different: MediaMTX only sends bytes to
                # readers that exist. With zero subscribers, bytesSent
                # sitting flat at 0 is the CORRECT, expected behaviour -
                # not a stall - so it is only checked when subscribers are
                # actually attached (path_subscriber_count() > 0).
                local cur_recv cur_sent cur_subs reason=""
                cur_recv="$(path_bytes_received)"
                cur_sent="$(path_bytes_sent)"
                cur_subs="$(path_subscriber_count)"

                # Log subscriber presence transitions only (not every
                # cycle) so logs stay readable under long idle periods.
                if [ "${cur_subs:-0}" -eq 0 ]; then
                    if [ "$LAST_SUBSCRIBER_STATE" != "none" ]; then
                        log_event "NO_ACTIVE_SUBSCRIBERS" "ffmpeg_pid=$ffmpeg_pid" "restart_count=$RESTART_COUNT"
                        log_event "OUTPUT_IDLE_NO_VIEWERS" "ffmpeg_pid=$ffmpeg_pid" \
                            "bytesReceived=${cur_recv:-?}" "restart_count=$RESTART_COUNT"
                        LAST_SUBSCRIBER_STATE="none"
                    fi
                elif [ "$LAST_SUBSCRIBER_STATE" != "active" ]; then
                    LAST_SUBSCRIBER_STATE="active"
                fi

                if [ -n "$cur_recv" ] && [ -n "$last_bytes_recv" ] && [ "$cur_recv" = "$last_bytes_recv" ]; then
                    reason="INPUT_STREAM_STALLED"
                elif [ "${cur_subs:-0}" -gt 0 ] && [ -n "$cur_sent" ] && [ -n "$last_bytes_sent" ] && [ "$cur_sent" = "$last_bytes_sent" ]; then
                    reason="OUTPUT_STREAM_STALLED"
                fi

                if [ -n "$reason" ]; then
                    [ -z "$stall_start_ts" ] && stall_start_ts=$(date +%s)
                    stalled_for=$((stalled_for + PATH_CHECK_INTERVAL))
                    if [ "$stalled_for" -ge "$PATH_READY_TIMEOUT" ]; then
                        log_event "$reason" \
                            "bytesReceived_prev=${last_bytes_recv:-?}" "bytesReceived_cur=${cur_recv:-?}" \
                            "bytesSent_prev=${last_bytes_sent:-?}" "bytesSent_cur=${cur_sent:-?}" \
                            "subscriber_count=${cur_subs:-0}" \
                            "publisher_ready=true" "ffmpeg_pid=$ffmpeg_pid" \
                            "restart_count=$RESTART_COUNT" "stall_duration_s=$stalled_for"
                        kill -TERM "$ffmpeg_pid" 2>/dev/null
                        break
                    fi
                else
                    stalled_for=0
                    stall_start_ts=""
                fi
                last_bytes_recv="$cur_recv"
                last_bytes_sent="$cur_sent"
            else
                unpublished_for=$((unpublished_for + PATH_CHECK_INTERVAL))
                stalled_for=0
                stall_start_ts=""
                last_bytes_recv=""
                last_bytes_sent=""
                if [ "$unpublished_for" -ge "$PATH_READY_TIMEOUT" ]; then
                    log_event "NO_PUBLISHER" \
                        "publisher_ready=false" "ffmpeg_pid=$ffmpeg_pid" \
                        "restart_count=$RESTART_COUNT" "stall_duration_s=$unpublished_for"
                    kill -TERM "$ffmpeg_pid" 2>/dev/null
                    break
                fi
            fi
            sleep "$PATH_CHECK_INTERVAL"
        done

        wait "$ffmpeg_pid" 2>/dev/null
        RC=$?

        # If we get here, ffmpeg exited (crash, camera drop, killed above for
        # failing to publish, etc.). Never let this loop exit - that's the
        # whole point of the watchdog - just log why and try again after a
        # short, non-busy backoff.
        echo "[entrypoint] [$(date '+%Y-%m-%d %H:%M:%S')] ffmpeg relay exited (rc=$RC) - restarting in ${RELAY_RESTART_DELAY}s..."
        log_event "FFMPEG_EXITED" "ffmpeg_pid=$ffmpeg_pid" "restart_count=$RESTART_COUNT" \
            "exit_code=$RC"
        sleep "$RELAY_RESTART_DELAY"
    done
}
# NOTE: -stimeout was removed from the rtsp demuxer in recent FFmpeg
# builds (superseded by -rw_timeout, already set above); keeping both
# risks "Unrecognized option 'stimeout'" hard-failing every restart on
# newer FFmpeg, so it has been dropped.

# Launch watchdog in background; script continues regardless of ffmpeg state.
run_ffmpeg_watchdog &
FFMPEG_WATCHDOG_PID=$!
sleep 2

if ! kill -0 "$FFMPEG_WATCHDOG_PID" 2>/dev/null; then
    echo "[entrypoint] WARN: ffmpeg watchdog failed to start - camera may be offline."
fi

# ------------------------------------------------------------------
# Auto-start the stream-mgr process/pipeline watchdog daemon.
# The operator must NEVER have to run `stream-mgr watchdog` by hand -
# this is the single integration point that makes the whole subsystem
# autonomous (FFmpeg/MediaMTX/pipeline-worker health, restart backoff).
# ------------------------------------------------------------------
if command -v stream-mgr >/dev/null 2>&1; then
    echo "[entrypoint] Starting stream-mgr watchdog daemon..."
    stream-mgr watchdog --daemon \
        --frame-timeout "$WATCHDOG_FRAME_TIMEOUT" \
        --interval "$WATCHDOG_INTERVAL" \
        || echo "[entrypoint] WARN: stream-mgr watchdog daemon failed to start."
else
    echo "[entrypoint] WARN: stream-mgr not on PATH - pipeline auto-recovery disabled."
fi

echo "[entrypoint] RTSP relay : rtsp://localhost:8554/main"
echo "[entrypoint] UDP in     : udp://0.0.0.0:9000"
echo "[entrypoint] API        : http://0.0.0.0:9997"
echo ""

if [ "$#" -gt 0 ]; then
    "$@" &
    FOREGROUND_PID=$!

    wait "$FOREGROUND_PID"
    cleanup
else
    echo "[entrypoint] No foreground command supplied. Supervising services..."

    while true; do
        if ! kill -0 "$MEDIAMTX_PID" 2>/dev/null; then
            echo "[entrypoint] MediaMTX exited unexpectedly."
            break
        fi

        if ! kill -0 "$FFMPEG_WATCHDOG_PID" 2>/dev/null; then
            echo "[entrypoint] FFmpeg watchdog exited unexpectedly."
            break
        fi

        sleep 2
    done

    cleanup
fi
