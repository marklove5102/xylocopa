import { useState, useRef } from "react";

/**
 * Token budget pill — sits between Stop and Monitor in the chat header.
 *
 *   [● 12%]   green   <60%
 *   [● 65%]   amber   60-80%
 *   [● 85%]   red     80-95%
 *   [● 96%]   red+pulse  >95%
 *
 * Click → popover with absolute numbers. Hover → tooltip via title attr.
 * Falls back to neutral grey when no data yet (no assistant turn).
 */
export default function ContextUsagePill({ usage }) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef(null);

  const hasData = !!usage?.has_data;
  const pct = hasData ? Math.max(0, Math.min(999, usage.percent || 0)) : 0;
  const total = hasData ? (usage.total || 0) : 0;
  const limit = usage?.limit || 200_000;

  let chipCls, dotCls, pulse = false;
  if (!hasData) {
    chipCls = "bg-gray-500/15 text-gray-400";
    dotCls = "bg-gray-400";
  } else if (pct < 60) {
    chipCls = "bg-cyan-500/15 text-cyan-600 dark:text-cyan-400";
    dotCls = "bg-cyan-500";
  } else if (pct < 80) {
    chipCls = "bg-amber-500/15 text-amber-500 dark:text-amber-400";
    dotCls = "bg-amber-500";
  } else if (pct < 95) {
    chipCls = "bg-red-500/15 text-red-500 dark:text-red-400";
    dotCls = "bg-red-500";
  } else {
    chipCls = "bg-red-500/20 text-red-500 dark:text-red-400";
    dotCls = "bg-red-500";
    pulse = true;
  }

  const label = hasData ? `${Math.round(pct)}%` : "—";
  const fmt = (n) => n.toLocaleString();
  const titleText = hasData
    ? `Context: ${fmt(total)} / ${fmt(limit)} tokens (${pct.toFixed(1)}%)`
    : "Context: no data yet";

  return (
    <span className="relative inline-flex">
      <button
        ref={btnRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={titleText}
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium transition-colors hover:opacity-80 ${chipCls}`}
      >
        <span className={`inline-block w-1.5 h-1.5 rounded-full ${dotCls} ${pulse ? "animate-pulse" : ""}`} />
        {label}
      </button>
      {open && (
        <ContextUsagePopover
          usage={usage}
          anchorRef={btnRef}
          onClose={() => setOpen(false)}
        />
      )}
    </span>
  );
}

function ContextUsagePopover({ usage, onClose }) {
  const hasData = !!usage?.has_data;
  const total = hasData ? (usage.total || 0) : 0;
  const limit = usage?.limit || 200_000;
  const free = Math.max(0, limit - total);
  const pct = hasData ? (usage.percent || 0) : 0;
  const fmt = (n) => n.toLocaleString();

  return (
    <>
      <div
        className="fixed inset-0 z-40"
        onClick={onClose}
      />
      <div className="absolute right-0 top-full mt-1 z-50 w-72 rounded-lg shadow-lg bg-surface border border-divider p-3 text-xs">
        <div className="font-semibold text-body mb-1">Context Usage</div>
        {hasData ? (
          <>
            <div className="text-dim mb-2 tabular-nums">
              {fmt(total)} / {fmt(limit)} tokens ({pct.toFixed(1)}%)
            </div>
            <div className="w-full h-1.5 rounded-full bg-input overflow-hidden mb-2">
              <div
                className={`h-full ${pct < 60 ? "bg-cyan-500" : pct < 80 ? "bg-amber-500" : "bg-red-500"}`}
                style={{ width: `${Math.min(100, pct)}%` }}
              />
            </div>
            <div className="space-y-0.5 text-dim">
              <div className="flex justify-between"><span>Used</span><span className="tabular-nums">{fmt(total)}</span></div>
              <div className="flex justify-between"><span>Free</span><span className="tabular-nums">{fmt(free)}</span></div>
              {usage.model && (
                <div className="flex justify-between"><span>Model</span><span className="font-mono text-[10px]">{usage.model}</span></div>
              )}
            </div>
            <div className="mt-2 pt-2 border-t border-divider text-[10px] text-faint">
              Headline numbers from session JSONL. Component breakdown coming in a later update.
            </div>
          </>
        ) : (
          <div className="text-dim">
            No assistant turns yet — context usage will appear after the first response.
          </div>
        )}
      </div>
    </>
  );
}
