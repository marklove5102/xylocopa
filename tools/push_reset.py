#!/usr/bin/env python3
"""Send a reset push to a Service Worker so it clears caches and unregisters.

Use when a device's PWA is stuck on a stale Service Worker (e.g. iPhone
PWA showing a perpetual loading screen after a deploy).

Usage:
    python tools/push_reset.py                  # interactive picker (default)
    python tools/push_reset.py list             # list all subscriptions
    python tools/push_reset.py <sub_id_or_tail> # reset one device
    python tools/push_reset.py all              # reset every subscription

After the push lands, the device's SW will:
  1. Show a "Reset done" notification
  2. Delete all caches
  3. Unregister itself

Then fully close and reopen the PWA on the device for a clean fetch.
"""
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
# Pin paths to this project regardless of any stale shell env vars
# (e.g. inherited DB_PATH pointing at a sibling install). Mirrors what
# ecosystem.config.cjs does for the backend process.
os.environ["DB_PATH"] = str(ROOT / "data" / "orchestrator.db")
sys.path.insert(0, str(ROOT / "orchestrator"))

from config import VAPID_PRIVATE_KEY, VAPID_SUBJECT  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import PushSubscription  # noqa: E402

LOG_PATH = ROOT / "logs" / "orchestrator.log"
ACK_RE = re.compile(r"push ack: nid=\S+ sub=(\w+) .* ua=(.+)$")


def _friendly_age(dt):
    if not dt:
        return "never"
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now(timezone.utc).replace(tzinfo=None)
    secs = int((now - dt).total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _device_label(ua: str) -> str:
    if not ua:
        return "unknown"
    if "iPhone" in ua:
        m = re.search(r"iPhone OS (\d+_\d+)", ua)
        return f"iPhone iOS {m.group(1).replace('_', '.')}" if m else "iPhone"
    if "iPad" in ua:
        return "iPad"
    if "Macintosh" in ua or "Mac OS X" in ua:
        if "Safari" in ua and "Chrome" not in ua:
            return "macOS Safari"
        if "Chrome" in ua:
            return "macOS Chrome"
        return "macOS"
    if "Android" in ua:
        return "Android"
    if "Windows" in ua:
        return "Windows"
    if "Linux" in ua:
        return "Linux"
    return ua[:30]


def _build_ua_map():
    """Scan recent ack lines to map sub_id -> last seen UA."""
    if not LOG_PATH.exists():
        return {}
    ua_map = {}
    try:
        with LOG_PATH.open("r", errors="ignore") as f:
            for line in f:
                m = ACK_RE.search(line)
                if m:
                    ua_map[m.group(1)] = m.group(2).strip()
    except OSError:
        return {}
    return ua_map


def _format_row(idx, sub, ua_map):
    host = urlparse(sub.endpoint).netloc
    age = _friendly_age(sub.last_ack_at)
    # Match by full id and by tail (subs can be referenced both ways).
    ua = ua_map.get(sub.id) or ""
    if not ua:
        for k, v in ua_map.items():
            if k.endswith(sub.id) or sub.id.endswith(k):
                ua = v
                break
    label = _device_label(ua)
    prefix = f"  [{idx}] " if idx is not None else "  "
    return f"{prefix}{sub.id}  {label:18s}  {host:25s}  ack={age}"


def _list(db, ua_map=None):
    subs = db.query(PushSubscription).order_by(
        PushSubscription.last_ack_at.desc().nullslast()
    ).all()
    if not subs:
        print("(no subscriptions)")
        return []
    if ua_map is None:
        ua_map = _build_ua_map()
    for s in subs:
        print(_format_row(None, s, ua_map))
    return subs


def _resolve(db, key):
    subs = db.query(PushSubscription).all()
    matches = [
        s for s in subs
        if s.id == key or s.id.endswith(key) or s.endpoint.endswith(key)
    ]
    if not matches:
        print(f"No subscription matches {key!r}", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"Ambiguous: {key!r} matches {len(matches)}:", file=sys.stderr)
        for s in matches:
            print(f"  {s.id}  ep_tail=...{s.endpoint[-16:]}", file=sys.stderr)
        sys.exit(1)
    return matches[0]


def _send_reset(sub):
    from pywebpush import WebPushException, webpush
    nid = secrets.token_hex(4)
    # title/body included as a fallback: a SW running the older
    # push-handler.js (no reset branch) will at least show a notification
    # so the user can tell the push landed.
    payload = json.dumps({
        "type": "reset",
        "title": "Xylocopa",
        "body": "Reset triggered — please re-open the app",
        "url": "/",
        "nid": nid,
    })
    parsed = urlparse(sub.endpoint)
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key},
            },
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={
                "sub": VAPID_SUBJECT,
                "aud": f"{parsed.scheme}://{parsed.netloc}",
            },
        )
        print(f"  OK    sub={sub.id} host={parsed.netloc} nid={nid}")
        return True
    except WebPushException as e:
        code = e.response.status_code if e.response is not None else "?"
        print(f"  FAIL  sub={sub.id} HTTP {code}: {e}")
        return False


def _interactive(db):
    subs = db.query(PushSubscription).order_by(
        PushSubscription.last_ack_at.desc().nullslast()
    ).all()
    if not subs:
        print("(no subscriptions)")
        return
    ua_map = _build_ua_map()
    print(f"Found {len(subs)} subscription(s):")
    for i, s in enumerate(subs, 1):
        print(_format_row(i, s, ua_map))
    print()
    try:
        choice = input("Pick [1-{n}], 'a' for all, 'q' to quit: ".format(n=len(subs))).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if not choice or choice == "q":
        return
    if choice == "a":
        try:
            confirm = input(f"Reset all {len(subs)} subscription(s)? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if confirm != "y":
            print("Aborted.")
            return
        print(f"Sending reset to {len(subs)} subscription(s)...")
        for s in subs:
            _send_reset(s)
        return
    if not choice.isdigit():
        print(f"Invalid choice: {choice!r}", file=sys.stderr)
        sys.exit(1)
    idx = int(choice)
    if not 1 <= idx <= len(subs):
        print(f"Out of range: {idx}", file=sys.stderr)
        sys.exit(1)
    _send_reset(subs[idx - 1])


def main():
    if not VAPID_PRIVATE_KEY:
        print("VAPID_PRIVATE_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        if len(sys.argv) == 1:
            _interactive(db)
            return
        if len(sys.argv) != 2:
            print(__doc__, file=sys.stderr)
            sys.exit(2)
        arg = sys.argv[1]
        if arg == "list":
            _list(db)
        elif arg == "all":
            subs = db.query(PushSubscription).all()
            print(f"Sending reset to {len(subs)} subscription(s)...")
            for s in subs:
                _send_reset(s)
        else:
            _send_reset(_resolve(db, arg))
    finally:
        db.close()


if __name__ == "__main__":
    main()
