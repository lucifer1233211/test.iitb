#!/usr/bin/env python3
"""
stream_mgr.py — RTSP/UDP Stream Management CLI
Jetson Orin Nano edition (MediaMTX + plugin-based inference)

Usage:
  # Streams
  stream-mgr streams add main --source rtsp://localhost:8554/stream2
  stream-mgr streams list
  stream-mgr streams remove main

  # Models (one plugin file = one model type)
  stream-mgr model add main detector --plugin onnx_detector \
      --model-path /app/models/model.onnx --conf 0.5
  stream-mgr model add main classifier --plugin hf_classifier \
      --model-path google/vit-base-patch16-224 \
      --plugin-args '{"top_k": 3}'
  stream-mgr model add main yolo --plugin ultralytics_yolo \
      --model-path yolov8n.pt --classes 0,2,7

  stream-mgr model list main          # what's attached
  stream-mgr model activate main detector
  stream-mgr model deactivate main detector
  stream-mgr model deactivate-all main
  stream-mgr model remove main detector

  # Plugins
  stream-mgr plugins list             # show all available plugin files

  # Status & logs
  stream-mgr status
  stream-mgr logs main detector --follow

  # UDP JSON listener
  stream-mgr udp start telemetry --port 9100 --pretty
  stream-mgr udp logs telemetry --follow
"""

import click
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

# --- Constants ----------------------------------------------------------------

STATE_FILE          = Path(os.environ.get("STREAM_STATE",   "/app/streams.json"))
LOG_DIR             = Path(os.environ.get("STREAM_LOG_DIR", "/app/logs"))
PLUGINS_DIR         = Path("/app/plugins")
WORKER_SCRIPT       = Path("/app/pipeline_worker.py")
UDP_LISTENER_SCRIPT = Path("/app/udp_listener.py")

# Persistent recovery history (production-hardening addendum, Section 2):
# a bounded, on-disk record of the last RECOVERY_HISTORY_MAX recovery
# events, independent of streams.json and of watchdog.log rotation, so
# operators can inspect recovery patterns across container restarts.
RECOVERY_HISTORY_FILE = Path(os.environ.get("RECOVERY_HISTORY_FILE", "/app/recovery_history.json"))
RECOVERY_HISTORY_MAX  = int(os.environ.get("RECOVERY_HISTORY_MAX", "500"))

console = Console()

# --- State helpers ------------------------------------------------------------

LOCK_FILE = STATE_FILE.with_suffix(STATE_FILE.suffix + ".lock")


@contextmanager
def _state_lock():
    """
    Advisory, cross-process exclusive lock guarding STATE_FILE.

    The CLI (streams add/remove, model activate/deactivate, …) and the
    background watchdog daemon both read-modify-write streams.json. Without
    locking, a watchdog restart cycle racing an operator command can clobber
    each other's writes (classic read-modify-write race / lost update).
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _load() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"streams": {}, "udp_listeners": {}}


def _save(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: write to a temp file then rename, so a crash mid-write
    # (or a concurrent reader) never observes a truncated/corrupt state file.
    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


@contextmanager
def locked_state():
    """Load state under the exclusive lock, yield it for mutation, save it,
    all while still holding the lock — the safe read-modify-write pattern."""
    with _state_lock():
        state = _load()
        yield state
        _save(state)


def _stream_or_die(state: dict, stream: str) -> dict:
    if stream not in state["streams"]:
        console.print(f"[bold red]?[/] Stream '[yellow]{stream}[/]' not found. "
                      "Run [cyan]stream-mgr streams list[/].")
        sys.exit(1)
    return state["streams"][stream]


def _model_or_die(state: dict, stream: str, key: str) -> dict:
    s = _stream_or_die(state, stream)
    if key not in s.get("models", {}):
        console.print(f"[bold red]?[/] Model '[yellow]{key}[/]' not attached to "
                      f"[cyan]{stream}[/]. Run [cyan]stream-mgr model add[/] first.")
        sys.exit(1)
    return s["models"][key]


def _is_running(pid) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _status_badge(pid) -> Text:
    if _is_running(pid):
        return Text("? RUNNING", style="bold green")
    elif pid is not None:
        return Text("? DEAD",    style="bold red")
    return Text("? STOPPED",     style="dim")


def _kill_pid(pid, timeout: int = 8):
    if not _is_running(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(timeout * 2):
            time.sleep(0.5)
            if not _is_running(pid):
                return
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _available_plugins() -> list[str]:
    if not PLUGINS_DIR.exists():
        return []
    return sorted(p.stem for p in PLUGINS_DIR.glob("*.py")
                  if not p.stem.startswith("_"))


# --- Rotating logs ----------------------------------------------------------

LOG_MAX_BYTES  = 10 * 1024 * 1024  # 10 MB
LOG_BACKUPS    = 5


def _rotate_if_needed(path: Path, max_bytes: int = LOG_MAX_BYTES,
                       backups: int = LOG_BACKUPS) -> None:
    """
    Size-based log rotation equivalent to logging.handlers.RotatingFileHandler,
    applied to plain subprocess-stdout log files (which aren't routed through
    Python's logging module, so RotatingFileHandler itself doesn't apply).
    Keeps the current log file's content intact — rotation only happens
    *before* opening for append, never truncating a file mid-write.
    """
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
        oldest = path.with_name(f"{path.name}.{backups}")
        if oldest.exists():
            oldest.unlink()
        for i in range(backups - 1, 0, -1):
            src = path.with_name(f"{path.name}.{i}")
            if src.exists():
                src.rename(path.with_name(f"{path.name}.{i + 1}"))
        path.rename(path.with_name(f"{path.name}.1"))
    except OSError as exc:
        # Never let log rotation itself take down a restart path.
        console.print(f"[dim]log rotation skipped for {path}: {exc}[/]")


def _open_rotating_log(path: Path):
    """Rotate (if oversized) then open a UTF-8 append-mode log file handle,
    suitable for passing as subprocess.Popen(stdout=..., stderr=...)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(path)
    return open(path, "a", encoding="utf-8")


# --- Mission backend notifications -----------------------------------------

def notify_backend(event: str, **fields) -> None:
    """
    Reusable notifier for the mission backend. The URL is never hardcoded —
    it's read from the MISSION_BACKEND_URL environment variable on every
    call, so it can be configured (or left unset to disable) per deployment.
    Failures are logged and swallowed; a notification must never abort a
    restart/recovery path.
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
        console.print(f"[dim]backend notify failed ({event}): {exc}[/]")


def _request_docker_restart(wd: dict, emit_fn, **fields) -> None:
    """
    FINAL recovery step (Level 5 addendum). Called only after every existing
    recovery mechanism (FFmpeg restart, MediaMTX restart, publisher/frame
    verification, escalation) has already failed. stream_mgr.py does not run
    `docker restart` itself and does not need the Docker socket mounted -- it
    POSTs a request to the host-side server.py, which executes the restart.

    Guarded by DOCKER_RESTART_COOLDOWN_S (stored in the watchdog state, so it
    survives across watchdog cycles) to prevent a restart storm if the
    camera keeps failing right after a container restart.
    """
    now = time.time()
    last = wd.get("last_docker_restart_request_ts")
    if last is not None and (now - last) < DOCKER_RESTART_COOLDOWN_S:
        remaining = round(DOCKER_RESTART_COOLDOWN_S - (now - last), 1)
        emit_fn("DOCKER_RESTART_SKIPPED_COOLDOWN", remaining_s=remaining, **fields)
        console.print(f"[dim]Docker restart skipped (cooldown, {remaining}s remaining)[/]")
        return

    url = STREAM_MGR_BACKEND_URL.rstrip("/") + "/api/restart-stream-manager"
    # Record the attempt timestamp before the request so a slow/hanging
    # backend can't itself cause a burst of duplicate requests.
    wd["last_docker_restart_request_ts"] = now
    try:
        req = urllib.request.Request(
            url, data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        emit_fn("DOCKER_RESTART_REQUESTED", url=url, **fields)
        console.print(f"[bold yellow]?[/] Requested container restart via {url}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        emit_fn("DOCKER_RESTART_REQUEST_FAILED", url=url, error=str(exc), **fields)
        console.print(f"[dim]Docker restart request failed: {exc}[/]")

# --- CLI Root -----------------------------------------------------------------

@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli():
    """
    \b
    +----------------------------------------+
    ¦  stream-mgr  ·  Jetson Stream Manager  ¦
    +----------------------------------------+
    Plugin-based inference on RTSP streams.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

# --- streams ------------------------------------------------------------------

@cli.group()
def streams():
    """Add, remove, and list configured input streams."""
    pass


@streams.command("add")
@click.argument("name")
@click.option("--source", "-s", required=True, help="Input stream URL.")
@click.option("--description", "-d", default="")
def streams_add(name, source, description):
    """Register a new stream source."""
    state = _load()
    if name in state["streams"]:
        console.print(f"[yellow]?[/]  Stream '[cyan]{name}[/]' already exists.")
        sys.exit(1)
    state["streams"][name] = {
        "name":        name,
        "source":      source,
        "description": description,
        "created_at":  datetime.now().isoformat(),
        "models":      {},
    }
    _save(state)
    console.print(f"[bold green]?[/] Added stream [cyan]{name}[/] ? [dim]{source}[/]")
    console.print(f"\n  Attach a model: [white]stream-mgr model add {name} <key> --plugin <plugin>[/]")


@streams.command("remove")
@click.argument("name")
@click.option("--force", is_flag=True, help="Stop all running models first.")
def streams_remove(name, force):
    """Remove a stream and all attached models."""
    state = _load()
    s = _stream_or_die(state, name)
    running = [k for k, v in s.get("models", {}).items() if _is_running(v.get("pid"))]
    if running and not force:
        console.print(f"[yellow]?[/]  Has running models: {running}. Use --force.")
        sys.exit(1)
    for k in running:
        _kill_pid(s["models"][k]["pid"])
    del state["streams"][name]
    _save(state)
    console.print(f"[bold green]?[/] Removed stream [cyan]{name}[/]")


@streams.command("list")
def streams_list():
    """List all configured streams."""
    state = _load()
    if not state["streams"]:
        console.print("[dim]No streams. Use [cyan]stream-mgr streams add[/].[/]")
        return
    t = Table(box=box.ROUNDED, header_style="bold magenta")
    t.add_column("Stream",  style="cyan",   no_wrap=True)
    t.add_column("Source",  style="dim")
    t.add_column("Models",  style="yellow")
    t.add_column("Running", style="green")
    for s in state["streams"].values():
        keys    = list(s.get("models", {}).keys())
        running = [k for k, v in s.get("models", {}).items() if _is_running(v.get("pid"))]
        t.add_row(
            s["name"], s["source"],
            ", ".join(keys)    if keys    else "—",
            ", ".join(running) if running else "—",
        )
    console.print(t)

# --- model --------------------------------------------------------------------

@cli.group()
def model():
    """Attach, configure, activate and deactivate model plugins on a stream."""
    pass


@model.command("add")
@click.argument("stream")
@click.argument("key")
@click.option("--plugin",      "-p", required=True,
              help="Plugin name in /app/plugins/ (without .py), e.g. onnx_detector")
@click.option("--model-path",  "-m", default="",
              help="Path to weights / model file. Passed to plugin.load().")
@click.option("--conf",        "-c", default=0.45, show_default=True)
@click.option("--classes",     "-C", default="",
              help="Comma-separated class IDs to detect (empty = all).")
@click.option("--half",        is_flag=True, default=True,
              help="FP16 inference (default on).")
