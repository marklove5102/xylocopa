// Idle-time preload for heavy dynamic-route chunks.
//
// AgentChatPage (146 KB, gzip 38 KB) and ProjectDetailPage (67 KB)
// are code-split via React.lazy, so the first navigation into them
// shows the Suspense fallback ("Loading...") for 200–500ms while the
// chunk is fetched and parsed. Once cached, subsequent navigations are
// instant.
//
// Strategy: as soon as the main app is idle (after first paint of the
// list pages), fire-and-forget the dynamic imports. Browsers cache
// module results, so when the user actually navigates the lazy()
// resolver finds the chunk already-resolved and skips Suspense.
//
// Network cost: ~250 KB extra on cold load, deferred to idle. Trivial
// on broadband; on mobile the user-perceived navigation feels instant
// rather than spending 400ms on each first chat/project entry.
//
// Idempotent: import() is cached at the module level. Calling
// prefetchHeavyChunks() twice is a no-op the second time.

let _scheduled = false;

export function prefetchHeavyChunks() {
  if (_scheduled) return;
  _scheduled = true;

  const fire = () => {
    // Use the lazy components' own preload() so React.lazy receives
    // the same already-settled Promise it would have created internally —
    // a parallel import() would cache the chunk in HTTP but lazy() still
    // creates a fresh Promise on first render and suspends for one frame.
    // Window-bridge avoids a circular import between App.jsx and this file.
    const reg = (typeof window !== "undefined" && window.__xylocopa_preloaders) || null;
    if (!reg) return;
    Object.values(reg).forEach((preload) => {
      try { preload()?.catch?.(() => {}); } catch { /* ignore */ }
    });
  };

  if (typeof window === "undefined") return;
  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(fire, { timeout: 3000 });
  } else {
    setTimeout(fire, 1500);
  }
}
