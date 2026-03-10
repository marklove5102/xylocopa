import { memo } from "react";
import TaskExpandedContent from "./TaskExpandedContent";

const STATUS_STYLE = {
  MERGING:  { label: "Merging...",   color: "text-purple-400" },
  REVIEW:   { label: "Needs Review", color: "text-amber-400" },
  CONFLICT: { label: "Conflict",     color: "text-red-400" },
};

export default memo(function ReviewCard({ task, selected, onSelect, merging, verifying, onApprove, onReject, onRetryMerge, onCancel, onVerify, expanded, onExpand, onRefresh }) {
  const isMerging = merging || task.status === "MERGING";
  const { label: statusLabel, color: statusColor } =
    STATUS_STYLE[isMerging ? "MERGING" : task.status] || STATUS_STYLE.MERGING;

  return (
    <div
      data-review-task={task.id}
      className={`w-full text-left rounded-2xl bg-surface shadow-card overflow-hidden transition-all ${
        selected ? "ring-2 ring-cyan-500/40" : ""
      }`}
    >
      <div className="flex items-start gap-3 px-5 py-[18px]">
        {/* Checkbox */}
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
            {selected && (
              <svg className="w-2.5 h-2.5 text-white animate-checkbox-pop" fill="none" stroke="currentColor" strokeWidth={3} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
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
          {/* Row 1: Title */}
          <p className="text-base font-semibold text-heading leading-snug truncate">{task.title}</p>

          {/* Row 2: Status + attempt */}
          <div className="mt-1.5">
            <span className={`text-sm font-medium ${statusColor}`}>{statusLabel}</span>
            {task.attempt_number > 1 && (
              <span className="text-sm text-orange-400 font-medium ml-2">Attempt #{task.attempt_number}</span>
            )}
          </div>

          {/* Row 3: Preview — hidden when expanded */}
          {!expanded && task.status === "REVIEW" && task.agent_summary && (
            <p className="text-sm text-dim leading-relaxed mt-1 line-clamp-2">{task.agent_summary.slice(0, 200)}</p>
          )}

          {!expanded && task.status === "CONFLICT" && task.error_message && (
            <p className="text-sm text-red-400/80 leading-relaxed mt-1 line-clamp-2">{task.error_message.slice(0, 150)}</p>
          )}
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && <TaskExpandedContent task={task} onRefresh={onRefresh} onCollapse={() => onExpand?.(task.id)} />}
    </div>
  );
});