@click.option("--device",      default="cuda",
              type=click.Choice(["cuda", "cpu"]), show_default=True)
@click.option("--plugin-args", "plugin_args", default="{}",
              help="JSON dict of extra args forwarded to ModelConfig.extra. "
                   "e.g. '{\"input_size\": 640, \"top_k\": 3}'")
@click.option("--warmup",      is_flag=True,
              help="Run a dummy inference after loading to warm up the model.")
def model_add(stream, key, plugin, model_path, conf, classes, half,
              device, plugin_args, warmup):
    """
    Attach a model plugin to a stream.

    \b
    KEY is the name you use to refer to this model on the stream.
    Use a different KEY to attach the same plugin twice with different configs.

    \b
    Examples:
      stream-mgr model add main detector --plugin onnx_detector \\
          --model-path /app/models/det.onnx

      stream-mgr model add main big-yolo --plugin ultralytics_yolo \\
          --model-path yolov8m.pt --conf 0.6 --classes 0,2,7

      stream-mgr model add main scene --plugin hf_classifier \\
          --model-path /app/models/scene-clf \\
          --plugin-args '{"top_k": 3}'
    """
    available = _available_plugins()
    if plugin not in available:
        console.print(f"[bold red]?[/] Plugin '[yellow]{plugin}[/]' not found in "
                      f"[dim]{PLUGINS_DIR}[/]")
        console.print(f"  Available: {available or '(none)'}")
        sys.exit(1)

    try:
        extra = json.loads(plugin_args)
    except json.JSONDecodeError as e:
        console.print(f"[bold red]?[/] Invalid --plugin-args JSON: {e}")
        sys.exit(1)

    state = _load()
    s = _stream_or_die(state, stream)
    if key in s["models"]:
        console.print(f"[yellow]?[/]  '[yellow]{key}[/]' already attached to "
                      f"[cyan]{stream}[/]. Remove it first.")
        sys.exit(1)

    s["models"][key] = {
        "plugin":      plugin,
        "model_path":  model_path,
        "conf":        conf,
        "classes":     classes,
        "half":        half,
        "device":      device,
        "plugin_args": extra,
        "warmup":      warmup,
        "pid":         None,
        "added_at":    datetime.now().isoformat(),
        "started_at":  None,
    }
    _save(state)
    console.print(f"[bold green]?[/] Attached [yellow]{key}[/] "
                  f"(plugin: [dim]{plugin}[/]) ? [cyan]{stream}[/]")
    console.print(f"  model-path : {model_path or '(none)'}")
    console.print(f"  conf={conf}  classes={classes or 'all'}  "
                  f"half={half}  device={device}")
    if extra:
        console.print(f"  plugin-args: {extra}")
    console.print(f"\n  Activate: [white]stream-mgr model activate {stream} {key}[/]")


@model.command("remove")
@click.argument("stream")
@click.argument("key")
@click.option("--force", is_flag=True)
def model_remove(stream, key, force):
    """Detach a model from a stream."""
    state = _load()
    m = _model_or_die(state, stream, key)
    if _is_running(m.get("pid")):
        if not force:
            console.print("[yellow]?[/]  Model is running. Use --force to stop and remove.")
            sys.exit(1)
        _kill_pid(m["pid"])
    del state["streams"][stream]["models"][key]
    _save(state)
    console.print(f"[bold green]?[/] Removed [yellow]{key}[/] from [cyan]{stream}[/]")


@model.command("activate")
@click.argument("stream")
@click.argument("key")
def model_activate(stream, key):
    """Start a model worker on a stream."""
    state = _load()
    s = _stream_or_die(state, stream)
    m = _model_or_die(state, stream, key)

    if _is_running(m.get("pid")):
        console.print(f"[yellow]?[/]  [yellow]{key}[/] already running "
                      f"on [cyan]{stream}[/] (PID {m['pid']}).")
        sys.exit(1)

    log_path = LOG_DIR / f"{stream}-{key}.log"
    log_file = _open_rotating_log(log_path)
    log_file.write(
        f"\n{'-'*60}\n[{datetime.now().isoformat()}] Activating\n{'-'*60}\n"
    )
    log_file.flush()

    cmd = [
        sys.executable, str(WORKER_SCRIPT),
        "--name",        f"{stream}/{key}",
        "--source",      s["source"],
        "--plugin",      m["plugin"],
        "--model-path",  m.get("model_path", ""),
        "--conf",        str(m["conf"]),
        "--classes",     m.get("classes", ""),
        "--device",      m.get("device", "cuda"),
        "--plugin-args", json.dumps(m.get("plugin_args", {})),
    ]
    if m.get("half"):
        cmd.append("--half")
    if m.get("warmup"):
        cmd.append("--warmup")

    proc = subprocess.Popen(cmd, stdout=log_file, stderr=log_file,
                            start_new_session=True)
    time.sleep(1.5)
    if proc.poll() is not None:
        console.print(f"[bold red]?[/] Worker exited immediately. "
                      f"Check: [cyan]stream-mgr logs {stream} {key}[/]")
        sys.exit(1)

    state["streams"][stream]["models"][key]["pid"]        = proc.pid
    state["streams"][stream]["models"][key]["started_at"] = datetime.now().isoformat()
    _save(state)

    console.print(f"[bold green]?[/] Activated [yellow]{key}[/] on [cyan]{stream}[/] "
                  f"(PID [dim]{proc.pid}[/])")
    console.print(f"  Plugin : [dim]{m['plugin']}[/]")
    console.print(f"  Follow : [white]stream-mgr logs {stream} {key} --follow[/]")


@model.command("deactivate")
@click.argument("stream")
@click.argument("key")
def model_deactivate(stream, key):
    """Stop a model worker without removing its config."""
    state = _load()
    m = _model_or_die(state, stream, key)
    if not _is_running(m.get("pid")):
        console.print(f"[dim][yellow]{key}[/] is not running on [cyan]{stream}[/].[/]")
        state["streams"][stream]["models"][key]["pid"] = None
        _save(state)
        return
    with console.status(f"Stopping [yellow]{key}[/] on [cyan]{stream}[/]…"):
        _kill_pid(m["pid"])
    state["streams"][stream]["models"][key]["pid"] = None
    _save(state)
    console.print(f"[bold green]?[/] Deactivated [yellow]{key}[/] on [cyan]{stream}[/]")


@model.command("deactivate-all")
@click.argument("stream")
def model_deactivate_all(stream):
    """Stop all running model workers on a stream."""
    state = _load()
    s = _stream_or_die(state, stream)
    stopped = 0
    for k, mv in s.get("models", {}).items():
        if _is_running(mv.get("pid")):
            with console.status(f"Stopping [yellow]{k}[/]…"):
                _kill_pid(mv["pid"])
            state["streams"][stream]["models"][k]["pid"] = None
            stopped += 1
    _save(state)
    console.print(f"[bold green]?[/] Stopped {stopped} model(s) on [cyan]{stream}[/]")


@model.command("list")
@click.argument("stream")
def model_list(stream):
    """List all models attached to a stream and their status."""
    state = _load()
    s = _stream_or_die(state, stream)
    models = s.get("models", {})
    if not models:
        console.print(f"[dim]No models on [cyan]{stream}[/]. "
                      "Use [cyan]stream-mgr model add[/].[/]")
        return

    t = Table(box=box.ROUNDED, header_style="bold magenta",
              title=f"Models on [cyan]{stream}[/]")
    t.add_column("Key",     style="yellow", no_wrap=True)
    t.add_column("Plugin",  style="cyan",   no_wrap=True)
    t.add_column("Status",  no_wrap=True)
    t.add_column("PID",     style="dim",    no_wrap=True)
    t.add_column("Weights", style="dim")
    t.add_column("Conf",    style="dim")
    t.add_column("Classes", style="dim")
    t.add_column("Device",  style="dim")

    dirty = False
    for k, mv in models.items():
        pid = mv.get("pid")
        if pid and not _is_running(pid):
            state["streams"][stream]["models"][k]["pid"] = None
            pid   = None
            dirty = True
        t.add_row(
            k,
            mv.get("plugin", "?"),
            _status_badge(pid),
            str(pid) if pid else "—",
            mv.get("model_path") or "—",
            str(mv.get("conf")),
            mv.get("classes") or "all",
            mv.get("device", "cuda"),
        )
    if dirty:
        _save(state)
    console.print(t)

# --- plugins ------------------------------------------------------------------

@cli.group()
def plugins():
    """List and inspect available plugin files."""
    pass


@plugins.command("list")
def plugins_list():
    """List all plugin files in /app/plugins/."""
    available = _available_plugins()
    if not available:
        console.print(f"[dim]No plugins found in [cyan]{PLUGINS_DIR}[/]. "
                      "Drop a .py file there to add one.[/]")
        return
    t = Table(box=box.ROUNDED, header_style="bold magenta")
    t.add_column("Plugin",      style="cyan")
    t.add_column("File",        style="dim")
    t.add_column("Description", style="dim")
    for name in available:
        path    = PLUGINS_DIR / f"{name}.py"
        # Pull the module docstring as description
        desc    = ""
        try:
            text  = path.read_text()
            lines = text.strip().splitlines()
            if lines and lines[0].startswith('"""'):
                for line in lines[1:]:
                    stripped = line.strip().strip('"')
                    if stripped:
                        desc = stripped
                        break
        except Exception:
            pass
        t.add_row(name, str(path), desc)
    console.print(t)

# --- status -------------------------------------------------------------------

@cli.command()
def status():
    """Show live status of all streams and model workers."""
    state = _load()
    if not state.get("streams"):
        console.print("[dim]No streams configured.[/]")
        return

    dirty = False
    for sname, s in state["streams"].items():
        for k, mv in s.get("models", {}).items():
            if mv.get("pid") and not _is_running(mv["pid"]):
                state["streams"][sname]["models"][k]["pid"] = None
                dirty = True
    if dirty:
        _save(state)

    t = Table(box=box.SIMPLE_HEAVY, header_style="bold")
    t.add_column("Stream",  style="cyan bold", no_wrap=True)
    t.add_column("Key",     style="yellow",    no_wrap=True)
    t.add_column("Plugin",  style="dim",       no_wrap=True)
    t.add_column("Status",  no_wrap=True)
    t.add_column("PID",     style="dim",       no_wrap=True)
    t.add_column("Conf",    style="dim")
    t.add_column("Device",  style="dim")
    t.add_column("Started", style="dim")

    for sname, s in state["streams"].items():
        models = s.get("models", {})
        if not models:
            t.add_row(sname, "[dim]no models[/]", "", "", "", "", "", "")
            continue
        for k, mv in models.items():
            pid     = mv.get("pid")
            started = (mv.get("started_at", "")[:19].replace("T", " ")
                       if mv.get("started_at") else "—")
            t.add_row(
                sname, k,
                mv.get("plugin", "?"),
                _status_badge(pid),
                str(pid) if pid else "—",
                str(mv.get("conf")),
                mv.get("device", "cuda"),
                started,
            )
    console.print(t)

    # Additive: surface recovery metrics (Section 8) below the existing
    # table if the watchdog daemon has run at least once. Purely
    # informational — never affects the table above or any other output.
    wd = state.get(WATCHDOG_STATE_KEY, {})
    m = wd.get("metrics")
    if m:
        console.print(
            f"\n[dim]Recovery:[/] total={m.get('total_recoveries', 0)} "
            f"success={m.get('successful_recoveries', 0)} "
            f"failed={m.get('failed_recoveries', 0)} "
            f"escalation_level={m.get('current_escalation_level', 1)} "
            f"stage={m.get('current_recovery_stage', 'idle')} "
            f"mean_duration_s={m.get('mean_recovery_duration_s')}"
        )

