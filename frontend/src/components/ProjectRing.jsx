import FluentEmoji from "./FluentEmoji";
import { defaultProjectEmoji } from "../lib/projectEmoji";

/**
 * Project identity icon.
 *
 * Displays the user's chosen emoji, or the default folder (open 📂 when
 * an agent is active, closed 📁 otherwise). No ring, no animation —
 * the emoji itself is the whole visual.
 */
export default function ProjectRing({
  emoji,
  hasActiveAgents = false,
  size = 28,
  className = "",
}) {
  const displayEmoji = emoji || defaultProjectEmoji({ hasActiveAgents });

  return (
    <span
      className={`inline-flex items-center justify-center shrink-0 ${className}`}
      style={{ width: size, height: size }}
    >
      <FluentEmoji char={displayEmoji} size={size} />
    </span>
  );
}
