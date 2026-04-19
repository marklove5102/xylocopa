"""Push notification sender — best-effort, never blocks dispatch.

Backend: Web Push (VAPID) — browser-based, works when PWA is open.
"""

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

# Shared pool for parallel webpush sends. Each push is an HTTPS round-trip
# (TLS + POST to Apple/Google/Mozilla) ~200-250ms; doing them serially used
# to stack up to 11*250ms ≈ 2.5s on the caller's hot path.
_push_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="webpush")


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


def _send_webpush(title: str, body: str, url: str = "/") -> None:
    """Send a Web Push notification to all subscribed browsers."""
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.debug("pywebpush not installed — skipping web push")
        return

    from urllib.parse import urlparse

    from database import SessionLocal
    from models import PushSubscription

    db = SessionLocal()
    try:
        subs = db.query(PushSubscription).all()
        if not subs:
            return

        # Diagnostic correlation id — SW echoes this back via /api/push/ack
        nid = secrets.token_hex(4)
        payload = json.dumps({"title": title, "body": body, "url": url, "nid": nid})
        logger.info(
            "push send: nid=%s subs=%d title=%r", nid, len(subs), title[:60],
        )
        def _send_one(sub):
            subscription_info = {
                "endpoint": sub.endpoint,
                "keys": {
                    "p256dh": sub.p256dh_key,
                    "auth": sub.auth_key,
                },
            }
            parsed = urlparse(sub.endpoint)
            aud = f"{parsed.scheme}://{parsed.netloc}"
            vapid_claims = {"sub": VAPID_SUBJECT, "aud": aud}
            try:
                webpush(
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims=vapid_claims,
                )
                logger.info(
                    "push send: nid=%s sub=%s host=%s ok",
                    nid, sub.id, parsed.netloc,
                )
                return None
            except WebPushException as e:
                if hasattr(e, "response") and e.response is not None:
                    if e.response.status_code == 410:
                        return sub.id  # expired — caller deletes
                logger.warning("Push failed for %s: %s", sub.endpoint[:60], e)
                return None
            except Exception:
                logger.warning("Push error for %s", sub.endpoint[:60], exc_info=True)
                return None

        # Fan out in parallel — serial was ~sum(rtts); parallel is ~max(rtt).
        expired_ids = [r for r in _push_pool.map(_send_one, subs) if r]

        if expired_ids:
            db.query(PushSubscription).filter(
                PushSubscription.id.in_(expired_ids)
            ).delete(synchronize_session=False)
            db.commit()
            logger.info("Removed %d expired push subscriptions", len(expired_ids))
    except _requests.exceptions.RequestException:
        logger.debug("Push notification batch failed (network)", exc_info=True)
    except Exception:
        logger.error("Push notification batch failed", exc_info=True)
    finally:
        db.close()
