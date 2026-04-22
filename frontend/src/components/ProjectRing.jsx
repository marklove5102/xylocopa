import FluentEmoji from "./FluentEmoji";
import { defaultProjectEmoji } from "../lib/projectEmoji";

/**
 * Circular icon for a project.
 *
 * Composes three visual layers:
 *   - stroke color     → operational status (running / idle-with-tasks / dormant)
 *   - stroke fill (%)  → weekly completion rate
 *   - emoji inside     → user-chosen identity, or default folder that flips
 *                         open (📂) when active, closed (📁) when not
 */
export default function ProjectRing({
  emoji,
  hasActiveAgents = false,
  hasTasks = false,
  pct = null,
  size = 32,
  emojiSize = 18,
  className = "",
}) {
  const state = hasActiveAgents ? "running" : hasTasks ? "ready" : "idle";
  const stroke = state === "running" ? "#22d3ee"      // cyan-400
    : state === "ready" ? "#34d399"                   // emerald-400
    : "#a1a1aa66";                                    // zinc-400/40

  const r = (size - 4) / 2;
  const c = 2 * Math.PI * r;
  const clampedPct = pct == null ? null : Math.max(0, Math.min(100, pct));
  const hasProgress = clampedPct != null;
  const offset = hasProgress ? c * (1 - clampedPct / 100) : 0;
  const half = size / 2;

  const displayEmoji = emoji || defaultProjectEmoji({ hasActiveAgents });

  return (
    <div
      className={`relative inline-flex items-center justify-center shrink-0 ${state === "running" ? "animate-breathe" : ""} ${className}`}
      style={{ width: size, height: size }}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="absolute inset-0"
      >
        {/* Track */}
        <circle
          cx={half}
          cy={half}
          r={r}
          fill="transparent"
          stroke={stroke}
          strokeWidth={2}
          opacity={hasProgress ? 0.18 : 0.35}
        />
        {/* Progress arc */}
        {hasProgress && (
          <circle
            cx={half}
            cy={half}
            r={r}
            fill="transparent"
            stroke={stroke}
            strokeWidth={2}
            strokeLinecap="round"
            strokeDasharray={c}
            strokeDashoffset={offset}
            transform={`rotate(-90 ${half} ${half})`}
            style={{ transition: "stroke-dashoffset 0.6s ease" }}
          />
        )}
      </svg>
      <FluentEmoji char={displayEmoji} size={emojiSize} />
    </div>
  );
}
