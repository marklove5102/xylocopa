import { MODE_COLORS } from "../lib/constants";

export default function ModeBadge({ mode }) {
  const cls = MODE_COLORS[mode] || MODE_COLORS.AUTO;
  return (
    <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${cls}`}>
      {mode}
    </span>
  );
}
