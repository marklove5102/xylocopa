#!/usr/bin/env python3
"""Send a reset push to a Service Worker so it clears caches and unregisters.

Use when a device's PWA is stuck on a stale Service Worker (e.g. iPhone
PWA showing a perpetual loading screen after a deploy).

Usage:
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
import secrets
import sys
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


def _list(db):
    subs = db.query(PushSubscription).order_by(
        PushSubscription.last_ack_at.desc().nullslast()
    ).all()
    if not subs:
        print("(no subscriptions)")
        return
    for s in subs:
        host = urlparse(s.endpoint).netloc
        ack = s.last_ack_at.strftime("%Y-%m-%d %H:%M") if s.last_ack_at else "never"
        print(f"  {s.id}  {host:25s}  last_ack={ack}  ep_tail=...{s.endpoint[-12:]}")


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


def main():
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    if not VAPID_PRIVATE_KEY:
        print("VAPID_PRIVATE_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    arg = sys.argv[1]
    db = SessionLocal()
    try:
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
