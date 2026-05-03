// Pure-CSS placeholder for AgentChatPage's Suspense fallback.
// Header + composer placeholders only — middle scroll area is left
// blank (bg-page) so users don't see ghost-bubbles flash in. Layout
// remains stable because the middle is a flex-1 spacer.

export default function ChatSkeleton() {
  return (
    <div className="flex flex-col h-full bg-page">
      {/* Header bar — height matches AgentChatPage header */}
      <div className="shrink-0 bg-surface border-b border-divider px-4 py-3 flex items-center gap-3">
        <div className="w-6 h-6 rounded-full bg-input animate-pulse" />
        <div className="h-5 w-40 rounded bg-input animate-pulse" />
        <div className="ml-auto h-5 w-12 rounded-full bg-input animate-pulse" />
      </div>

      {/* Empty middle — no placeholder bubbles */}
      <div className="flex-1" />

      {/* Composer placeholder */}
      <div className="shrink-0 px-4 pb-4">
        <div className="rounded-2xl bg-surface h-14 animate-pulse" />
      </div>
    </div>
  );
}
