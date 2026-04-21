"""Push notification sender — non-blocking, fire-and-forget.

Backend: Web Push (VAPID) — browser-based, works when PWA is open.
"""

import atexit
import json
import logging
import secrets
from concurrent.futures import ThreadPoolExecutor

import requests as _requests

from config import (
    VAPID_PRIVATE_KEY,
    VAPID_PUBLIC_KEY,
    VAPID_SUBJECT,
)

logger = logging.getLogger("orchestrator.push")

# Thread pool for webpush fanout. Each push is an HTTPS round-trip
# (TLS + POST to Apple/Google/Mozilla) ~200-250ms.  Callers submit
# fire-and-forget tasks; workers handle their own 410 cleanup so the
# event loop never waits on network I/O.
_push_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="webpush")

# Drain in-flight pushes on process exit.  Without this, SIGTERM during
# a restart could truncate pending TLS POSTs.
atexit.register(lambda: _push_pool.shutdown(wait=True))


def is_notification_enabled(category: str) -> bool:
    """Check if notifications are globally enabled for a category ('agents' or 'tasks')."""
    from database import SessionLocal
    from models import SystemConfig
    db = SessionLocal()
    try:
        row = db.get(SystemConfig, f"notifications_{category}_enabled")
        return row.value != "0" if row else True
    finally:
        db.close()


def send_push_notification(title: str, body: str, url: str = "/") -> None:
    """Send a push notification via Web Push."""
    _send_webpush(title, body, url)


def _send_one(sub_data: dict, title: str, body: str, url: str, nid: str) -> None:
    """Worker: send one webpush and self-clean if endpoint is gone.

    Runs in a _push_pool thread.  sub_data is a plain dict (materialized
    from the ORM) so there's no risk of DetachedInstanceError.
    """
    from urllib.parse import urlparse
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return

    sub_id = sub_data["id"]
    endpoint = sub_data["endpoint"]
    parsed = urlparse(endpoint)
    aud = f"{parsed.scheme}://{parsed.netloc}"
    payload = json.dumps({"title": title, "body": body, "url": url, "nid": nid})
    subscription_info = {
        "endpoint": endpoint,
        "keys": {
            "p256dh": sub_data["p256dh_key"],
            "auth": sub_data["auth_key"],
        },
    }
    vapid_claims = {"sub": VAPID_SUBJECT, "aud": aud}

    expired = False
    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=vapid_claims,
        )
        logger.info(
            "push send: nid=%s sub=%s host=%s ok",
            nid, sub_id, parsed.netloc,
        )
    except WebPushException as e:
        if hasattr(e, "response") and e.response is not None \
                and e.response.status_code == 410:
            expired = True
        else:
            logger.warning("Push failed for %s: %s", endpoint[:60], e)
    except _requests.exceptions.RequestException:
        logger.debug("Push network error for %s", endpoint[:60], exc_info=True)
    except Exception:
        logger.warning("Push error for %s", endpoint[:60], exc_info=True)

    if expired:
        from database import SessionLocal
        from models import PushSubscription
        _db = SessionLocal()
        try:
            _db.query(PushSubscription).filter(
                PushSubscription.id == sub_id
            ).delete(synchronize_session=False)
            _db.commit()
            logger.info("Removed expired push subscription id=%s", sub_id)
        except Exception:
            logger.warning(
                "Failed to delete expired sub id=%s", sub_id, exc_info=True,
            )
        finally:
            _db.close()


def _send_webpush(title: str, body: str, url: str = "/") -> None:
    """Fire-and-forget fanout to all subscribed browsers.

    Reads the subscription list (a short indexed query), materializes
    each row into a plain dict, and submits one fire-and-forget task
    per subscription.  Returns before any TLS POST completes, so the
    caller (typically the sync-engine coroutine) is not blocked by
    push RTTs and subsequent WebSocket emits can proceed immediately.
    """
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return

    try:
        import pywebpush  # noqa: F401 — presence check only
    except ImportError:
        logger.debug("pywebpush not installed — skipping web push")
        return

    from database import SessionLocal
    from models import PushSubscription

    db = SessionLocal()
    try:
        subs = db.query(PushSubscription).all()
        if not subs:
            return
        sub_data_list = [
            {
                "id": s.id,
                "endpoint": s.endpoint,
                "p256dh_key": s.p256dh_key,
                "auth_key": s.auth_key,
            }
            for s in subs
        ]
    finally:
        db.close()

    # Diagnostic correlation id — SW echoes this back via /api/push/ack
    nid = secrets.token_hex(4)
    logger.info(
        "push send: nid=%s subs=%d title=%r", nid, len(sub_data_list), title[:60],
    )
    for sd in sub_data_list:
        try:
            _push_pool.submit(_send_one, sd, title, body, url, nid)
        except RuntimeError:
            # Pool already shut down (process exiting) — drop silently.
            logger.debug("push pool shut down, dropping push to sub=%s", sd["id"])
