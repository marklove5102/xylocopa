import { PRIORITY_COLORS } from "../lib/constants";

export default function PriorityBadge({ priority }) {
  const cls = PRIORITY_COLORS[priority] || PRIORITY_COLORS.P2;
  return (
    <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${cls}`}>
      {priority}
    </span>
  );
}
