// Suspense fallback for TaskDetailPage. Title bar + meta chips + body.

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
      {/* Body content */}
      <div className="flex-1 overflow-hidden px-4 pt-2 pb-24 space-y-3">
        <div className="h-4 rounded bg-input animate-pulse" />
        <div className="h-4 w-5/6 rounded bg-input animate-pulse" />
        <div className="h-4 w-2/3 rounded bg-input animate-pulse" />
        <div className="h-32 rounded-xl bg-surface animate-pulse" />
        <div className="h-4 w-3/4 rounded bg-input animate-pulse" />
        <div className="h-4 w-1/2 rounded bg-input animate-pulse" />
      </div>
    </div>
  );
}
