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
    // Fire all four in parallel; browser dedups concurrent fetches.
    // Failures here are silent — they'll happen again on real navigation
    // and the lazyPage retry/reload safety net there will handle it.
    import("../pages/AgentChatPage").catch(() => {});
    import("../pages/ProjectDetailPage").catch(() => {});
    import("../pages/TaskDetailPage").catch(() => {});
    import("../pages/NewTaskPage").catch(() => {});
  };

  if (typeof window === "undefined") return;
  if ("requestIdleCallback" in window) {
    window.requestIdleCallback(fire, { timeout: 3000 });
  } else {
    setTimeout(fire, 1500);
  }
}
