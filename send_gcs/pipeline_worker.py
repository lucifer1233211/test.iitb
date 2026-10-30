#!/usr/bin/env python3
"""
pipeline_worker.py — Plugin-based per-stream detection worker.

Loads a model plugin from /app/plugins/<plugin_name>.py,
opens the stream with OpenCV, and runs infer(frame) on each frame.

Spawned by stream_mgr.py — not intended to be called directly.
"""

import argparse
import importlib.util
import json
import os
import signal
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import cv2

PLUGINS_DIR = Path("/app/plugins")
sys.path.insert(0, "/app")

from model_base import ModelConfig


# --- Args ---------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--name",       required=True,  help="stream/model label for logs")
    p.add_argument("--source",     required=True,  help="Input stream URL")
    p.add_argument("--plugin",     required=True,  help="Plugin name (no .py) or full path")
    p.add_argument("--model-path", dest="model_path", default="",
                   help="Path to weights file passed to plugin.load()")
    p.add_argument("--conf",       type=float, default=0.45)
    p.add_argument("--classes",    default="",
                   help="Comma-separated class IDs e.g. 0,2,7 (empty = all)")
    p.add_argument("--half",       action="store_true")
    p.add_argument("--device",     default="cuda", choices=["cuda", "cpu"])
    p.add_argument("--plugin-args", dest="plugin_args", default="{}",
                   help='JSON string of extra args passed to ModelConfig.extra')
    p.add_argument("--warmup",     action="store_true",
                   help="Run a dummy inference before starting the stream loop")
    return p.parse_args()


# --- Plugin loader -------------------------------------------------------------

def load_plugin(plugin: str):
    """
    Load a Model class from:
      - /app/plugins/<plugin>.py   (if plugin has no path separators)
      - an absolute or relative path (if plugin ends in .py or contains /)
    """
    plugin_path = Path(plugin)
    if not plugin_path.suffix:
        plugin_path = PLUGINS_DIR / f"{plugin}.py"

    if not plugin_path.exists():
        raise FileNotFoundError(
            f"Plugin not found: {plugin_path}\n"
            f"Available plugins: {[p.stem for p in PLUGINS_DIR.glob('*.py')]}"
        )

    spec   = importlib.util.spec_from_file_location("plugin_module", plugin_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "Model"):
        raise AttributeError(
            f"{plugin_path} must define a class called 'Model' "
            "that inherits from BaseModel."
        )
    return module.Model


# --- Stream manager notification -------------------------------------------

def notify_stream_manager(name, event, **fields):
    """
    Notify the parent stream manager of a recovery-related event.
    stream_mgr.py spawns this worker as a subprocess, so the simplest,
    dependency-free channel is a structured line on stdout that the
    manager can grep/parse. Swap this out for an IPC/socket call if needed.
    """
    payload = {"stream": name, "event": event, "ts": time.time(), **fields}
    print(f"[STREAM_MGR_EVENT] {json.dumps(payload)}", flush=True)


def notify_backend(event, **fields):
    """
    Reusable mission-backend notifier. The backend URL is never hardcoded —
    it is read from the MISSION_BACKEND_URL environment variable each call,
    so deployments (and tests) can configure/disable it freely. A missing
    URL or a network failure is logged and swallowed; the worker's own
    recovery loop must never be blocked or crashed by a notification.
    """
    url = os.environ.get("MISSION_BACKEND_URL", "").strip()
    if not url:
        return
    payload = {"event": event, "ts": time.time(), **fields}
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"[STREAM_MGR_EVENT] backend notify failed: {exc}", flush=True)


# --- Stream loop --------------------------------------------------------------