# --- logs ---------------------------------------------------------------------

@cli.command()
@click.argument("stream")
@click.argument("key")
@click.option("--lines",  "-n", default=50, show_default=True)
@click.option("--follow", "-f", is_flag=True)
def logs(stream, key, lines, follow):
    """Tail the log for a specific stream + model key."""
    log_path = LOG_DIR / f"{stream}-{key}.log"
    if not log_path.exists():
        console.print(f"[dim]No log yet for [cyan]{stream}[/]/[yellow]{key}[/].[/]")
        return
    cmd = ["tail", f"-n{lines}"]
    if follow:
        cmd.append("-f")
    cmd.append(str(log_path))
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass

# --- udp ----------------------------------------------------------------------

@cli.group()
def udp():
    """Manage UDP JSON text listeners."""
    pass


@udp.command("start")
@click.argument("name")
@click.option("--port",   "-p", default=9100, show_default=True)
@click.option("--host",   "-H", default="0.0.0.0", show_default=True)
@click.option("--pretty", is_flag=True)
def udp_start(name, port, host, pretty):
    """Start a raw UDP JSON listener on PORT."""
    state     = _load()
    listeners = state.setdefault("udp_listeners", {})
    if name in listeners and _is_running(listeners[name].get("pid")):
        console.print(f"[yellow]?[/]  Listener [cyan]{name}[/] already running.")
        sys.exit(1)

    log_path = LOG_DIR / f"udp-{name}.log"
    log_file = _open_rotating_log(log_path)
    log_file.write(
        f"\n{'-'*60}\n[{datetime.now().isoformat()}] Starting\n{'-'*60}\n"
    )
    log_file.flush()

    cmd = [sys.executable, str(UDP_LISTENER_SCRIPT),
           "--name", name, "--port", str(port), "--host", host]
    if pretty:
        cmd.append("--pretty")

    proc = subprocess.Popen(cmd, stdout=log_file, stderr=log_file,
                            start_new_session=True)
    time.sleep(0.8)
    if proc.poll() is not None:
        console.print(f"[bold red]?[/] Listener exited. "
                      f"Check: [cyan]stream-mgr udp logs {name}[/]")
        sys.exit(1)

    listeners[name] = {
        "name": name, "port": port, "host": host,
        "pretty": pretty, "pid": proc.pid,
        "started_at": datetime.now().isoformat(),
    }
    _save(state)
    console.print(f"[bold green]?[/] Listener [cyan]{name}[/] on "
                  f"[dim]{host}:{port}/udp[/] (PID [dim]{proc.pid}[/])")
    console.print(f"  Follow: [white]stream-mgr udp logs {name} --follow[/]")


@udp.command("stop")
@click.argument("name")
def udp_stop(name):
    """Stop a UDP listener."""
    state     = _load()
    listeners = state.setdefault("udp_listeners", {})
    if name not in listeners:
        console.print(f"[red]?[/] No listener named [cyan]{name}[/].")
        sys.exit(1)
    pid = listeners[name].get("pid")
    if not _is_running(pid):
        console.print(f"[dim]Listener [cyan]{name}[/] is not running.[/]")
        listeners[name]["pid"] = None
        _save(state)
        return
    with console.status(f"Stopping [cyan]{name}[/]…"):
        _kill_pid(pid)
    listeners[name]["pid"] = None
    _save(state)
    console.print(f"[bold green]?[/] Stopped [cyan]{name}[/]")


@udp.command("status")
def udp_status():
    """Show all UDP listeners."""
    state     = _load()
    listeners = state.get("udp_listeners", {})
    if not listeners:
        console.print("[dim]No listeners. Use [cyan]stream-mgr udp start[/].[/]")
        return
    t = Table(box=box.ROUNDED, header_style="bold magenta")
    t.add_column("Name",    style="cyan")
    t.add_column("Status",  no_wrap=True)
    t.add_column("PID",     style="dim")
    t.add_column("Bind",    style="dim")
    t.add_column("Started", style="dim")
    dirty = False
    for s in listeners.values():
        pid = s.get("pid")
        if pid and not _is_running(pid):
            listeners[s["name"]]["pid"] = None
            pid   = None
            dirty = True
        started = (s.get("started_at", "")[:19].replace("T", " ")
                   if s.get("started_at") else "—")
        t.add_row(s["name"], _status_badge(pid), str(pid) if pid else "—",
                  f"{s['host']}:{s['port']}/udp", started)
    if dirty:
        _save(state)
    console.print(t)


@udp.command("logs")
@click.argument("name")
@click.option("--lines",  "-n", default=50, show_default=True)
@click.option("--follow", "-f", is_flag=True)
def udp_logs(name, lines, follow):
    """Tail a UDP listener log."""
    log_path = LOG_DIR / f"udp-{name}.log"
    if not log_path.exists():
        console.print(f"[dim]No log yet for [cyan]{name}[/].[/]")
        return
    cmd = ["tail", f"-n{lines}"]
    if follow:
        cmd.append("-f")
    cmd.append(str(log_path))
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass

# --- server -------------------------------------------------------------------

@cli.group()
def server():
    """MediaMTX management."""
    pass


