// In-flight prefetch cache for /display/sent + /display/pre-sent.
//
// Triggered by hover on AgentRow; consumed by AgentChatPage's loadData.
// The hover→click latency (typically 100-300ms motor delay) overlaps with
// the network round-trip, so by the time the chat page mounts the data is
// either already in JS or about to be. This eliminates a chunk of the
// 0-300ms "dead zone" where we'd otherwise wait for fetches to fire.
//
// Cache lifetime is short: ~2s grace window covers (a) the click→mount
// transition and (b) StrictMode's dev-only double-mount, after which the
// entry is evicted so subsequent loads always see fresh data. WS updates
// reconcile any short-lived staleness within this window.

import { fetchDisplaySent, fetchDisplayPreSent } from "./api";

const inflight = new Map(); // id -> Promise<[sentData, preSentData]>

const TTL_MS = 2000;

export function prefetchChatData(id) {
  if (!id || inflight.has(id)) return;
  const promise = Promise.all([
    fetchDisplaySent(id, { tailBytes: 50000 }),
    fetchDisplayPreSent(id),
  ]).catch(() => null); // swallow — chat page will retry on its own
  inflight.set(id, promise);
  setTimeout(() => {
    if (inflight.get(id) === promise) inflight.delete(id);
  }, TTL_MS);
}

// Peek-without-delete: lets StrictMode's dev double-mount both consume
// the same promise. Eviction is TTL-driven, so re-opening the same chat
// after the window always gets a fresh fetch.
export function consumePrefetch(id) {
  return inflight.get(id) || null;
}
