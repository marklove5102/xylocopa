// Suspense fallback for TaskDetailPage. Header + meta chips only —
// body area left blank so users don't see ghost-lines flash in.

export default function TaskDetailSkeleton() {
  return (
    <div className="flex flex-col h-full bg-page">
      {/* Header bar */}
      <div className="shrink-0 bg-surface border-b border-divider px-4 py-3 flex items-center gap-3">
        <div className="w-6 h-6 rounded bg-input animate-pulse" />
        <div className="h-5 w-48 rounded bg-input animate-pulse" />
      </div>
      {/* Meta chips row */}
      <div className="shrink-0 px-4 py-3 flex items-center gap-2">
        <div className="h-6 w-16 rounded-full bg-input animate-pulse" />
        <div className="h-6 w-20 rounded-full bg-input animate-pulse" />
        <div className="h-6 w-14 rounded-full bg-input animate-pulse" />
      </div>
      {/* Empty body — no placeholder lines */}
      <div className="flex-1" />
    </div>
  );
}
