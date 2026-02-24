import { PRIORITIES } from "../lib/constants";

export default function PriorityPicker({ value, onChange }) {
  return (
    <div className="grid grid-cols-3 gap-3">
      {PRIORITIES.map((p) => {
        const isActive = value === p.value;
        return (
          <button
            key={p.value}
            type="button"
            onClick={() => onChange(p.value)}
            className={`min-h-[44px] rounded-lg text-sm font-medium transition-colors ${
              isActive
                ? "bg-cyan-500 text-white shadow-md shadow-cyan-500/20"
                : "bg-elevated text-body hover:bg-hover"
            }`}
          >
            {p.label}
          </button>
        );
      })}
    </div>
  );
}
