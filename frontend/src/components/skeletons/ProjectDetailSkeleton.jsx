// Suspense fallback for ProjectDetailPage. Header (emoji + name +
// stats ring) + filter tabs + agent list placeholders.

function AgentRowSkel() {
  return (
    <div className="rounded-2xl bg-surface px-5 py-[18px] flex items-start gap-3 animate-pulse">
      <div className="shrink-0 w-2.5 h-2.5 rounded-full bg-input self-center" />
      <div className="flex-1 space-y-2">
        <div className="h-4 w-1/2 rounded bg-input" />
        <div className="h-3 w-3/4 rounded bg-input" />
      </div>
      <div className="w-4 h-4 rounded bg-input self-center" />
    </div>
  );
}

export default function ProjectDetailSkeleton() {
  return (
    <div className="flex flex-col h-full bg-page">
      {/* Header */}
      <div className="shrink-0 bg-page border-b border-divider px-4 py-3 flex items-center gap-3">
        <div className="w-7 h-7 rounded bg-input animate-pulse" />
        <div className="h-5 w-32 rounded bg-input animate-pulse" />
        <div className="ml-auto h-7 w-7 rounded-full bg-input animate-pulse" />
      </div>
      {/* Filter tabs */}
      <div className="shrink-0 px-4 py-2 flex items-center gap-2">
        {[60, 70, 80, 70, 70].map((w, i) => (
          <div key={i} className="h-9 rounded-full bg-input animate-pulse" style={{ width: w }} />
        ))}
      </div>
      {/* Body */}
      <div className="flex-1 overflow-hidden px-4 pt-3 pb-24 space-y-3">
        <AgentRowSkel />
        <AgentRowSkel />
        <AgentRowSkel />
        <AgentRowSkel />
      </div>
    </div>
  );
}
