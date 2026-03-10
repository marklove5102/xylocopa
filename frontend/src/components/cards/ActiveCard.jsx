import { memo, useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { elapsedDisplay } from "../../lib/formatters";
import TaskExpandedContent from "./TaskExpandedContent";

export default memo(function ActiveCard({ task, selected, onSelect, onCancel, onChat, expanded, onExpand, onRefresh }) {
  const navigate = useNavigate();
  const [elapsed, setElapsed] = useState(task.elapsed_seconds || 0);

  useEffect(() => {
    setElapsed(task.elapsed_seconds || 0);
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [task.elapsed_seconds]);

  return (
    <div
      className={`w-full text-left rounded-2xl bg-surface shadow-card overflow-hidden transition-all ${
        selected ? "ring-2 ring-cyan-500/40" : ""
      }`}
    >
      <div className="flex items-start gap-3 px-5 py-[18px]">
        {/* Pulsing checkbox */}
        <button
          type="button"
          onClick={() => onSelect?.(task.id)}
          className="shrink-0 mt-0.5 group"
          aria-label="Select task"
        >
          <div
            className={`w-5 h-5 rounded-full border-[1.5px] transition-all duration-200 flex items-center justify-center ${
              selected
                ? "border-cyan-500 bg-cyan-500"
                : "border-cyan-400/60 dark:border-cyan-500/40"
            }`}
          >
            {selected ? (
              <svg className="w-2.5 h-2.5 text-white animate-checkbox-pop" fill="none" stroke="currentColor" strokeWidth={3} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-500 animate-pulse" />
            )}
          </div>
        </button>

        {/* Content area */}
        <div
          className="flex-1 min-w-0 cursor-pointer"
          onClick={() => onExpand?.(task.id)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter") onExpand?.(task.id); }}
        >
          {/* Row 1: Title + elapsed */}
          <div className="flex items-start justify-between gap-3">
            <p className="text-base font-semibold text-heading leading-snug truncate">
              {task.title}
            </p>
            <span className="text-[11px] font-mono text-dim shrink-0 mt-0.5">{elapsedDisplay(elapsed)}</span>
          </div>

          {/* Row 2: Status + last message */}
          <div className="mt-1.5">
            <span className="text-sm text-cyan-400 font-medium">Running</span>
            {task.last_agent_message && (
              <p className="text-sm text-dim leading-relaxed mt-0.5 line-clamp-2">{task.last_agent_message}</p>
            )}
          </div>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && <TaskExpandedContent task={task} onRefresh={onRefresh} onCollapse={() => onExpand?.(task.id)} />}
    </div>
  );
});
