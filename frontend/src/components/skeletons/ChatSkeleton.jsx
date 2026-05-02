// Pure-CSS placeholder for AgentChatPage's Suspense fallback.
// Mirrors the broad shape (header bar, message stream, composer) so the
// transition from skeleton → real chat is layout-stable. No API calls,
// no markdown, no lazy imports — paints in the same frame as the click.

function Bubble({ side, width }) {
  const align = side === "right" ? "ml-auto" : "";
  return (
    <div className={`${align} mb-3`} style={{ maxWidth: "85%", width }}>
      <div className="rounded-2xl bg-surface animate-pulse"
        style={{ height: 56 }} />
    </div>
  );
}

export default function ChatSkeleton() {
  return (
    <div className="flex flex-col h-full bg-page">
      {/* Header bar — height matches AgentChatPage header */}
      <div className="shrink-0 bg-surface border-b border-divider px-4 py-3 flex items-center gap-3">
        <div className="w-6 h-6 rounded-full bg-input animate-pulse" />
        <div className="h-5 w-40 rounded bg-input animate-pulse" />
        <div className="ml-auto h-5 w-12 rounded-full bg-input animate-pulse" />
      </div>

      {/* Scrollable message area with placeholder bubbles */}
      <div className="flex-1 overflow-hidden px-4 pt-4 pb-4">
        <Bubble side="left" width="70%" />
        <Bubble side="right" width="55%" />
        <Bubble side="left" width="80%" />
        <Bubble side="right" width="40%" />
        <Bubble side="left" width="65%" />
      </div>

      {/* Composer placeholder */}
      <div className="shrink-0 px-4 pb-4">
        <div className="rounded-2xl bg-surface h-14 animate-pulse" />
      </div>
    </div>
  );
}