@server.command("restart")
def server_restart():
    """Restart MediaMTX."""
    subprocess.run(["pkill", "-f", "mediamtx"])
    time.sleep(1)
    proc = subprocess.Popen(
        ["/opt/mediamtx/mediamtx", "/opt/mediamtx/mediamtx.yml"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(1)
    if _is_running(proc.pid):
        console.print(f"[bold green]?[/] MediaMTX restarted (PID {proc.pid})")
    else:
        console.print("[bold red]?[/] MediaMTX failed to start.")


@server.command("paths")
def server_paths():
    """List active MediaMTX paths via HTTP API."""
    try:
        import urllib.request
        with urllib.request.urlopen(
                "http://localhost:9997/v3/paths/list", timeout=3) as r:
            data = json.loads(r.read())
    except Exception as e:
        console.print(f"[red]Could not reach MediaMTX API: {e}[/]")
        return
    items = data.get("items", [])
    if not items:
        console.print("[dim]No active paths.[/]")
        return
    t = Table(box=box.ROUNDED, header_style="bold magenta")
    t.add_column("Path",    style="cyan")
    t.add_column("Source",  style="dim")
    t.add_column("Readers", style="yellow")
    for item in items:
        t.add_row(
            item.get("name", "?"),
            item.get("source", {}).get("type", "—"),
            str(len(item.get("readers", []))),
        )
    console.print(t)


# --- watchdog -----------------------------------------------------------------

WATCHDOG_STATE_KEY = "watchdog"
FFMPEG_PATTERN      = "rtsp://localhost:8554/main"   # unique cmdline fragment
FFMPEG_SOURCE       = "rtsp://192.168.144.25:8554/main.264"
FFMPEG_TARGET       = "rtsp://localhost:8554/main"
MEDIAMTX_BIN        = "/opt/mediamtx/mediamtx"
MEDIAMTX_CFG        = "/opt/mediamtx/mediamtx.yml"

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


DEFAULT_FRAME_TIMEOUT  = _env_int("STREAM_MGR_FRAME_TIMEOUT", 15)     # seconds of log silence -> pipeline restart
DEFAULT_CHECK_INTERVAL = _env_float("STREAM_MGR_CHECK_INTERVAL", 1.0)
BACKOFF_BASE            = _env_float("STREAM_MGR_BACKOFF_BASE", 1.0)
BACKOFF_MAX             = _env_float("STREAM_MGR_BACKOFF_MAX", 10.0)
BACKOFF_WINDOW          = _env_int("STREAM_MGR_BACKOFF_WINDOW", 300)   # seconds; a target's failure count resets after this
MAX_RESTARTS_IN_WINDOW  = _env_int("STREAM_MGR_MAX_RESTARTS_IN_WINDOW", 8)  # cool down after this many restarts in the window

# --- Production lifecycle improvement ---
# How many *consecutive* watchdog cycles must observe "FFmpeg alive but
# MediaMTX shows no publisher / not ready" before we restart FFmpeg. A
# single failed check can be a transient MediaMTX API hiccup; requiring
# several in a row is what avoids unnecessary restarts (see PUBLISHER_
# MISSING / PUBLISHER_NOT_READY handling in the watchdog loop below).
PUBLISHER_FAIL_THRESHOLD = _env_int("STREAM_MGR_PUBLISHER_FAIL_THRESHOLD", 1)

# Timeout for confirming a restarted FFmpeg has actually re-published to
# MediaMTX (wait_for_publisher()), not just that the process exists.
PUBLISHER_VERIFY_TIMEOUT = _env_float("STREAM_MGR_PUBLISHER_VERIFY_TIMEOUT", 4.0)

# --- MediaMTX "alive but unhealthy" detection (Section 2) ---
# A running MediaMTX process is not proof the publisher pipeline works -
# these govern how many consecutive unhealthy observations are required
# before MediaMTX itself is restarted, and how long a stalled/ready=false
# publisher may persist before it counts as unhealthy at all.
MEDIAMTX_HEALTH_FAIL_THRESHOLD  = _env_int("STREAM_MGR_MEDIAMTX_HEALTH_FAIL_THRESHOLD", 2)
MEDIAMTX_READY_FALSE_MAX_S      = _env_float("STREAM_MGR_MEDIAMTX_READY_FALSE_MAX_S", 6.0)
MEDIAMTX_BYTES_FROZEN_MAX_S     = _env_float("STREAM_MGR_MEDIAMTX_BYTES_FROZEN_MAX_S", 6.0)
MEDIAMTX_READER_TIMEOUT_S       = _env_float("STREAM_MGR_MEDIAMTX_READER_TIMEOUT_S", 10.0)

# --- Stream verification (Section 4) ---
# STREAM_READY now requires several consecutive decoded frames, stable
# over a minimum duration, not just a single successful frame read.
STREAM_VERIFY_CONSECUTIVE_FRAMES = _env_int("STREAM_MGR_VERIFY_CONSECUTIVE_FRAMES", 3)
STREAM_VERIFY_STABLE_DURATION_S  = _env_float("STREAM_MGR_VERIFY_STABLE_DURATION_S", 2.0)

# --- RTSP session cleanup (Section 3) ---
# How long to wait for MediaMTX to confirm the old publisher/session is
# fully gone before a new FFmpeg publisher is allowed to launch.
PUBLISHER_REMOVAL_TIMEOUT_S = _env_float("STREAM_MGR_PUBLISHER_REMOVAL_TIMEOUT_S", 8.0)

# --- Recovery escalation (Section 5) ---
# How many consecutive failed recoveries at a given level before moving to
# the next one. Resets to level 1 on any successful recovery.
ESCALATION_FAILURES_PER_LEVEL = _env_int("STREAM_MGR_ESCALATION_FAILURES_PER_LEVEL", 1)
ESCALATION_MAX_LEVEL = 5

# --- Level 5 final recovery: request a container restart from the host ---
# (addendum). stream_mgr.py never touches the Docker socket itself -- it
# POSTs a request to server.py, which is the process that actually runs
# `docker restart`. URL is never hardcoded; configurable per deployment
# (e.g. host.docker.internal on Docker Desktop, or the Jetson host's own
# IP/hostname on Linux where host.docker.internal may not resolve).
STREAM_MGR_BACKEND_URL = os.environ.get(
    "STREAM_MGR_BACKEND_URL", "http://host.docker.internal:5002"
).strip()

# Minimum time between Docker-restart requests, so a flapping camera can't
# trigger repeated container restarts ("restart storms").
DOCKER_RESTART_COOLDOWN_S = _env_float("STREAM_MGR_DOCKER_RESTART_COOLDOWN_S", 300.0)


class _RestartReason:
    """Explicit, machine-readable reasons for an FFmpeg/MediaMTX restart.
    Used in structured log events so operators/stream_recovery.py can tell
    *why* a restart happened without re-deriving it from raw process state."""
    PROCESS_EXITED         = "PROCESS_EXITED"
    PUBLISHER_MISSING      = "PUBLISHER_MISSING"
    PUBLISHER_NOT_READY    = "PUBLISHER_NOT_READY"
    MEDIA_MTX_UNAVAILABLE  = "MEDIA_MTX_UNAVAILABLE"
    OUTPUT_SOCKET_STALE    = "OUTPUT_SOCKET_STALE"
    CAMERA_UNAVAILABLE     = "CAMERA_UNAVAILABLE"
    # --- New reasons for MediaMTX-alive-but-unhealthy detection ---
    MEDIAMTX_UNHEALTHY     = "MEDIAMTX_UNHEALTHY"
    BYTES_FROZEN           = "BYTES_FROZEN"
    READER_DEADLOCK        = "READER_DEADLOCK"
    STALE_PUBLISHER        = "STALE_PUBLISHER"


class RecoveryLevel:
    """Deterministic recovery escalation ladder (Section 5). Escalation only
    ever moves up one level at a time after ESCALATION_FAILURES_PER_LEVEL
    consecutive failures at the current level, and resets to LEVEL_1 on any
    successful recovery. Never jumped directly."""
    LEVEL_1_RECONNECT        = 1  # reconnect RTSP session (soft retry)
    LEVEL_2_RESTART_FFMPEG   = 2  # restart FFmpeg
    LEVEL_3_RESTART_MEDIAMTX = 3  # restart MediaMTX
    LEVEL_4_RESTART_FFMPEG_2 = 4  # restart FFmpeg again (post-MediaMTX restart)
    LEVEL_5_NOTIFY_EXTERNAL  = 5  # notify external recovery manager (mission backend)


def _pgrep(pattern) -> int | None:
    """Return the PID of a process whose cmdline matches `pattern`, else None."""
    pids = _pgrep_all(pattern)
    return pids[0] if pids else None


def _pgrep_all(pattern) -> list[int]:
    """Return ALL PIDs whose cmdline matches `pattern`. Used to detect and
    clean up duplicate FFmpeg/MediaMTX instances (e.g. left over from a
    crashed watchdog cycle)."""
    try:
        out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        return [int(p) for p in out.stdout.split()]
    except Exception:
        return []


def _start_ffmpeg() -> int | None:
    """(Re)start the RTSP relay. Mirrors entrypoint.sh's ffmpeg invocation."""
    cmd = [
        "ffmpeg", "-y",
        "-rtsp_transport", "tcp",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-analyzeduration", "0",
        "-probesize", "32",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-rw_timeout", "5000000",
        "-i", FFMPEG_SOURCE,
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-f", "rtsp", FFMPEG_TARGET,
    ]
    log_file = _open_rotating_log(LOG_DIR / "ffmpeg-relay.log")
    proc = subprocess.Popen(cmd, stdout=log_file, stderr=log_file, start_new_session=True)
    time.sleep(1)
    return proc.pid if proc.poll() is None else None


def _start_mediamtx() -> int | None:
    proc = subprocess.Popen(
        [MEDIAMTX_BIN, MEDIAMTX_CFG],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(1)
    return proc.pid if proc.poll() is None else None


def _mediamtx_path_status(path_name: str = "main") -> dict:
    """
    Query MediaMTX's own HTTP API for the *detailed* status of a path,
    rather than a single boolean.

    --- Why process liveness alone is insufficient ---
    Production testing showed FFmpeg staying alive (PID present, socket to
    the camera ESTABLISHED) while its socket to MediaMTX sat in CLOSE-WAIT:
    FFmpeg had silently stopped publishing without ever exiting. A liveness
    check (`_is_running(pid)`) stays green through that entire failure.
    Only MediaMTX's own view of the path — whether a publisher is present
    and ready — can catch it, which is why this is checked every cycle
    alongside (not instead of) process liveness.
    """
    result = {
        "publisher_exists": False,
        "ready": False,
        "reader_count": 0,
        "publisher_type": None,
        "timestamp": time.time(),
        "reachable": False,
    }
    try:
        import urllib.request as _u
        with _u.urlopen(f"http://localhost:9997/v3/paths/get/{path_name}", timeout=3) as r:
            data = json.loads(r.read())
        result["reachable"] = True
        source = data.get("source") or {}
        result["publisher_exists"] = bool(source)
        result["publisher_type"] = source.get("type")
        result["ready"] = bool(data.get("ready", False))
        result["reader_count"] = len(data.get("readers", []) or [])
    except Exception:
        pass  # unreachable/ambiguous — caller decides how to treat this
    return result


def _processed_stream_ready(path_name: str = "main") -> bool:
    """Backward-compatible boolean view of _mediamtx_path_status(). Treats
    an unreachable MediaMTX API as ready=True so a transient API hiccup
    never piles a second restart on top of an already-alive process check."""
    status = _mediamtx_path_status(path_name)
    if not status["reachable"]:
        return True
    return status["publisher_exists"] and status["ready"]


def _mediamtx_path_status_extended(path_name: str = "main") -> dict:
    """
    Extended view of the MediaMTX path status (Section 7), adding the
    remaining useful fields the HTTP API actually exposes: bytesReceived,
    bytesSent, publisherId, tracks, source. Superset of
    _mediamtx_path_status() so existing callers/behaviour are unaffected;
    only fields that genuinely exist in the /v3/paths/get/<name> response
    are read (no fabricated values).
    """
    result = _mediamtx_path_status(path_name)
    result.update({
        "bytes_received": None,
        "bytes_sent": None,
        "publisher_id": None,
        "tracks": None,
        "source_type": None,
    })
    try:
        import urllib.request as _u
        with _u.urlopen(f"http://localhost:9997/v3/paths/get/{path_name}", timeout=3) as r:
            data = json.loads(r.read())
        result["reachable"] = True
        source = data.get("source") or {}
        result["bytes_received"] = data.get("bytesReceived")
        result["bytes_sent"]     = data.get("bytesSent")
        result["publisher_id"]   = source.get("id")
        result["source_type"]    = source.get("type")
        result["tracks"]         = data.get("tracks")
    except Exception:
        pass  # unreachable/ambiguous — caller decides how to treat this
    return result


def _mediamtx_health_signal(wd: dict, path_name: str = "main") -> tuple[bool, str | None, dict]:
    """
    Detects a MediaMTX that is unhealthy *while its process remains alive*
    (Section 2) — publisher missing/never recreated/stuck, ready=false for
    an extended duration, input bytes frozen, or a reader deadlock
    (readers present but bytesSent frozen). Consecutive-observation state
    is kept in `wd["mtx_health"]` (persisted across watchdog cycles via
    locked_state) so a single noisy sample never triggers escalation.

    bytesReceived and bytesSent are tracked and evaluated independently
    (production-hardening fix): bytesSent only means something once a
    reader actually exists. With zero readers, MediaMTX has nowhere to
    push output, so bytesSent legitimately sits flat forever — that is
    normal idle behaviour, not a stall, and must never contribute to a
    restart. bytesReceived freezing, by contrast, always indicates a real
    problem (nothing is arriving from ffmpeg) regardless of viewers, so
    it is checked unconditionally. This asymmetry is what a single
    combined "both bytes frozen" check (the old behaviour) got wrong: it
    silently required the input to *also* stall before ever detecting a
    genuine reader-side deadlock, and — depending on framing — could
    treat an idle no-viewer stream as unhealthy too.

    Returns (unhealthy, reason, status) — reason is one of the
    _RestartReason MEDIAMTX_* / BYTES_FROZEN / READER_DEADLOCK /
    STALE_PUBLISHER values, or None if healthy.
    """
    now = time.time()
    h = wd.setdefault("mtx_health", {
        "ready_false_since": None,
        "bytes_recv_prev": None, "bytes_sent_prev": None,
        "bytes_recv_frozen_since": None,
        "bytes_sent_frozen_since": None,
        # Legacy key kept for any external readers of persisted state;
        # no longer used to gate decisions.
        "bytes_frozen_since": None,
        "reader_stall_since": None,
    })
    status = _mediamtx_path_status_extended(path_name)

    if not status["reachable"]:
        # Ambiguous — don't accumulate unhealthy state off an API blip.
        h["ready_false_since"] = None
        h["bytes_recv_frozen_since"] = None
        h["bytes_sent_frozen_since"] = None
        h["reader_stall_since"] = None
        return False, None, status

    # publisher missing / never recreated
    if not status["publisher_exists"]:
        h["ready_false_since"] = h["ready_false_since"] or now
        if now - h["ready_false_since"] >= MEDIAMTX_READY_FALSE_MAX_S:
            return True, _RestartReason.STALE_PUBLISHER, status
        return False, None, status
    else:
        h["ready_false_since"] = None if status["ready"] else (h["ready_false_since"] or now)
        if not status["ready"] and now - h["ready_false_since"] >= MEDIAMTX_READY_FALSE_MAX_S:
            return True, _RestartReason.PUBLISHER_NOT_READY, status

    br, bs = status["bytes_received"], status["bytes_sent"]
    reader_count = status.get("reader_count") or 0

    # Input leg: bytesReceived freezing always indicates a real stall
    # (nothing arriving from ffmpeg/camera) — evaluated unconditionally,
    # independent of whether anyone is watching.
    recv_frozen = br is not None and br == h["bytes_recv_prev"]
    if recv_frozen:
        h["bytes_recv_frozen_since"] = h["bytes_recv_frozen_since"] or now
        if now - h["bytes_recv_frozen_since"] >= MEDIAMTX_BYTES_FROZEN_MAX_S:
            h["bytes_recv_prev"], h["bytes_sent_prev"] = br, bs
            return True, _RestartReason.BYTES_FROZEN, status
    else:
        h["bytes_recv_frozen_since"] = None

    # Output leg: bytesSent freezing is only meaningful with an active
    # reader attached. Zero readers -> zero bytesSent is expected, so the
    # freeze timer is not even started in that case, and any timer
    # already running is cleared the moment the last reader leaves.
    sent_frozen = bs is not None and bs == h["bytes_sent_prev"]
    if reader_count > 0 and sent_frozen:
        h["bytes_sent_frozen_since"] = h["bytes_sent_frozen_since"] or now
        if now - h["bytes_sent_frozen_since"] >= MEDIAMTX_READER_TIMEOUT_S:
            h["bytes_recv_prev"], h["bytes_sent_prev"] = br, bs
            return True, _RestartReason.READER_DEADLOCK, status
    else:
        h["bytes_sent_frozen_since"] = None

    h["bytes_recv_prev"], h["bytes_sent_prev"] = br, bs
    return False, None, status


def verify_stream_frames(stream_url: str = "rtsp://localhost:8554/main",
                          timeout: float = 5.0,
                          consecutive_frames: int = STREAM_VERIFY_CONSECUTIVE_FRAMES,
                          stable_duration: float = STREAM_VERIFY_STABLE_DURATION_S) -> bool:
    """
    --- Why publisher health alone is insufficient ---
    MediaMTX reporting publisher_exists=True and ready=True only confirms
    FFmpeg opened an RTSP session and MediaMTX accepted it as a publisher.
    It does NOT confirm actual video frames are flowing end-to-end through
    Camera -> FFmpeg -> MediaMTX; a publisher can register successfully and
    then stall (e.g. FFmpeg negotiated the session but the camera feed
    behind it died). This is the final end-to-end confirmation: it opens
    the same RTSP path a real consumer would.

    --- Why a single decoded frame is not enough (Section 4) ---
    A lone successful read can be a decoder fluke (e.g. one cached/garbage
    frame before the feed actually dies). This now requires
    `consecutive_frames` successive non-empty decoded frames, and that
    those successes span at least `stable_duration` seconds of real time,
    before declaring the stream verified. Any failed/empty read resets the
    consecutive-success streak. `timeout` remains the hard ceiling on how
    long verification may take overall.
    """
    cap = None
    try:
        import cv2
        backend = getattr(cv2, "CAP_FFMPEG", 0)
        cap = cv2.VideoCapture(stream_url, backend) if backend else cv2.VideoCapture(stream_url)

        deadline = time.time() + timeout
        consecutive = 0
        streak_start = None
        while time.time() < deadline:
            # isOpened() alone is not proof of a working feed — a capture
            # can report "opened" while never yielding a real frame. Only
            # a successful, non-empty decoded frame counts as progress.
            ret, frame = cap.read()
            if ret and frame is not None and frame.size > 0:
                consecutive += 1
                streak_start = streak_start or time.time()
                elapsed_streak = time.time() - streak_start
                if consecutive >= consecutive_frames and elapsed_streak >= stable_duration:
                    return True
            else:
                consecutive = 0
                streak_start = None
            time.sleep(0.2)
        return False
    except Exception:
        return False
    finally:
        if cap is not None:
            cap.release()


def wait_for_publisher(path_name: str = "main", timeout: float = PUBLISHER_VERIFY_TIMEOUT) -> bool:
    """
    --- Why restart verification is necessary ---
    Starting a new FFmpeg process is not the same as recovering the
    stream — the whole point of this fix is that a "process is running"
    signal was exactly what missed the original failure. So after every
    FFmpeg (re)start we actively poll MediaMTX until it reports a
    publisher AND ready==true, then perform one further end-to-end check
    (verify_stream_frames) confirming real frames are actually flowing,
    or we time out and log the restart as unsuccessful instead of
    assuming it worked.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = _mediamtx_path_status(path_name)
        if status["publisher_exists"] and status["ready"]:
            remaining = max(0.5, deadline - time.time())
            if verify_stream_frames(timeout=min(remaining, 5.0)):
                return True
            console.print(f"[yellow]?[/] [{datetime.now().isoformat()}] "
                          "Publisher healthy but no frames received.")
            # Do not restart here — keep polling until the outer timeout.
        time.sleep(1)
    return False


def _wait_publisher_removed(path_name: str = "main",
                             timeout: float = PUBLISHER_REMOVAL_TIMEOUT_S) -> bool:
    """
    RTSP session cleanup (Section 3): before launching a *new* FFmpeg
    publisher, confirm MediaMTX itself has actually dropped the old
    publisher/session, not just that the old FFmpeg PID is gone. Racing a
    new publish attempt against a not-yet-cleared old session is what
    causes overlapping-publisher and stale-session failures. Returns True
    once MediaMTX reports no publisher (or once timeout elapses — the
    caller proceeds regardless since _stop_ffmpeg_relay has already done a
    hard process-level teardown by this point).
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = _mediamtx_path_status(path_name)
        if not status["reachable"] or not status["publisher_exists"]:
            return True
        time.sleep(0.5)
    return not _mediamtx_path_status(path_name)["publisher_exists"]


def _ffmpeg_socket_to_mediamtx_stale() -> bool:
    """Best-effort detection of the exact symptom observed in production:
    an FFmpeg socket to MediaMTX (127.0.0.1:8554) stuck in CLOSE-WAIT
    rather than ESTABLISHED or absent. Uses `ss`; if it's unavailable this
    fails open (returns False) rather than blocking a restart on a
    missing diagnostic tool."""
    try:
        out = subprocess.run(["ss", "-tnp"], capture_output=True, text=True, timeout=3)
        for line in out.stdout.splitlines():
            if "127.0.0.1:8554" in line and "ffmpeg" in line.lower():
                return "CLOSE-WAIT" in line
        return False
    except Exception:
        return False


def _stop_ffmpeg_relay(pid: int | None, timeout: float = 8.0) -> None:
    """
    Full teardown of the FFmpeg relay before restarting it.

    Just killing the tracked PID is not enough to guarantee a clean
    restart: leftover duplicate relays (e.g. from a previous crashed
    watchdog cycle) can race the new instance for the RTSP path, and a
    lingering half-closed socket to MediaMTX can make the *new* FFmpeg
    process look published while still not actually flowing. So this:
      1. gracefully terminates (SIGTERM, then SIGKILL via _kill_pid) every
         process matching the FFmpeg relay pattern — not just `pid`,
      2. re-checks for any survivors and force-kills them,
      3. waits for the old FFmpeg->MediaMTX TCP socket to clear.
    """
    for p in _pgrep_all(FFMPEG_PATTERN):
        _kill_pid(p, timeout=timeout)

    deadline = time.time() + timeout
    while _pgrep_all(FFMPEG_PATTERN) and time.time() < deadline:
        time.sleep(0.5)
    for p in _pgrep_all(FFMPEG_PATTERN):  # last-resort sweep
        try:
            os.kill(p, signal.SIGKILL)
        except ProcessLookupError:
            pass

    deadline = time.time() + timeout
    while _ffmpeg_socket_to_mediamtx_stale() and time.time() < deadline:
        time.sleep(0.5)

    # Never allow overlapping publishers: confirm MediaMTX itself has
    # dropped the old publisher/session before returning control to the
    # caller, who is about to launch a brand-new FFmpeg publisher.
    _wait_publisher_removed()


def _camera_reachable(timeout: float = 2.0) -> bool:
    """Quick TCP reachability check against the camera's RTSP source.
    Distinguishes an FFmpeg-side fault from the camera itself being
    unreachable (CAMERA_UNAVAILABLE), which is worth logging distinctly
    even though the recovery action — restart FFmpeg and let its own
    --reconnect flags retry — stays the same."""
    try:
        from urllib.parse import urlparse
        import socket as _socket
        parsed = urlparse(FFMPEG_SOURCE)
        host, port = parsed.hostname, parsed.port or 554
        with _socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _start_worker(state, stream, key) -> int | None:
    """Restart a model worker from its saved config (mirrors model_activate)."""
    s, m = state["streams"][stream], state["streams"][stream]["models"][key]
    log_file = _open_rotating_log(LOG_DIR / f"{stream}-{key}.log")
    log_file.write(f"\n[{datetime.now().isoformat()}] Watchdog restart\n")
    log_file.flush()
    cmd = [
        sys.executable, str(WORKER_SCRIPT),
        "--name", f"{stream}/{key}", "--source", s["source"],
        "--plugin", m["plugin"], "--model-path", m.get("model_path", ""),
        "--conf", str(m["conf"]), "--classes", m.get("classes", ""),
        "--device", m.get("device", "cuda"),
        "--plugin-args", json.dumps(m.get("plugin_args", {})),
    ]
    if m.get("half"):
        cmd.append("--half")
    if m.get("warmup"):
        cmd.append("--warmup")
    proc = subprocess.Popen(cmd, stdout=log_file, stderr=log_file, start_new_session=True)
    time.sleep(1)
    return proc.pid if proc.poll() is None else None


class _RestartTracker:
    """Per-target rolling-window failure counter + exponential backoff.
    Prevents infinite restart loops by cooling down after too many failures."""

    def __init__(self, label):
        self.label = label
        self.fails = 0
        self.window_start = time.time()
        self.cooling_until = 0.0

    def allowed(self) -> bool:
        now = time.time()
        if now - self.window_start > BACKOFF_WINDOW:
            self.fails, self.window_start = 0, now
        if now < self.cooling_until:
            return False
        if self.fails >= MAX_RESTARTS_IN_WINDOW:
            self.cooling_until = now + BACKOFF_WINDOW
            console.print(f"[bold red]?[/] {self.label}: too many restarts, "
                          f"cooling down {int(BACKOFF_WINDOW)}s.")
            return False
        return True

    def record_attempt(self):
        self.fails += 1

    def delay(self) -> float:
        return min(BACKOFF_BASE * (2 ** max(self.fails - 1, 0)), BACKOFF_MAX)


def _init_metrics(wd: dict) -> dict:
    """Ensure wd['metrics'] exists with all Section 8 fields, without
    clobbering values already persisted from a previous watchdog run."""
    return wd.setdefault("metrics", {
        "total_recoveries": 0,
        "successful_recoveries": 0,
        "failed_recoveries": 0,
        "current_recovery_stage": "idle",
        "last_recovery_reason": None,
        "last_recovery_duration_s": None,
        "mean_recovery_duration_s": None,
        "current_escalation_level": RecoveryLevel.LEVEL_1_RECONNECT,
        "publisher_uptime_s": None,
        "publisher_ready_since": None,
        "verification_latency_s": None,
    })


def _record_recovery_start(wd: dict, reason: str) -> float:
    """Marks the start of a recovery attempt; returns the start timestamp
    to be passed to _record_recovery_result()."""
    m = _init_metrics(wd)
    m["current_recovery_stage"] = "in_progress"
    m["last_recovery_reason"] = reason
    return time.time()


def _append_recovery_history(record: dict) -> None:
    """
    Appends one recovery event to the on-disk, bounded recovery-history
    log (production-hardening addendum, Section 2). Keeps only the most
    recent RECOVERY_HISTORY_MAX entries.

    Deliberately best-effort: any failure here (disk full, permissions,
    concurrent-write hiccup) is swallowed after a single console warning
    so a logging problem can never interrupt stream recovery itself.
    """
    try:
        RECOVERY_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        history = []
        if RECOVERY_HISTORY_FILE.exists():
            try:
                history = json.loads(RECOVERY_HISTORY_FILE.read_text(encoding="utf-8"))
                if not isinstance(history, list):
                    history = []
            except (json.JSONDecodeError, OSError):
                history = []
        history.append(record)
        if len(history) > RECOVERY_HISTORY_MAX:
            history = history[-RECOVERY_HISTORY_MAX:]
        tmp = RECOVERY_HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(history), encoding="utf-8")
        tmp.replace(RECOVERY_HISTORY_FILE)  # atomic on POSIX
    except Exception as exc:  # noqa: BLE001 - logging must never break recovery
        console.print(f"[dim yellow]WARN: recovery history write failed: {exc}[/]")


def _record_recovery_result(wd: dict, success: bool, duration_s: float, **context) -> None:
    """
    Updates recovery metrics after an attempt completes (Section 8), and
    persists the event to RECOVERY_HISTORY_FILE (Section 2).

    Extra keyword context (all optional, used for the history record only):
      reason, camera_state, publisher_status, mediamtx_status,
      escalation_level
    """
    m = _init_metrics(wd)
    m["total_recoveries"] += 1
    if success:
        m["successful_recoveries"] += 1
        m["current_recovery_stage"] = "idle"
        m["publisher_ready_since"] = time.time()
    else:
        m["failed_recoveries"] += 1
        m["current_recovery_stage"] = "failed"
    m["last_recovery_duration_s"] = round(duration_s, 3)
    prev_mean = m.get("mean_recovery_duration_s")
    n = m["total_recoveries"]
    m["mean_recovery_duration_s"] = round(
        (duration_s if prev_mean is None else (prev_mean * (n - 1) + duration_s) / n), 3
    )

    _append_recovery_history({
        "timestamp": time.time(),
        "success": success,
        "duration_s": duration_s,
        "reason": context.get("reason"),
        "escalation_level": context.get("escalation_level", m.get("current_escalation_level")),
        "camera_status": context.get("camera_state", wd.get("camera_state")),
        "publisher_status": context.get("publisher_status"),
        "mediamtx_status": context.get("mediamtx_status"),
    })


def _escalate(wd: dict, emit_fn) -> int:
    """
    Deterministic recovery escalation (Section 5): advances exactly one
    level after ESCALATION_FAILURES_PER_LEVEL consecutive failures *at the
    current level*, never jumping directly to a higher level. Returns the
    (possibly unchanged) current level.
    """
    m = _init_metrics(wd)
    wd["escalation_fail_streak"] = wd.get("escalation_fail_streak", 0) + 1
    level = m.get("current_escalation_level", RecoveryLevel.LEVEL_1_RECONNECT)
    if wd["escalation_fail_streak"] >= ESCALATION_FAILURES_PER_LEVEL and level < ESCALATION_MAX_LEVEL:
        new_level = level + 1
        wd["escalation_fail_streak"] = 0
        m["current_escalation_level"] = new_level
        emit_fn("escalation_level_changed", previous_level=level, new_level=new_level)
        return new_level
    return level


def _reset_escalation(wd: dict, emit_fn) -> None:
    """Resets escalation to LEVEL_1 after any successful recovery
    (Section 5: 'Reset escalation after successful recovery')."""
    m = _init_metrics(wd)
    prev = m.get("current_escalation_level", RecoveryLevel.LEVEL_1_RECONNECT)
    wd["escalation_fail_streak"] = 0
    if prev != RecoveryLevel.LEVEL_1_RECONNECT:
        m["current_escalation_level"] = RecoveryLevel.LEVEL_1_RECONNECT
        emit_fn("escalation_level_changed", previous_level=prev,
                new_level=RecoveryLevel.LEVEL_1_RECONNECT)


WATCHDOG_DAEMON_KEY = "watchdog_daemon"


@cli.command("watchdog")
@click.option("--frame-timeout", default=DEFAULT_FRAME_TIMEOUT, show_default=True,
              help="Seconds without stream activity before the pipeline is restarted.")
@click.option("--interval", default=DEFAULT_CHECK_INTERVAL, show_default=True,
              help="Seconds between health checks.")
@click.option("--daemon", is_flag=True,
              help="Launch the watchdog as a detached background process "
                   "instead of blocking the current terminal. This is what "
                   "entrypoint.sh uses so the operator never runs this by hand.")
@click.option("--stop", "do_stop", is_flag=True, help="Stop a running watchdog daemon.")
@click.option("--status", "do_status", is_flag=True, help="Show watchdog daemon status.")
def watchdog(frame_timeout, interval, daemon, do_stop, do_status):
    """
    Run the stream watchdog.

    Every --interval seconds, checks FFmpeg, MediaMTX, each active model
    worker, and per-stream last-frame activity (worker log mtime). Dead
    FFmpeg/workers are restarted individually; a stream silent for longer
    than --frame-timeout gets its whole pipeline restarted. All restarts
    use exponential backoff with a rolling-window cap to avoid infinite
    restart loops. Persistent failures (cooldown reached) are logged as
    structured events to logs/watchdog.log for stream_recovery.py to
    escalate to a container restart.

    Use --daemon to run detached (recommended; entrypoint.sh does this
    automatically), or --stop / --status to manage that daemon.
    """
    if do_stop:
        with locked_state() as state:
            wd = state.get(WATCHDOG_DAEMON_KEY, {})
            pid = wd.get("pid")
            if not _is_running(pid):
                console.print("[dim]Watchdog daemon is not running.[/]")
            else:
                _kill_pid(pid)
                console.print("[bold green]?[/] Watchdog daemon stopped.")
            state[WATCHDOG_DAEMON_KEY] = {}
        return

    if do_status:
        state = _load()
        wd = state.get(WATCHDOG_DAEMON_KEY, {})
        pid = wd.get("pid")
        if _is_running(pid):
            console.print(f"[bold green]? RUNNING[/] Watchdog daemon PID [dim]{pid}[/]")
        else:
            console.print("[dim]Watchdog daemon is not running.[/]")
        return

    if daemon:
        with locked_state() as state:
            wd = state.get(WATCHDOG_DAEMON_KEY, {})
            if _is_running(wd.get("pid")):
                console.print(f"[yellow]?[/]  Watchdog daemon already running "
                              f"(PID {wd['pid']}).")
                sys.exit(1)
            log_path = LOG_DIR / "watchdog.log"
            log_file = _open_rotating_log(log_path)
            log_file.write(f"\n[{datetime.now().isoformat()}] Daemon starting\n")
            log_file.flush()
            proc = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "watchdog",
                 "--frame-timeout", str(frame_timeout), "--interval", str(interval)],
                stdout=log_file, stderr=log_file, start_new_session=True,
            )
            time.sleep(0.8)
            if proc.poll() is not None:
                console.print("[bold red]?[/] Watchdog daemon exited immediately. "
                               f"Check: [cyan]tail {log_path}[/]")
                sys.exit(1)
            state[WATCHDOG_DAEMON_KEY] = {
                "pid": proc.pid, "started_at": datetime.now().isoformat(),
            }
        console.print(f"[bold green]?[/] Watchdog daemon started (PID [dim]{proc.pid}[/])")
        return

    console.print(f"[bold cyan]Watchdog started.[/] "
                  f"interval={interval}s frame_timeout={frame_timeout}s")
    trackers: dict[str, _RestartTracker] = {}

    def tracker(key):
        return trackers.setdefault(key, _RestartTracker(key))

    shutdown = {"flag": False}

    def _sig(signum, _frame):
        console.print(f"\n[dim]Watchdog received signal {signum}, shutting down…[/]")
        shutdown["flag"] = True

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    def _emit_watchdog_event(event: str, **fields):
        """
        Write a structured [STREAM_MGR_EVENT] line to a shared watchdog log.
        stream_recovery.py can tail this file (in addition to per-worker
        logs) to detect persistent, in-container-unrecoverable failures
        (e.g. FFmpeg/MediaMTX stuck in cooldown) and escalate to a Docker
        container restart. This is the ONLY integration point between the
        two watchdogs — stream_recovery never re-implements process checks.
        """
        payload = {"event": event, "ts": time.time(), **fields}
        watchdog_log = LOG_DIR / "watchdog.log"
        _rotate_if_needed(watchdog_log)
        with open(watchdog_log, "a", encoding="utf-8") as f:
            f.write(f"[STREAM_MGR_EVENT] {json.dumps(payload)}\n")

    while not shutdown["flag"]:
        with locked_state() as state:
            wd = state.setdefault(WATCHDOG_STATE_KEY, {"ffmpeg_pid": None})

            metrics = _init_metrics(wd)

            # -- Camera reachability transition logging --
            # Tracked independently of restart decisions so operators get
            # CAMERA_CONNECTED/CAMERA_LOST events even when FFmpeg's own
            # --reconnect flags are quietly absorbing a brief outage.
            cam_reachable_now = _camera_reachable()
            prev_camera_state = wd.get("camera_state")
            if prev_camera_state is not True and cam_reachable_now:
                _emit_watchdog_event("CAMERA_CONNECTED", camera_source=FFMPEG_SOURCE)
            elif prev_camera_state is not False and not cam_reachable_now:
                _emit_watchdog_event("CAMERA_LOST", camera_source=FFMPEG_SOURCE)
            wd["camera_state"] = cam_reachable_now

            # -- FFmpeg --
            # --- Why publisher health is monitored (not just PID liveness) ---
            # See _mediamtx_path_status()'s docstring: the production failure
            # this addresses had FFmpeg alive with an ESTABLISHED socket to
            # the camera, yet CLOSE-WAIT to MediaMTX — a dead publish path
            # with a perfectly healthy-looking process. So every cycle we
            # check both PID liveness AND MediaMTX's own publisher/ready
            # state, and only ever touch MediaMTX itself if ITS process has
            # exited OR is unhealthy-while-alive (see the "-- MediaMTX --"
            # blocks below).
            ffmpeg_pid = wd.get("ffmpeg_pid")
            was_running = _is_running(ffmpeg_pid)
            if not was_running:
                ffmpeg_pid = _pgrep(FFMPEG_PATTERN)
                if wd.get("ffmpeg_pid") and not _is_running(wd.get("ffmpeg_pid")):
                    _emit_watchdog_event("FFMPEG_EXITED", ffmpeg_pid=wd.get("ffmpeg_pid"))
            # Guard against duplicate relays: pgrep -f can match more than
            # one process if a previous instance leaked; kill any extras.
            for extra_pid in _pgrep_all(FFMPEG_PATTERN):
                if extra_pid != ffmpeg_pid:
                    console.print(f"[yellow]?[/] Killing duplicate FFmpeg PID {extra_pid}.")
                    _kill_pid(extra_pid)

            restart_reason = None
            mtx_status = None
            if not _is_running(ffmpeg_pid):
                restart_reason = (_RestartReason.CAMERA_UNAVAILABLE if not cam_reachable_now
                                   else _RestartReason.PROCESS_EXITED)
                wd["publisher_fail_count"] = 0  # not a publisher-side failure
            else:
                mtx_status = _mediamtx_path_status()
                if not mtx_status["reachable"]:
                    # Ambiguous — a MediaMTX API blip shouldn't by itself
                    # trigger a restart, but also shouldn't mask a real
                    # problem, so the consecutive-failure streak resets and
                    # a later genuine failure needs fresh confirmations.
                    wd["publisher_fail_count"] = 0
                elif _ffmpeg_socket_to_mediamtx_stale():
                    # --- Why consecutive failures are required ---
                    # This is the exact production symptom (FFmpeg alive,
                    # socket to MediaMTX in CLOSE-WAIT). Still require
                    # PUBLISHER_FAIL_THRESHOLD consecutive confirmations
                    # before restarting, so one noisy check doesn't restart
                    # a relay that's about to recover on its own.
                    wd["publisher_fail_count"] = wd.get("publisher_fail_count", 0) + 1
                    if wd["publisher_fail_count"] >= PUBLISHER_FAIL_THRESHOLD:
                        restart_reason = _RestartReason.OUTPUT_SOCKET_STALE
                elif not mtx_status["publisher_exists"]:
                    wd["publisher_fail_count"] = wd.get("publisher_fail_count", 0) + 1
                    if wd["publisher_fail_count"] >= PUBLISHER_FAIL_THRESHOLD:
                        restart_reason = _RestartReason.PUBLISHER_MISSING
                        _emit_watchdog_event("PUBLISHER_DESTROYED", path="main")
                elif not mtx_status["ready"]:
                    wd["publisher_fail_count"] = wd.get("publisher_fail_count", 0) + 1
                    if wd["publisher_fail_count"] >= PUBLISHER_FAIL_THRESHOLD:
                        restart_reason = _RestartReason.PUBLISHER_NOT_READY
                else:
                    wd["publisher_fail_count"] = 0  # healthy — reset streak

            if restart_reason:
                t = tracker("ffmpeg")
                if t.allowed():
                    restart_start = _record_recovery_start(wd, restart_reason)
                    level = metrics["current_escalation_level"]
                    console.print(f"[yellow]?[/] [{datetime.now().isoformat()}] "
                                  f"FFmpeg restart needed ({restart_reason}, "
                                  f"escalation_level={level}), restarting…")
                    t.record_attempt()
                    _emit_watchdog_event(
                        "RECOVERY_STARTED", reason=restart_reason,
                        escalation_level=level, restart_count=t.fails,
                        ffmpeg_pid=ffmpeg_pid, publisher_status=(mtx_status or {}),
                    )

                    # Full teardown (graceful -> SIGKILL, duplicate cleanup,
                    # stale-socket wait, publisher-removal confirmation)
                    # BEFORE restarting — see _stop_ffmpeg_relay() docstring
                    # for why a bare kill of the tracked PID alone is not
                    # sufficient here. This is Level 1/2 of the escalation
                    # ladder (reconnect / restart FFmpeg).
                    _stop_ffmpeg_relay(ffmpeg_pid)
                    time.sleep(t.delay())
                    ffmpeg_pid = _start_ffmpeg()
                    wd["publisher_fail_count"] = 0
                    if ffmpeg_pid is not None:
                        _emit_watchdog_event("FFMPEG_STARTED", ffmpeg_pid=ffmpeg_pid)

                    # Verify recovery against MediaMTX itself rather than
                    # assuming success once the new PID exists. Publisher
                    # lifecycle: launch -> wait for publisher -> ready ->
                    # bytes moving -> decoded frames -> STREAM_READY.
                    recovered = ffmpeg_pid is not None and wait_for_publisher()
                    elapsed = round(time.time() - restart_start, 2)
                    _record_recovery_result(
                        wd, recovered, elapsed,
                        reason=restart_reason, escalation_level=level,
                        camera_state=wd.get("camera_state"),
                        publisher_status=(mtx_status or {}),
                    )

                    if recovered:
                        _emit_watchdog_event("PUBLISHER_CREATED", path="main", ffmpeg_pid=ffmpeg_pid)
                        _emit_watchdog_event("PUBLISHER_READY", path="main", ffmpeg_pid=ffmpeg_pid)
                        _emit_watchdog_event("STREAM_VERIFIED", path="main", ffmpeg_pid=ffmpeg_pid,
                                              verification_latency_s=elapsed)
                        verified_status = _mediamtx_path_status_extended()
                        if (verified_status.get("reader_count") or 0) > 0:
                            _emit_watchdog_event("RECOVERY_VERIFIED",
                                                  reason="PUBLISHER_HEALTHY_ACTIVE_VIEWERS", path="main")
                        else:
                            _emit_watchdog_event("RECOVERY_VERIFIED",
                                                  reason="PUBLISHER_HEALTHY_NO_VIEWERS", path="main")
                        _emit_watchdog_event(
                            "RECOVERY_COMPLETED", reason=restart_reason,
                            publisher_status=(mtx_status or {}), restart_count=t.fails,
                            elapsed_recovery_s=elapsed, ffmpeg_pid=ffmpeg_pid,
                        )
                        _reset_escalation(wd, _emit_watchdog_event)
                        notify_backend("processed_stream_restarted", pid=ffmpeg_pid,
                                        reason=restart_reason)
                    else:
                        _emit_watchdog_event("FRAME_DECODE_FAILED", path="main", ffmpeg_pid=ffmpeg_pid)
                        _emit_watchdog_event(
                            "RECOVERY_FAILED", reason=restart_reason,
                            publisher_status=(mtx_status or {}), restart_count=t.fails,
                            elapsed_recovery_s=elapsed, ffmpeg_pid=ffmpeg_pid,
                        )
                        console.print(f"[bold red]?[/] [{datetime.now().isoformat()}] "
                                      f"FFmpeg restarted but MediaMTX publisher did not "
                                      f"become ready within {PUBLISHER_VERIFY_TIMEOUT}s.")
                        new_level = _escalate(wd, _emit_watchdog_event)
                        # Level 3: publisher-recovery alone keeps failing —
                        # MediaMTX itself is treated as suspect and restarted
                        # (graceful) alongside FFmpeg, then re-verified.
                        if new_level >= RecoveryLevel.LEVEL_3_RESTART_MEDIAMTX:
                            console.print(f"[bold yellow]?[/] Escalating to level {new_level}: "
                                          "restarting MediaMTX.")
                            mtx_restart_start = time.time()
                            _kill_pid(_pgrep(MEDIAMTX_BIN))
                            _start_mediamtx()
                            _emit_watchdog_event(
                                "MEDIAMTX_RESTARTED", reason="escalation",
                                escalation_level=new_level,
                                elapsed_recovery_s=round(time.time() - mtx_restart_start, 2),
                            )
                        # Level 5: recovery has escalated to the top of the
                        # ladder — notify the external/mission recovery
                        # manager rather than silently keep retrying alone.
                        if new_level >= RecoveryLevel.LEVEL_5_NOTIFY_EXTERNAL:
                            notify_backend("recovery_escalation_critical",
                                           reason=restart_reason,
                                           escalation_level=new_level,
                                           restart_count=t.fails)
                            # FINAL recovery step: all in-process recovery
                            # (FFmpeg/MediaMTX restarts, publisher/frame
                            # verification, escalation) has been exhausted.
                            # Ask server.py to `docker restart` this
                            # container, subject to DOCKER_RESTART_COOLDOWN_S.
                            _request_docker_restart(
                                wd, _emit_watchdog_event,
                                reason=restart_reason,
                                escalation_level=new_level,
                                restart_count=t.fails,
                            )
                else:
                    _emit_watchdog_event("cooldown", target="ffmpeg", reason=restart_reason,
                                          fails=t.fails)
            wd["ffmpeg_pid"] = ffmpeg_pid

            # -- MediaMTX (process exited) --
            # Restarted whenever the MediaMTX *process itself* has exited —
            # an unready/missing publisher alone is an FFmpeg-side problem
            # (handled above) and must never on its own cause MediaMTX to be
            # restarted, since that would drop every other reader.
            if not _is_running(_pgrep(MEDIAMTX_BIN)):
                t = tracker("mediamtx")
                if t.allowed():
                    restart_start = time.time()
                    console.print(f"[yellow]?[/] [{datetime.now().isoformat()}] "
                                  "MediaMTX down, restarting…")
                    t.record_attempt()
                    time.sleep(t.delay())
                    _start_mediamtx()
                    _emit_watchdog_event(
                        "MEDIAMTX_RESTARTED",
                        reason=_RestartReason.MEDIA_MTX_UNAVAILABLE,
                        restart_count=t.fails,
                        elapsed_recovery_s=round(time.time() - restart_start, 2),
                    )
                else:
                    _emit_watchdog_event("cooldown", target="mediamtx",
                                          reason=_RestartReason.MEDIA_MTX_UNAVAILABLE,
                                          fails=t.fails)

            # -- MediaMTX (alive but unhealthy) -- (Section 2)
            # Process liveness alone is insufficient: publisher missing/
            # never recreated, stuck ready=false, frozen bytes, or a reader
            # deadlock can all persist while MediaMTX's own process stays
            # up. Require MEDIAMTX_HEALTH_FAIL_THRESHOLD consecutive
            # unhealthy observations (never a single sample) before
            # escalating to a graceful MediaMTX restart, so a transient
            # blip is never mistaken for a real failure.
            elif _is_running(_pgrep(MEDIAMTX_BIN)):
                unhealthy, mtx_reason, ext_status = _mediamtx_health_signal(wd)

                # -- Subscriber presence transition logging --
                # Logged only on change (never every poll cycle) so an
                # idle, unwatched stream doesn't spam the logs, while
                # still making the "nobody's watching" state visible to
                # operators for context on why bytesSent sits at 0.
                reader_count = ext_status.get("reader_count") or 0
                prev_subscriber_state = wd.get("subscriber_state")
                if reader_count == 0 and prev_subscriber_state != "none":
                    _emit_watchdog_event("NO_ACTIVE_SUBSCRIBERS", path="main")
                    _emit_watchdog_event("OUTPUT_IDLE_NO_VIEWERS", path="main",
                                          bytesReceived=ext_status.get("bytes_received"))
                    wd["subscriber_state"] = "none"
                elif reader_count > 0 and prev_subscriber_state != "active":
                    wd["subscriber_state"] = "active"

                if mtx_reason == _RestartReason.BYTES_FROZEN:
                    _emit_watchdog_event("BYTES_STALLED", path="main",
                                          bytesReceived=ext_status.get("bytes_received"),
                                          bytesSent=ext_status.get("bytes_sent"))
                if mtx_reason == _RestartReason.READER_DEADLOCK:
                    _emit_watchdog_event("READER_TIMEOUT", path="main",
                                          reader_count=ext_status.get("reader_count"))
                if unhealthy:
                    wd["mtx_unhealthy_count"] = wd.get("mtx_unhealthy_count", 0) + 1
                else:
                    wd["mtx_unhealthy_count"] = 0

                if wd["mtx_unhealthy_count"] >= MEDIAMTX_HEALTH_FAIL_THRESHOLD:
                    t = tracker("mediamtx_health")
                    if t.allowed():
                        restart_start = _record_recovery_start(wd, _RestartReason.MEDIAMTX_UNHEALTHY)
                        console.print(f"[bold yellow]?[/] [{datetime.now().isoformat()}] "
                                      f"MediaMTX unhealthy while alive ({mtx_reason}), "
                                      "restarting gracefully…")
                        t.record_attempt()
                        _emit_watchdog_event("RECOVERY_STARTED", reason=mtx_reason,
                                              target="mediamtx_health", restart_count=t.fails)

                        # Graceful restart: stop FFmpeg's publisher first
                        # (avoids an orphaned publisher racing the new
                        # MediaMTX instance), then MediaMTX, then FFmpeg —
                        # exactly Section 2's "Restart MediaMTX / Restart
                        # FFmpeg / Verify recovery" sequence.
                        _stop_ffmpeg_relay(wd.get("ffmpeg_pid"))
                        _kill_pid(_pgrep(MEDIAMTX_BIN))
                        _start_mediamtx()
                        _emit_watchdog_event("MEDIAMTX_RESTARTED", reason=mtx_reason,
                                              restart_count=t.fails)
                        new_ffmpeg_pid = _start_ffmpeg()
                        if new_ffmpeg_pid is not None:
                            _emit_watchdog_event("FFMPEG_STARTED", ffmpeg_pid=new_ffmpeg_pid)
                        wd["ffmpeg_pid"] = new_ffmpeg_pid
                        wd["mtx_unhealthy_count"] = 0
                        wd["mtx_health"] = {}

                        recovered = new_ffmpeg_pid is not None and wait_for_publisher()
                        elapsed = round(time.time() - restart_start, 2)
                        _record_recovery_result(
                            wd, recovered, elapsed,
                            reason=mtx_reason,
                            escalation_level=metrics.get("current_escalation_level"),
                            camera_state=wd.get("camera_state"),
                            mediamtx_status=ext_status,
                        )
                        if recovered:
                            _emit_watchdog_event("PUBLISHER_READY", path="main")
                            _emit_watchdog_event("STREAM_VERIFIED", path="main",
                                                  verification_latency_s=elapsed)
                            verified_status = _mediamtx_path_status_extended()
                            if (verified_status.get("reader_count") or 0) > 0:
                                _emit_watchdog_event("RECOVERY_VERIFIED",
                                                      reason="PUBLISHER_HEALTHY_ACTIVE_VIEWERS", path="main")
                            else:
                                _emit_watchdog_event("RECOVERY_VERIFIED",
                                                      reason="PUBLISHER_HEALTHY_NO_VIEWERS", path="main")
                            _emit_watchdog_event("RECOVERY_COMPLETED", reason=mtx_reason,
                                                  elapsed_recovery_s=elapsed, restart_count=t.fails)
                            _reset_escalation(wd, _emit_watchdog_event)
                        else:
                            _emit_watchdog_event("RECOVERY_FAILED", reason=mtx_reason,
                                                  elapsed_recovery_s=elapsed, restart_count=t.fails)
                            _escalate(wd, _emit_watchdog_event)
                    else:
                        _emit_watchdog_event("cooldown", target="mediamtx_health",
                                              reason=mtx_reason, fails=t.fails)

            # -- Workers + per-stream frame-activity staleness --
            for sname, s in state.get("streams", {}).items():
                for key, mv in s.get("models", {}).items():
                    pid = mv.get("pid")
                    if pid is None:
                        continue  # not activated, nothing to watch

                    label    = f"{sname}/{key}"
                    log_path = LOG_DIR / f"{sname}-{key}.log"
                    stale    = (log_path.exists() and
                                time.time() - log_path.stat().st_mtime > frame_timeout)

                    if not _is_running(pid):
                        t = tracker(label)
                        if t.allowed():
                            console.print(f"[yellow]?[/] [{datetime.now().isoformat()}] "
                                          f"Worker {label} down, restarting…")
                            t.record_attempt()
                            time.sleep(t.delay())
                            mv["pid"] = _start_worker(state, sname, key)
                            mv["started_at"] = datetime.now().isoformat()
                            notify_backend("worker_restarted", stream=sname, key=key,
                                           pid=mv["pid"], reason="dead")
                        else:
                            _emit_watchdog_event("cooldown", target=label, fails=t.fails)

                    elif stale:
                        t = tracker(label + "/stale")
                        if t.allowed():
                            console.print(f"[yellow]?[/] [{datetime.now().isoformat()}] "
                                          f"{label} stale (no activity {frame_timeout}s+), "
                                          "restarting pipeline…")
                            t.record_attempt()
                            _kill_pid(pid)
                            time.sleep(t.delay())
                            mv["pid"] = _start_worker(state, sname, key)
                            mv["started_at"] = datetime.now().isoformat()
                            notify_backend("worker_restarted", stream=sname, key=key,
                                           pid=mv["pid"], reason="stale")
                        else:
                            _emit_watchdog_event("cooldown", target=label + "/stale", fails=t.fails)

        shutdown["flag"] or time.sleep(interval)

    console.print("[dim]Watchdog stopped cleanly.[/]")