def run(args):
    name = args.name
    log  = lambda msg: print(f"[{name}] {msg}", flush=True)
    worker_start_ts = time.time()
    pid = os.getpid()

    log(f"Worker starting")
    log(f"Source : {args.source}")
    log(f"Plugin : {args.plugin}")
    log(f"Weights: {args.model_path or '(none)'}")

    # -- 1. Load plugin --------------------------------------------------------
    log("Loading plugin…")
    ModelClass = load_plugin(args.plugin)

    extra = {}
    try:
        extra = json.loads(args.plugin_args)
    except json.JSONDecodeError:
        log(f"Warning: could not parse --plugin-args as JSON, ignoring.")

    config = ModelConfig(
        model_path = args.model_path,
        conf       = args.conf,
        classes    = [int(c) for c in args.classes.split(",") if c.strip()],
        half       = args.half,
        device     = args.device,
        extra      = extra,
    )

    model = ModelClass()
    model.load(config)
    log("Plugin loaded.")

    # -- 2. Optional warmup ----------------------------------------------------
    if args.warmup:
        log("Warming up…")
        try:
            model.warmup()
            log("Warmup done.")
        except Exception as e:
            log(f"Warmup failed (non-fatal): {e}")

    # -- 3. Graceful shutdown --------------------------------------------------
    shutdown = [False]

    def _sig(sig, _frame):
        log(f"Received signal {sig}, shutting down…")
        shutdown[0] = True

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT,  _sig)

    # -- 4. Open stream --------------------------------------------------------
    def open_cap(url):
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def flush_and_release(cap_obj):
        """
        Best-effort decoder flush before release. OpenCV's VideoCapture has
        no explicit "flush" API, so we drain a couple of already-buffered
        frames (non-blocking-ish grab calls) before releasing — this avoids
        the FFmpeg backend holding a half-decoded frame/packet in its
        internal buffer across the reconnect, which has been observed to
        cause the first frame(s) after reconnect to be corrupt/stale.
        """
        if cap_obj is None:
            return
        try:
            for _ in range(2):
                cap_obj.grab()
        except Exception:
            pass  # decoder may already be in a broken state — fine, we're releasing it anyway
        finally:
            cap_obj.release()

    def interruptible_sleep(seconds: float):
        """time.sleep() that still notices shutdown[0] promptly, so SIGTERM
        during a (possibly long, backed-off) reconnect wait is honored
        within ~0.2s instead of blocking for the full delay."""
        end = time.time() + seconds
        while not shutdown[0] and time.time() < end:
            time.sleep(min(0.2, max(0.0, end - time.time())))

    # -- Recovery-specific logging, separate from inference logs --
    def rlog(msg):
        print(f"[{name}][recovery] {msg}", flush=True)

    log("Opening stream…")
    consecutive_errors      = 0
    FAIL_THRESHOLD          = 10       # failures before a decoder reset/reconnect
    BASE_RECONNECT_DELAY    = 1.0      # seconds; doubles on each consecutive failure
    MAX_RECONNECT_DELAY     = 30.0     # cap so we never wait "forever" between tries
    HEARTBEAT_INTERVAL      = 5.0      # seconds; liveness signal independent of frame rate
    reconnect_delay         = BASE_RECONNECT_DELAY
    reconnect_count         = 0
    decoder_reset_count     = 0
    packet_failure_count    = 0        # every failed cap.read(), not just threshold crossings
    frame_count             = 0        # total frames successfully read
    last_good_frame_ts      = time.time()
    failed_reconnect_streak = 0
    NOTIFY_AFTER_FAILED_RECONNECTS = 3  # escalate to stream manager

    # Boxed (mutable single-element list) so the heartbeat() closure below
    # can update them without needing `nonlocal` for every field.
    last_heartbeat_ts_box    = [0.0]
    last_heartbeat_frames_box = [0]

    def heartbeat():
        now = time.time()
        if now - last_heartbeat_ts_box[0] >= HEARTBEAT_INTERVAL:
            elapsed = now - last_heartbeat_ts_box[0] if last_heartbeat_ts_box[0] else HEARTBEAT_INTERVAL
            frames_since = frame_count - last_heartbeat_frames_box[0]
            fps = frames_since / elapsed if elapsed > 0 else 0.0
            uptime_s = now - worker_start_ts
            last_heartbeat_ts_box[0] = now
            last_heartbeat_frames_box[0] = frame_count
            rlog(
                f"heartbeat alive=1 pid={pid} fps={fps:.2f} frame_count={frame_count} "
                f"reconnect_count={reconnect_count} "
                f"decoder_reset_count={decoder_reset_count} "
                f"packet_failure_count={packet_failure_count} "
                f"seconds_since_good_frame={now - last_good_frame_ts:.1f} "
                f"uptime_s={uptime_s:.1f}"
            )
            notify_stream_manager(
                name, "heartbeat",
                pid=pid,
                fps=round(fps, 2),
                frame_count=frame_count,
                reconnect_count=reconnect_count,
                decoder_reset_count=decoder_reset_count,
                packet_failure_count=packet_failure_count,
                seconds_since_good_frame=round(now - last_good_frame_ts, 1),
                last_good_frame_ts=last_good_frame_ts,
                uptime_s=round(uptime_s, 1),
            )

    # Open the stream with the same retry/backoff policy used for later
    # reconnects — a temporary camera/network hiccup at startup must NOT
    # crash the worker (previously this called sys.exit(1) immediately).
    cap = None
    open_attempt = 0
    while not shutdown[0] and (cap is None or not cap.isOpened()):
        open_attempt += 1
        cap = open_cap(args.source)
        if cap.isOpened():
            break
        rlog(f"Initial open attempt #{open_attempt} failed; "
             f"retrying in {reconnect_delay:.1f}s…")
        flush_and_release(cap)
        cap = None
        interruptible_sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY)

    if shutdown[0]:
        log("Shutdown requested during initial connect; exiting cleanly.")
        return

    reconnect_delay = BASE_RECONNECT_DELAY  # reset backoff after a successful open
    log("Stream opened.")

    # -- 5. Inference loop -----------------------------------------------------
    log("Inference loop started.")

    try:
        while not shutdown[0]:
            heartbeat()
            ret, frame = cap.read()

            # Handle dropped frames / disconnected stream
            if not ret or frame is None:
                consecutive_errors += 1
                packet_failure_count += 1
                log(f"Failed to read frame (#{consecutive_errors}).")

                if consecutive_errors >= FAIL_THRESHOLD:
                    # -- Full recovery cycle: release, flush, destroy decoder, wait, recreate --
                    reconnect_count += 1
                    decoder_reset_count += 1
                    rlog(f"Threshold reached ({consecutive_errors} failures). "
                         f"Resetting decoder (reset #{decoder_reset_count}), "
                         f"reconnect attempt #{reconnect_count}, "
                         f"waiting {reconnect_delay:.1f}s…")

                    flush_and_release(cap)
                    cap = None  # ensure old decoder is dropped/garbage-collected

                    interruptible_sleep(reconnect_delay)
                    if shutdown[0]:
                        break

                    cap = open_cap(args.source)
                    if cap.isOpened():
                        rlog(f"Reconnect successful (attempt #{reconnect_count}).")
                        failed_reconnect_streak = 0
                        consecutive_errors = 0
                        reconnect_delay = BASE_RECONNECT_DELAY  # backoff resets on success
                        notify_backend(
                            "stream_recovered", stream=name,
                            reconnect_count=reconnect_count,
                            decoder_reset_count=decoder_reset_count,
                        )
                    else:
                        failed_reconnect_streak += 1
                        rlog(f"Reconnect attempt #{reconnect_count} failed "
                             f"(streak: {failed_reconnect_streak}).")
                        if failed_reconnect_streak >= NOTIFY_AFTER_FAILED_RECONNECTS:
                            notify_stream_manager(
                                name, "reconnect_failing",
                                failed_reconnect_streak=failed_reconnect_streak,
                                reconnect_count=reconnect_count,
                                decoder_reset_count=decoder_reset_count,
                                packet_failure_count=packet_failure_count,
                                last_good_frame_ts=last_good_frame_ts,
                            )
                        # Never exit on RTSP failure — back off (exponentially,
                        # capped) and keep trying.
                        consecutive_errors = 0
                        reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY)
                        interruptible_sleep(reconnect_delay)
                else:
                    interruptible_sleep(0.2)

                continue

            consecutive_errors = 0
            last_good_frame_ts = time.time()
            frame_count += 1

            try:
                detections = model.infer(frame)
                if detections:
                    for d in detections:
                        log(str(d))
                else:
                    log("no detections")

            except Exception as exc:
                log(f"Infer error: {exc}")
                traceback.print_exc()

    finally:
        flush_and_release(cap)
        log(f"Worker exited. reconnect_count={reconnect_count} "
            f"decoder_reset_count={decoder_reset_count} "
            f"packet_failure_count={packet_failure_count} "
            f"last_good_frame_ts={last_good_frame_ts}")


if __name__ == "__main__":
    args = parse_args()
    try:
        run(args)
    except Exception:
        traceback.print_exc()
        sys.exit(1)