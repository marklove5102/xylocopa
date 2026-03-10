import { memo, useState, useEffect, useRef, useCallback } from "react";
import { projectDotColor, modelDisplayName } from "../../lib/constants";
import { relativeTime, elapsedDisplay, durationDisplay } from "../../lib/formatters";
import { planTask, dispatchTask, cancelTask, approveTask } from "../../lib/api";
import { useToast } from "../../contexts/ToastContext";
import TaskExpandedContent from "./TaskExpandedContent";

/* ── Checkbox style by status + priority ── */
function getCheckboxStyle(task) {
  const s = task.status;
  // Terminal states: filled circle with icon
  if (s === "COMPLETE")  return { border: "border-gray-400",   bg: "bg-gray-400",   filled: true, icon: "M5 13l4 4L19 7" };
  if (s === "CANCELLED") return { border: "border-gray-400",   bg: "bg-gray-400",   filled: true, icon: "M6 18L18 6M6 6l12 12" };
  if (s === "REJECTED")  return { border: "border-orange-500", bg: "bg-orange-500", filled: true, icon: "M6 18L18 6M6 6l12 12" };
  if (s === "FAILED")    return { border: "border-red-500",    bg: "bg-red-500",    filled: true, icon: "M6 18L18 6M6 6l12 12" };
  if (s === "TIMEOUT")   return { border: "border-orange-500", bg: "bg-orange-500", filled: true, icon: "M12 6v6l4 2m6-2a10 10 0 11-20 0 10 10 0 0120 0z" };

  // Priority overrides for non-terminal states
  if (task.priority >= 2) return { border: "border-red-500",    filled: false };
  if (task.priority >= 1) return { border: "border-orange-500", filled: false };

  // Status-based defaults
  if (s === "PLANNING")                                return { border: "border-blue-500",   filled: false };
  if (s === "EXECUTING")                               return { border: "border-teal-500",   filled: false };
  if (s === "PENDING")                                 return { border: "border-gray-300 dark:border-gray-600", filled: false };
  if (s === "REVIEW" || s === "CONFLICT" || s === "MERGING") return { border: "border-purple-500", filled: false };

  // INBOX default
  return { border: "border-gray-300 dark:border-gray-600", filled: false };
}

/* ── Status metadata label ── */
const STATUS_META = {
  EXECUTING: { label: "Running",  cls: "text-teal-500" },
  REVIEW:    { label: "Review",   cls: "text-amber-400" },
  CONFLICT:  { label: "Conflict", cls: "text-red-400" },
  MERGING:   { label: "Merging",  cls: "text-purple-400" },
  PENDING:   { label: "Queued",   cls: "text-faint" },
};

const DONE_STATUSES = new Set(["COMPLETE", "CANCELLED", "REJECTED", "FAILED", "TIMEOUT"]);
const SWIPE_SNAP = 140;
const SWIPE_SNAP_LEFT = 72;
const SWIPE_THRESHOLD = 50;

