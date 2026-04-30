import { memo } from "react";
import { useNavigate } from "react-router-dom";
import { Hourglass } from "lucide-react";
import { relativeTime } from "../lib/formatters";
import { modelDisplayName } from "../lib/constants";
import useLongPress from "../hooks/useLongPress";
import WorktreePill from "./WorktreePill";

/**
 * Shared Chats-style agent row, used on both AgentsPage and inside
 * ProjectDetailPage.
 *
 * Props:
 *   agent           — agent object (name, status, last_message_*, project, …)
 *   onClick         — card click handler (navigate to /agents/:id)
 *   selecting       — multi-select mode on
 *   selected        — is this row selected
 *   onToggle        — (id) => void, multi-select toggle
 *   hideProjectTag  — skip the cyan "project" chip (use when already inside
 *                     a project page so the tag would be redundant)
 */
const AgentRow = memo(function AgentRow({
  agent,
  onClick,
  selecting = false,
  selected = false,
  onToggle,
  onEnterSelect,
  hideProjectTag = false,
}) {
  const navigate = useNavigate();

  const handleClick = () => {
    if (selecting) {
      onToggle?.(agent.id);
    } else {
      onClick?.();
    }
  };

  // Long-press → enter multi-select; ignore presses on inner interactive
  // elements (project tag, etc) so they keep their own click handlers.
  const isInner = (e) => !!e?.target?.closest?.("[data-no-longpress]");
  const longPressHandlers = useLongPress((e) => {
    if (selecting) return;
    if (isInner(e)) return;
    if (navigator.vibrate) navigator.vibrate(15);
    onEnterSelect?.(agent.id);
  }, (e) => {
    if (isInner(e)) return;
    handleClick();
  });

  return (
    <button
      type="button"
      data-agent-id={agent.id}
      data-unread={agent.unread_count > 0 ? "1" : undefined}
      {...longPressHandlers}
      style={{ WebkitTapHighlightColor: "transparent" }}
      className={`w-full text-left rounded-2xl bg-surface shadow-card overflow-hidden transform-gpu transition-[transform,box-shadow,ring-color,opacity,background-color,filter] duration-400 ease-[cubic-bezier(0.22,1.15,0.36,1)] active:bg-input focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 hover:ring-1 hover:ring-ring-hover ${
        selecting && selected ? "ring-2 ring-cyan-500/50 brightness-[0.88]" : ""
      }`}
    >
      <div className="flex items-start gap-3 px-5 py-[18px]">
        {/* Status dot */}
        <div className={`shrink-0 w-2.5 h-2.5 rounded-full self-center -ml-1 mr-1 ${
          agent.status === "EXECUTING" ? "bg-cyan-400 animate-glow"
            : agent.status === "IDLE" ? "bg-cyan-300/50"
            : agent.status === "ERROR" ? "bg-red-400"
            : "bg-zinc-400/50"
        }`} />

        <div className="min-w-0 flex-1">
          {/* Title + time */}
          <div className="flex items-start justify-between gap-3">
            <h3 className="text-base font-medium leading-snug text-heading truncate">
              {agent.name}
            </h3>
            <span className="text-[11px] text-faint shrink-0 mt-0.5">
              {agent.last_message_at ? relativeTime(agent.last_message_at) : ""}
            </span>
          </div>
          {/* Preview + unread badge */}
          <div className="flex items-center gap-2 mt-1">
            <p className="text-sm text-dim truncate min-w-0 flex-1">
              {agent.last_message_preview || "No messages yet"}
            </p>
            {agent.unread_count > 0 && (
              <span className="shrink-0 inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 rounded-full bg-cyan-500 text-white text-xs font-bold">
                {agent.unread_count}
              </span>
            )}
          </div>
          {/* Tags */}
          <div className="flex flex-wrap items-center gap-1 mt-1.5">
            {!hideProjectTag && agent.project && (
              <span
                data-no-longpress
                className="text-[10px] font-medium px-1.5 py-px rounded-full bg-cyan-500/15 text-cyan-600 dark:text-cyan-400 truncate cursor-pointer hover:bg-cyan-500/25 transition-colors"
                onClick={(e) => { e.stopPropagation(); navigate(`/projects/${encodeURIComponent(agent.project)}`); }}
                title={agent.project}
              >{agent.project}</span>
            )}
            {agent.worktree && <WorktreePill name={agent.worktree} />}
            {agent.skip_permissions && (
              <span className="text-[10px] font-medium px-1.5 py-px rounded-full bg-amber-500/15 text-amber-500 dark:text-amber-400">
                Auto
              </span>
            )}
            {agent.model && (
              <span className="text-[10px] text-dim font-medium px-1.5 py-px rounded-full bg-elevated">
                {modelDisplayName(agent.model)}
              </span>
            )}
            {agent.effort && (
              <span className="text-[10px] text-dim font-medium px-1.5 py-px rounded-full bg-elevated">
                {agent.effort.charAt(0).toUpperCase() + agent.effort.slice(1)}
              </span>
            )}
            {agent.insight_status === "failed" && !agent.has_pending_suggestions && (
              <span className="text-[10px] font-semibold px-1.5 py-px rounded-full bg-red-500/15 text-red-500 dark:text-red-400">
                failed
              </span>
            )}
            {agent.deferred_to && new Date(agent.deferred_to) > new Date() && (
              <span className="text-[10px] text-indigo-400 flex items-center gap-0.5">
                <Hourglass className="w-2.5 h-2.5" strokeWidth={2} />
                {relativeTime(agent.deferred_to)}
              </span>
            )}
          </div>
        </div>
        {agent.insight_status === "generating" && !agent.has_pending_suggestions && (
          <span className="shrink-0 self-center text-[10px] font-semibold px-1.5 py-px rounded-full bg-blue-500/15 text-blue-400 animate-pulse">
            generating
          </span>
        )}
        {agent.has_pending_suggestions && (
          <span className="shrink-0 self-center text-[10px] font-semibold px-1.5 py-px rounded-full bg-amber-500/15 text-amber-500 dark:text-amber-400">
            insights
          </span>
        )}
      </div>
    </button>
  );
});

export default AgentRow;