# --- recovery (new, additive) --------------------------------------------------

@cli.group()
def recovery():
    """Inspect the autonomous recovery subsystem's state and metrics."""
    pass


@recovery.command("history")
@click.option("--lines", default=20, show_default=True,
              help="Number of most recent recovery events to show.")
@click.option("--json", "as_json", is_flag=True, help="Print raw JSON instead of a table.")
def recovery_history(lines, as_json):
    """
    Show persisted recovery history (Section 2 addendum): survives
    container/watchdog restarts, unlike the in-memory-only metrics that
    reset when the watchdog process is recreated. Backed by
    RECOVERY_HISTORY_FILE, capped at RECOVERY_HISTORY_MAX events.
    """
    if not RECOVERY_HISTORY_FILE.exists():
        console.print("[dim]No recovery history recorded yet.[/]")
        return
    try:
        history = json.loads(RECOVERY_HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        console.print(f"[red]Failed to read recovery history: {exc}[/]")
        return

    recent = history[-lines:]
    if as_json:
        console.print(json.dumps(recent, indent=2))
        return

    t = Table(box=box.ROUNDED, header_style="bold magenta",
              title=f"Recovery History (last {len(recent)} of {len(history)})")
    for col in ("Time", "Result", "Reason", "Duration (s)", "Escalation", "Camera"):
        t.add_column(col, style="cyan" if col == "Time" else "white")
    for rec in reversed(recent):
        ts = datetime.fromtimestamp(rec.get("timestamp", 0)).isoformat(timespec="seconds")
        result = "[green]OK[/]" if rec.get("success") else "[red]FAILED[/]"
        t.add_row(
            ts, result, str(rec.get("reason")),
            f"{rec.get('duration_s', 0):.2f}",
            str(rec.get("escalation_level")), str(rec.get("camera_status")),
        )
    console.print(t)


@recovery.command("status")
def recovery_status():
    """Show detailed recovery metrics, escalation level, and MediaMTX
    publisher health as last observed by the watchdog daemon."""
    state = _load()
    wd = state.get(WATCHDOG_STATE_KEY, {})
    m = wd.get("metrics")
    if not m:
        console.print("[dim]No recovery activity recorded yet "
                       "(watchdog daemon may not have run a cycle).[/]")
        return

    t = Table(box=box.ROUNDED, header_style="bold magenta", title="Recovery Metrics")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="white")
    rows = [
        ("Total recoveries",        m.get("total_recoveries", 0)),
        ("Successful recoveries",   m.get("successful_recoveries", 0)),
        ("Failed recoveries",       m.get("failed_recoveries", 0)),
        ("Current stage",           m.get("current_recovery_stage", "idle")),
        ("Last recovery reason",    m.get("last_recovery_reason") or "—"),
        ("Last recovery duration",  f'{m.get("last_recovery_duration_s")}s'
                                      if m.get("last_recovery_duration_s") is not None else "—"),
        ("Mean recovery duration",  f'{m.get("mean_recovery_duration_s")}s'
                                      if m.get("mean_recovery_duration_s") is not None else "—"),
        ("Escalation level",        f'{m.get("current_escalation_level", 1)} / {ESCALATION_MAX_LEVEL}'),
        ("Publisher ready since",   m.get("publisher_ready_since") or "—"),
        ("FFmpeg PID",              wd.get("ffmpeg_pid") or "—"),
    ]
    for label, value in rows:
        t.add_row(label, str(value))
    console.print(t)

    ext = _mediamtx_path_status_extended()
    t2 = Table(box=box.ROUNDED, header_style="bold magenta", title="MediaMTX Path: main")
    t2.add_column("Field", style="cyan")
    t2.add_column("Value", style="white")
    for label, value in [
        ("Reachable",       ext["reachable"]),
        ("Publisher exists", ext["publisher_exists"]),
        ("Ready",           ext["ready"]),
        ("Reader count",    ext["reader_count"]),
        ("Publisher type",  ext["publisher_type"]),
        ("Publisher ID",    ext["publisher_id"]),
        ("Bytes received",  ext["bytes_received"]),
        ("Bytes sent",      ext["bytes_sent"]),
        ("Tracks",          ext["tracks"]),
    ]:
        t2.add_row(label, str(value))
    console.print(t2)