export default memo(function TaskRow({ task, selecting, selected, onToggle, expanded, onExpand, onRefresh, position }) {
  const toast = useToast();
  const isDone = DONE_STATUSES.has(task.status);
  const isExecuting = task.status === "EXECUTING";
  const checkStyle = getCheckboxStyle(task);

  // Elapsed timer for executing tasks
  const [elapsed, setElapsed] = useState(task.elapsed_seconds || 0);
  useEffect(() => {
    if (!isExecuting) return;
    setElapsed(task.elapsed_seconds || 0);
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [isExecuting, task.elapsed_seconds]);

  /* ── Swipe gesture (ref-based for 60fps) ── */
  const rowRef = useRef(null);
  const swipeState = useRef({ startX: 0, startY: 0, dx: 0, locked: null, open: 0 });

  const resetSwipe = useCallback(() => {
    const el = rowRef.current?.querySelector("[data-swipe]");
    if (!el) return;
    swipeState.current.open = 0;
    el.style.transition = "transform 0.25s cubic-bezier(.4,0,.2,1)";
    el.style.transform = "translateX(0)";
  }, []);

  useEffect(() => {
    const container = rowRef.current;
    if (!container || selecting || isDone) return;

    const s = swipeState.current;
    const content = container.querySelector("[data-swipe]");
    if (!content) return;

    const onStart = (e) => {
      s.startX = e.touches[0].clientX;
      s.startY = e.touches[0].clientY;
      s.dx = 0;
      s.locked = null;
      content.style.transition = "none";
    };

    const onMove = (e) => {
      const dx = e.touches[0].clientX - s.startX;
      const dy = e.touches[0].clientY - s.startY;

      if (!s.locked) {
        if (Math.abs(dx) > 8 || Math.abs(dy) > 8) {
          s.locked = Math.abs(dx) > Math.abs(dy) ? "h" : "v";
        }
        return;
      }
      if (s.locked !== "h") return;

      e.preventDefault();
      s.dx = dx;
      // Resist beyond snap points
      const clamped = dx > 0
        ? Math.min(SWIPE_SNAP + 20, dx > SWIPE_SNAP ? SWIPE_SNAP + (dx - SWIPE_SNAP) * 0.2 : dx)
        : Math.max(-(SWIPE_SNAP_LEFT + 20), dx < -SWIPE_SNAP_LEFT ? -SWIPE_SNAP_LEFT + (dx + SWIPE_SNAP_LEFT) * 0.2 : dx);
      content.style.transform = `translateX(${clamped}px)`;
    };

    const onEnd = () => {
      if (!s.locked || s.locked !== "h") return;
      content.style.transition = "transform 0.25s cubic-bezier(.4,0,.2,1)";
      if (Math.abs(s.dx) < SWIPE_THRESHOLD) {
        content.style.transform = "translateX(0)";
        s.open = 0;
      } else if (s.dx > 0) {
        content.style.transform = `translateX(${SWIPE_SNAP}px)`;
        s.open = 1;
      } else {
        content.style.transform = `translateX(${-SWIPE_SNAP_LEFT}px)`;
        s.open = -1;
      }
    };

    container.addEventListener("touchstart", onStart, { passive: true });
    container.addEventListener("touchmove", onMove, { passive: false });
    container.addEventListener("touchend", onEnd, { passive: true });

    return () => {
      container.removeEventListener("touchstart", onStart);
      container.removeEventListener("touchmove", onMove);
      container.removeEventListener("touchend", onEnd);
    };
  }, [selecting, isDone]);

  /* ── Actions ── */
  const doAction = useCallback(async (fn, ...args) => {
    resetSwipe();
    try {
      await fn(...args);
      onRefresh?.();
    } catch (err) {
      toast.error(err.message);
    }
  }, [resetSwipe, onRefresh, toast]);

  const handlePlan = () => doAction(planTask, task.id);
  const handleDispatch = () => doAction(dispatchTask, task.id);
  const handleDelete = () => { if (confirm("Delete this task?")) doAction(cancelTask, task.id); };
  const handleApprove = () => doAction(approveTask, task.id);

  const handleClick = () => {
    // If swiped open, reset instead of navigating
    if (swipeState.current.open !== 0) {
      resetSwipe();
      return;
    }
    if (selecting) onToggle?.(task.id);
    else onExpand?.(task.id);
  };

  /* ── Time display ── */
  let timeDisplay;
  if (isExecuting) {
    timeDisplay = elapsedDisplay(elapsed);
  } else if (isDone && task.started_at && task.completed_at) {
    timeDisplay = durationDisplay(task.started_at, task.completed_at);
  } else {
    timeDisplay = relativeTime(task.created_at);
  }

  /* ── Metadata pieces ── */
  const projDot = task.project_name ? projectDotColor(task.project_name) : null;
  const statusMeta = STATUS_META[task.status];
  const meta = [];

  if (task.project_name) {
    meta.push(
      <span key="proj" className="flex items-center gap-1 text-[12px] text-faint">
        <span className={`w-[6px] h-[6px] rounded-full ${projDot} shrink-0`} />
        {task.project_name}
      </span>
    );
  }
  if (task.model) {
    meta.push(<span key="model" className="text-[12px] text-faint">{modelDisplayName(task.model)}</span>);
  }
  if (statusMeta) {
    meta.push(<span key="status" className={`text-[12px] font-medium ${statusMeta.cls}`}>{statusMeta.label}</span>);
  }
  if (position && !selecting) {
    meta.push(<span key="pos" className="text-[12px] text-faint">#{position}</span>);
  }
  if (task.attempt_number > 1) {
    meta.push(<span key="attempt" className="text-[12px] text-orange-400">Attempt #{task.attempt_number}</span>);
  }
  if (task.notify_at) {
    meta.push(
      <span key="notify" className="text-[12px] text-amber-500 dark:text-amber-400 flex items-center gap-0.5">
        <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        {relativeTime(task.notify_at)}
      </span>
    );
  }

  /* ── Determine right-swipe actions ── */
  const canPlan = task.status === "INBOX" && task.project_name;
  const canDispatch = (task.status === "INBOX" || task.status === "PLANNING") && task.project_name;
  const canApprove = task.status === "REVIEW";
  const showRightSwipe = canPlan || canDispatch || canApprove;
  const showLeftSwipe = !isDone;

  return (
    <div
      ref={rowRef}
      className="relative overflow-hidden"
      data-review-task={task.status === "REVIEW" || task.status === "CONFLICT" || task.status === "MERGING" ? task.id : undefined}
    >
      {/* ── Left-side actions (revealed on swipe right) ── */}
      {showRightSwipe && (
        <div className="absolute inset-y-0 left-0 flex" style={{ width: SWIPE_SNAP }}>
          {canPlan && (
            <button
              type="button"
              onClick={handlePlan}
              className="flex-1 flex items-center justify-center bg-violet-500 text-white text-[13px] font-medium active:bg-violet-600"
            >
              Plan
            </button>
          )}
          {canDispatch && (
            <button
              type="button"
              onClick={handleDispatch}
              className="flex-1 flex items-center justify-center bg-green-500 text-white text-[13px] font-medium active:bg-green-600"
            >
              Dispatch
            </button>
          )}
          {canApprove && (
            <button
              type="button"
              onClick={handleApprove}
              className="flex-1 flex items-center justify-center bg-green-500 text-white text-[13px] font-medium active:bg-green-600"
            >
              Approve
            </button>
          )}
        </div>
      )}

      {/* ── Right-side action (revealed on swipe left) ── */}
      {showLeftSwipe && (
        <div className="absolute inset-y-0 right-0 flex" style={{ width: SWIPE_SNAP_LEFT }}>
          <button
            type="button"
            onClick={handleDelete}
            className="flex-1 flex items-center justify-center bg-red-500 text-white text-[13px] font-medium active:bg-red-600"
          >
            Delete
          </button>
        </div>
      )}

      {/* ── Main row content ── */}
      <div
        data-swipe
        className={`relative bg-page transition-colors ${
          selecting && selected ? "bg-blue-50 dark:bg-blue-950/30" : ""
        } ${expanded && !selecting ? "bg-surface/50 dark:bg-surface/30" : ""}`}
      >
        <div
          className="flex items-center gap-3 pl-5 pr-4 cursor-pointer active:bg-surface/60"
          style={{ minHeight: 56 }}
          onClick={handleClick}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter") handleClick(); }}
        >
          {/* ── Checkbox ── */}
          <div className="shrink-0" onClick={(e) => { if (selecting) { e.stopPropagation(); onToggle?.(task.id); } }}>
            {selecting && selected ? (
              <div className="w-5 h-5 rounded-full bg-cyan-500 border-2 border-cyan-500 flex items-center justify-center animate-checkbox-pop">
                <svg className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" strokeWidth={3} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </div>
            ) : selecting ? (
              <div className={`w-5 h-5 rounded-full border-2 ${checkStyle.border}`} />
            ) : checkStyle.filled ? (
              <div className={`w-5 h-5 rounded-full border-2 ${checkStyle.border} ${checkStyle.bg} flex items-center justify-center`}>
                <svg className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" strokeWidth={3} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d={checkStyle.icon} />
                </svg>
              </div>
            ) : (
              <div className={`w-5 h-5 rounded-full border-2 ${checkStyle.border}`} />
            )}
          </div>

          {/* ── Content ── */}
          <div className="flex-1 min-w-0 py-[14px]">
            {/* Title row */}
            <div className="flex items-center gap-1.5">
              {isExecuting && !selecting && (
                <span className="w-[6px] h-[6px] rounded-full bg-teal-500 animate-pulse shrink-0" />
              )}
              <p className={`text-[15px] leading-snug truncate ${
                isDone ? "text-faint line-through" : "text-heading"
              }`}>
                {task.title}
              </p>
            </div>

            {/* Metadata row */}
            {meta.length > 0 && (
              <div className="flex items-center gap-1 mt-0.5 overflow-hidden">
                {meta.map((item, i) => (
                  <span key={i} className="flex items-center gap-1 shrink-0">
                    {i > 0 && <span className="text-faint text-[10px] mx-0.5">&middot;</span>}
                    {item}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* ── Time ── */}
          <span className={`text-[11px] shrink-0 ${isExecuting ? "font-mono text-dim" : "text-faint"}`}>
            {timeDisplay}
          </span>
        </div>

        {/* ── Expanded content ── */}
        {!selecting && expanded && (
          <TaskExpandedContent task={task} onRefresh={onRefresh} onCollapse={() => onExpand?.(task.id)} />
        )}
      </div>
    </div>
  );
});
