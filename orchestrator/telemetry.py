"""Xylocopa telemetry — privacy-first, anonymous, opt-out.

Sends ONE event type only: `daily_heartbeat`, gated to >20h interval.
This is the minimum signal needed to know whether anyone is using the project.

Payload (anonymous — exactly these 5 fields, nothing else):
    { "event", "install_id" (UUID v4), "version", "platform" (sys.platform),
      "timestamp" (ISO8601) }

Disable: env XYLOCOPA_TELEMETRY=0 OR ~/.xylocopa/config.yaml with telemetry: false.

All calls are fire-and-forget with a 2s socket timeout in a daemon thread.
Errors are swallowed — telemetry must never crash or block the app.

Endpoint: defaults to the public Worker URL below. Override via
XYLOCOPA_TELEMETRY_ENDPOINT. Empty string → skip sends (kill switch).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("xylocopa.telemetry")

# ---- Paths ----

TELEMETRY_DIR = Path(os.path.expanduser("~/.xylocopa"))
INSTALL_ID_FILE = TELEMETRY_DIR / "install_id"
LAST_HEARTBEAT_FILE = TELEMETRY_DIR / "last_heartbeat"
CONFIG_FILE = TELEMETRY_DIR / "config.yaml"

# ---- Constants ----

HEARTBEAT_MIN_INTERVAL_SECONDS = 20 * 3600
REQUEST_TIMEOUT_SECONDS = 2.0
ENV_ENABLED = "XYLOCOPA_TELEMETRY"
ENV_ENDPOINT = "XYLOCOPA_TELEMETRY_ENDPOINT"
DEFAULT_ENDPOINT = "https://xylocopa-telemetry.jyao073.workers.dev/v1/event"

FIRST_RUN_NOTICE = """\
----------------------------------------------------------------
Xylocopa sends one anonymous heartbeat per day to help me see if
anyone is using the project. Payload: random install_id, version,
OS family, timestamp. No IPs, no prompts, no code, no file paths.
Disable: Monitor page toggle, or XYLOCOPA_TELEMETRY=0 env var,
or telemetry=false in ~/.xylocopa/config.yaml.
See: https://github.com/jyao97/xylocopa#telemetry
----------------------------------------------------------------
"""


# ---- Version ----

def _load_version() -> str:
    try:
        pkg = Path(__file__).resolve().parent.parent / "package.json"
        with open(pkg) as f:
            return json.load(f).get("version", "unknown")
    except Exception:
        return "unknown"


_VERSION = _load_version()


# ---- Enablement ----

def _env_disable() -> bool:
    """True if env var explicitly disables. None/unset → False."""
    val = os.environ.get(ENV_ENABLED, "").strip().lower()
    return val in ("0", "false", "no", "off")


def _config_disable() -> bool:
    """True if ~/.xylocopa/config.yaml has telemetry: false."""
    try:
        if CONFIG_FILE.exists():
            import yaml
            with open(CONFIG_FILE) as f:
                cfg = yaml.safe_load(f) or {}
            if cfg.get("telemetry") is False:
                return True
    except Exception:
        pass
    return False


def _is_enabled() -> bool:
    return not (_env_disable() or _config_disable())


def _endpoint_url() -> str:
    val = os.environ.get(ENV_ENDPOINT)
    if val is None:
        return DEFAULT_ENDPOINT
    return val.strip()


# ---- Filesystem helpers ----

def _ensure_dirs() -> None:
    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


def _read_install_id() -> Optional[str]:
    try:
        val = INSTALL_ID_FILE.read_text().strip()
        return val or None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _ensure_install_id() -> Optional[str]:
    """Get or create the local install_id. Prints first-run notice on creation.
    Returns None if telemetry is disabled (no file is created in that case)."""
    if not _is_enabled():
        return None
    existing = _read_install_id()
    if existing:
        return existing
    new_id = str(uuid.uuid4())
    try:
        _ensure_dirs()
        INSTALL_ID_FILE.write_text(new_id)
    except Exception:
        logger.debug("install_id write failed", exc_info=True)
        return None
    try:
        print(FIRST_RUN_NOTICE, flush=True)
    except Exception:
        pass
    logger.info("Telemetry: first-run notice printed; install_id created")
    return new_id


# ---- Send ----

def _send(event: str, install_id: str) -> None:
    """Fire-and-forget POST of structured JSON to the Worker relay. Never raises."""
    url = _endpoint_url()
    if not url:
        return

    payload = {
        "event": event,
        "install_id": install_id,
        "version": _VERSION,
        "platform": sys.platform,
        "timestamp": _now_iso(),
    }

    def _worker() -> None:
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": f"Xylocopa/{_VERSION}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS):
                pass
        except Exception:
            pass

    try:
        threading.Thread(target=_worker, daemon=True, name="xylocopa-telemetry").start()
    except Exception:
        pass


# ---- Public API ----

def record_heartbeat() -> None:
    """Send daily_heartbeat if last was >20h ago. Creates install_id on first call."""
    if not _is_enabled():
        return
    try:
        install_id = _ensure_install_id()
        if not install_id:
            return

        now = _now_ts()
        try:
            last = float(LAST_HEARTBEAT_FILE.read_text().strip())
        except (FileNotFoundError, ValueError):
            last = 0.0

        if now - last < HEARTBEAT_MIN_INTERVAL_SECONDS:
            return

        _ensure_dirs()
        LAST_HEARTBEAT_FILE.write_text(str(now))
        _send("daily_heartbeat", install_id)
    except Exception:
        logger.debug("record_heartbeat failed", exc_info=True)


def get_status() -> dict:
    """Return current telemetry config, for the Monitor UI toggle."""
    env_locked = _env_disable()
    config_disabled = _config_disable()
    return {
        "enabled": not (env_locked or config_disabled),
        "env_locked": env_locked,
        "install_id": _read_install_id(),
        "version": _VERSION,
    }


def set_enabled(enabled: bool) -> dict:
    """Toggle via config.yaml. Returns the new status."""
    try:
        import yaml
        _ensure_dirs()
        cfg: dict = {}
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                cfg = yaml.safe_load(f) or {}
        cfg["telemetry"] = bool(enabled)
        with open(CONFIG_FILE, "w") as f:
            yaml.safe_dump(cfg, f)
    except Exception:
        logger.exception("set_enabled failed")
    return get_status()