# --- cmd-server ---------------------------------------------------------------

CMD_SERVER_SCRIPT = Path("/app/udp_cmd_server.py")
CMD_SERVER_STATE_KEY = "cmd_server"


@cli.group("cmd-server")
def cmd_server():
    """UDP command server — receive model commands from another PC."""
    pass


@cmd_server.command("start")
@click.option("--port", "-p", default=9200, show_default=True,
              help="UDP port to listen on.")
@click.option("--host", "-H", default="0.0.0.0", show_default=True)
def cmd_server_start(port, host):
    """
    Start the UDP command server.

    \b
    Your other PC sends JSON commands like:
      {"cmd": "activate",   "stream": "main", "key": "detector"}
      {"cmd": "deactivate", "stream": "main", "key": "detector"}
      {"cmd": "deactivate_all", "stream": "main"}
      {"cmd": "status"}
      {"cmd": "list_models", "stream": "main"}

    Responses are sent back to the sender as JSON.
    """
    state = _load()
    srv   = state.get(CMD_SERVER_STATE_KEY, {})
    if _is_running(srv.get("pid")):
        console.print(f"[yellow]?[/]  Command server already running (PID {srv['pid']}).")
        sys.exit(1)

    log_path = LOG_DIR / "cmd-server.log"
    log_file = _open_rotating_log(log_path)
    log_file.write(
        f"\n{'-'*60}\n[{datetime.now().isoformat()}] Starting\n{'-'*60}\n"
    )
    log_file.flush()

    proc = subprocess.Popen(
        [sys.executable, str(CMD_SERVER_SCRIPT),
         "--host", host, "--port", str(port)],
        stdout=log_file, stderr=log_file,
        start_new_session=True,
    )
    time.sleep(0.8)
    if proc.poll() is not None:
        console.print(f"[bold red]?[/] Command server exited immediately. "
                      "Check: [cyan]stream-mgr cmd-server logs[/]")
        sys.exit(1)

    state[CMD_SERVER_STATE_KEY] = {
        "pid":        proc.pid,
        "host":       host,
        "port":       port,
        "started_at": datetime.now().isoformat(),
    }
    _save(state)

    console.print(f"[bold green]?[/] Command server started (PID [dim]{proc.pid}[/])")
    console.print(f"  Listening : [dim]{host}:{port}/udp[/]")
    console.print(f"  Logs      : [dim]{log_path}[/]")
    console.print(f"\n  From your other PC:")
    console.print(f'    [dim]python3 send_cmd.py --host <JETSON_IP> --port {port} '
                  f'activate main detector[/]')


