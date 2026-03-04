import { useState } from "react";
import QueueCard from "../../components/cards/QueueCard";
import ActiveCard from "../../components/cards/ActiveCard";
import { updateTaskV2, cancelTask } from "../../lib/api";

export default function ExecutingView({ tasks, loading, onRefresh }) {
  const [error, setError] = useState(null);
  const [loadingIds, setLoadingIds] = useState(new Set());

  const active = tasks
    .filter((t) => t.status === "EXECUTING")
    .sort((a, b) => new Date(a.started_at || a.created_at) - new Date(b.started_at || b.created_at));

  const queued = tasks
    .filter((t) => t.status === "PENDING")
    .sort((a, b) => {
      if (b.priority !== a.priority) return b.priority - a.priority;
      return new Date(a.created_at) - new Date(b.created_at);
    });

  const handleCancel = async (task) => {
    setError(null);
    setLoadingIds((s) => new Set(s).add(task.id));
    try {
      await cancelTask(task.id);
      onRefresh?.();
    } catch (err) {
      setError(err.message || "Cancel failed");
    } finally {
      setLoadingIds((s) => { const n = new Set(s); n.delete(task.id); return n; });
    }
  };

  const handleDispatchNow = async (task) => {
    setError(null);
    setLoadingIds((s) => new Set(s).add(task.id));
    try {
      await updateTaskV2(task.id, { priority: 1 });
      onRefresh?.();
    } catch (err) {
      setError(err.message || "Priority update failed");
    } finally {
      setLoadingIds((s) => { const n = new Set(s); n.delete(task.id); return n; });
    }
  };

  if (!loading && active.length === 0 && queued.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-faint">
        <svg className="w-10 h-10 mb-2" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
        </svg>
        <p className="text-sm font-medium">No executing tasks</p>
        <p className="text-xs mt-1">Queued and running tasks appear here</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && (
        <div className="bg-red-950/40 border border-red-800 rounded-xl px-3 py-2 flex items-center justify-between">
          <p className="text-red-400 text-sm">{error}</p>
          <button type="button" onClick={() => setError(null)} className="text-red-400/60 hover:text-red-400 text-xs ml-2">dismiss</button>
        </div>
      )}

      {active.length > 0 && (
        <>
          <div className="flex items-center gap-2 px-1 pt-1">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-500 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-cyan-500" />
            </span>
            <span className="text-xs font-medium text-cyan-400">Running · {active.length}</span>
          </div>
          {active.map((task) => (
            <ActiveCard key={task.id} task={task} onCancel={handleCancel} />
          ))}
        </>
      )}

      {queued.length > 0 && (
        <>
          <div className="flex items-center gap-2 px-1 pt-1">
            <span className="inline-flex rounded-full h-2 w-2 bg-gray-500" />
            <span className="text-xs font-medium text-dim">Queued · {queued.length}</span>
          </div>
          {queued.map((task, i) => (
            <QueueCard key={task.id} task={task} position={i + 1} onDispatchNow={handleDispatchNow} />
          ))}
        </>
      )}
    </div>
  );
}
