import { memo } from "react";
import { modelDisplayName } from "../../lib/constants";
import TaskExpandedContent from "./TaskExpandedContent";

export default memo(function QueueCard({ task, position, selected, onSelect, expanded, onExpand, onRefresh }) {
  return (
    <div
      className={`w-full text-left rounded-2xl bg-surface shadow-card overflow-hidden transition-all ${
        selected ? "ring-2 ring-cyan-500/40" : ""
      }`}
    >
      <div className="flex items-start gap-3 px-5 py-[18px]">
        {/* Checkbox with position */}
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
                : "border-gray-300 dark:border-gray-600 group-hover:border-cyan-400 dark:group-hover:border-cyan-400"
            }`}
          >
            {selected ? (
              <svg className="w-2.5 h-2.5 text-white animate-checkbox-pop" fill="none" stroke="currentColor" strokeWidth={3} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            ) : (
              <span className="text-[9px] font-bold text-dim">{position}</span>
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
          <p className="text-base font-semibold text-heading leading-snug truncate">
            {task.title}
          </p>

          {!expanded && task.description && task.description !== task.title && (
            <p className="text-sm text-dim leading-relaxed mt-1.5 line-clamp-2">
              {task.description.slice(0, 200)}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-1.5 mt-2.5">
            {task.model && (
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-elevated text-dim">
                {modelDisplayName(task.model)}
              </span>
            )}
            {task.effort && (
              <span className="text-[11px] font-medium px-1.5 py-0.5 rounded-full bg-elevated text-dim uppercase">
                {task.effort[0]}
              </span>
            )}
            {task.priority >= 1 && (
              <span className="text-[11px] font-semibold px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-500 dark:text-amber-400">
                H
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && <TaskExpandedContent task={task} onRefresh={onRefresh} onCollapse={() => onExpand?.(task.id)} />}
    </div>
  );
});