@cmd_server.command("stop")
def cmd_server_stop():
    """Stop the UDP command server."""
    state = _load()
    srv   = state.get(CMD_SERVER_STATE_KEY, {})
    pid   = srv.get("pid")
    if not _is_running(pid):
        console.print("[dim]Command server is not running.[/]")
        state[CMD_SERVER_STATE_KEY] = {}
        _save(state)
        return
    with console.status("Stopping command server…"):
        _kill_pid(pid)
    state[CMD_SERVER_STATE_KEY] = {}
    _save(state)
    console.print("[bold green]?[/] Command server stopped.")


@cmd_server.command("status")
def cmd_server_status():
    """Show command server status."""
    state = _load()
    srv   = state.get(CMD_SERVER_STATE_KEY, {})
    pid   = srv.get("pid")
    if not srv or not _is_running(pid):
        console.print("[dim]Command server is not running.[/]")
        return
    started = srv.get("started_at", "")[:19].replace("T", " ")
    console.print(f"[bold green]? RUNNING[/]  PID [dim]{pid}[/]  "
                  f"[dim]{srv['host']}:{srv['port']}/udp[/]  started {started}")


@cmd_server.command("logs")
@click.option("--lines",  "-n", default=50, show_default=True)
@click.option("--follow", "-f", is_flag=True)
def cmd_server_logs(lines, follow):
    """Tail the command server log."""
    log_path = LOG_DIR / "cmd-server.log"
    if not log_path.exists():
        console.print("[dim]No log yet. Start the server first.[/]")
        return
    cmd = ["tail", f"-n{lines}"]
    if follow:
        cmd.append("-f")
    cmd.append(str(log_path))
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    # CRITICAL: this must stay the LAST statement in the file. Every
    # @cli.* command/group decorator above needs to have executed and
    # registered itself on `cli` before cli() is invoked — previously this
    # guard sat in the middle of the file (before the cmd-server group),
    # which meant `stream-mgr cmd-server ...` was silently unregistered
    # whenever the script was run directly.
    cli()