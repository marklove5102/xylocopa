import { AGENT_MODES } from "../lib/constants";

export default function ModePicker({ value, onChange }) {
  return (
    <div className="grid grid-cols-3 gap-3">
      {AGENT_MODES.map((m) => {
        const isActive = value === m.value;
        return (
          <button
            key={m.value}
            type="button"
            onClick={() => onChange(m.value)}
            className={`min-h-[44px] rounded-lg text-sm font-medium transition-colors ${
              isActive
                ? "bg-cyan-500 text-white shadow-md shadow-cyan-500/20"
                : "bg-elevated text-body hover:bg-hover"
            }`}
          >
            {m.label}
          </button>
        );
      })}
    </div>
  );
}
