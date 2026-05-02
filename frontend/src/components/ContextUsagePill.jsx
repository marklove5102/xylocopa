import { useState, useRef, useEffect } from "react";
import { fetchAgentContextBreakdown, sendMessage } from "../lib/api";

/**
 * Build a self-contained markdown prompt that captures the full token
 * budget snapshot. Sent as a user message when the user clicks "Ask
 * Claude to optimize" — Claude then has structured context to reason
 * about which buckets to /compact, which MCP servers to disable, etc.
 */
function buildOptimizationPrompt(usage, breakdown) {
  const fmt = (n) => (n || 0).toLocaleString();
  const total = usage?.total || 0;
  const limit = usage?.limit || 200_000;
  const pct = (usage?.percent || 0).toFixed(1);
  const components = breakdown?.components || [];
  const suggestions = breakdown?.suggestions || [];

  const lines = [
    `My current context window usage:`,
    ``,
    `**Total:** ${fmt(total)} / ${fmt(limit)} tokens (${pct}%)`,
    `**Model:** ${usage?.model || "unknown"}`,
    ``,
    `### Breakdown`,
  ];
  for (const c of components) {
    lines.push(`- **${c.name}:** ${fmt(c.tokens)} tokens (${c.percent.toFixed(1)}%)`);
    if (Array.isArray(c.breakdown)) {
      for (const b of c.breakdown) {
        const mark = b.estimated ? " (~ estimated)" : "";
        lines.push(`  - ${b.name}: ${fmt(b.tokens)}${mark}`);
      }
    }
  }
  if (suggestions.length > 0) {
    lines.push(``, `### Auto-detected warnings`);
    for (const s of suggestions) {
      lines.push(`- [${s.severity}] ${s.text}`);
    }
  }
  lines.push(
    ``,
    `Where is my context potentially inefficient and what should I do to free up space?`,
    `Be specific — name MCP servers to disable, files to trim, or whether /compact would help most.`,
  );
  return lines.join("\n");
}

/**
 * Token budget pill — sits between Stop and Monitor in the chat header.
 *
 *   [● 12%]   green   <60%
 *   [● 65%]   amber   60-80%
 *   [● 85%]   red     80-95%
 *   [● 96%]   red+pulse  >95%
 *
 * Click → popover with per-component breakdown + suggestions (lazy-fetched).
 * Hover → tooltip via title attr with absolute numbers.
 */
export default function ContextUsagePill({ usage, agentId }) {
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
          agentId={agentId}
          onClose={() => setOpen(false)}
        />
      )}
    </span>
  );
}

const SEVERITY_STYLES = {
  urgent: "bg-red-500/15 text-red-600 dark:text-red-400 border-l-2 border-red-500",
  warn: "bg-amber-500/15 text-amber-600 dark:text-amber-400 border-l-2 border-amber-500",
  info: "bg-cyan-500/15 text-cyan-600 dark:text-cyan-400 border-l-2 border-cyan-500",
};

function ContextUsagePopover({ usage, agentId, onClose }) {
  const [breakdown, setBreakdown] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState({});
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState(null);

  useEffect(() => {
    if (!agentId) return;
    let cancelled = false;
    fetchAgentContextBreakdown(agentId)
      .then((data) => { if (!cancelled) { setBreakdown(data); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [agentId]);

  const hasData = !!usage?.has_data;
  const total = hasData ? (usage.total || 0) : 0;
  const limit = usage?.limit || 200_000;
  const free = Math.max(0, limit - total);
  const pct = hasData ? (usage.percent || 0) : 0;
  const fmt = (n) => n.toLocaleString();

  const components = breakdown?.components || [];
  const suggestions = breakdown?.suggestions || [];

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div className="absolute right-0 top-full mt-1 z-50 w-80 max-w-[90vw] rounded-lg shadow-lg bg-surface border border-divider p-3 text-xs max-h-[70vh] overflow-y-auto">
        <div className="flex items-baseline justify-between mb-1">
          <div className="font-semibold text-body">Context Usage</div>
          {usage?.model && (
            <div className="font-mono text-[10px] text-faint">{usage.model}</div>
          )}
        </div>

        {!hasData ? (
          <div className="text-dim">
            No assistant turns yet — usage will appear after the first response.
          </div>
        ) : (
          <>
            <div className="text-dim mb-2 tabular-nums">
              {fmt(total)} / {fmt(limit)} tokens ({pct.toFixed(1)}%)
            </div>
            <div className="w-full h-2 rounded-full bg-input overflow-hidden mb-3 flex">
              {components.map((c) => {
                const widthPct = Math.min(100, (c.tokens / limit) * 100);
                if (widthPct < 0.1) return null;
                const color = COMPONENT_COLOR[c.name] || "bg-gray-500";
                return (
                  <div
                    key={c.name}
                    className={`h-full ${color}`}
                    style={{ width: `${widthPct}%` }}
                    title={`${c.name}: ${fmt(c.tokens)} (${c.percent.toFixed(1)}%)`}
                  />
                );
              })}
            </div>

            {loading && !components.length ? (
              <div className="text-dim animate-pulse">Loading breakdown...</div>
            ) : (
              <div className="space-y-1">
                {components.map((c) => (
                  <ComponentRow
                    key={c.name}
                    component={c}
                    expanded={!!expanded[c.name]}
                    onToggle={() => setExpanded((s) => ({ ...s, [c.name]: !s[c.name] }))}
                  />
                ))}
                <div className="flex items-center justify-between py-1 text-dim border-t border-divider mt-2 pt-2">
                  <span>Free space</span>
                  <span className="tabular-nums">
                    {fmt(free)}
                    <span className="text-faint ml-1">({((free / limit) * 100).toFixed(1)}%)</span>
                  </span>
                </div>
              </div>
            )}

            {suggestions.length > 0 && (
              <div className="mt-3 pt-2 border-t border-divider">
                <div className="font-semibold text-body mb-1.5">Suggestions</div>
                <div className="space-y-1">
                  {suggestions.map((s, i) => (
                    <div key={i} className={`px-2 py-1.5 rounded text-[11px] leading-snug ${SEVERITY_STYLES[s.severity] || SEVERITY_STYLES.info}`}>
                      {s.text}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {breakdown && hasData && (
              <div className="mt-3 pt-2 border-t border-divider">
                <button
                  type="button"
                  disabled={sending || !agentId}
                  onClick={async () => {
                    if (!agentId) return;
                    setSending(true);
                    setSendError(null);
                    try {
                      const prompt = buildOptimizationPrompt(usage, breakdown);
                      await sendMessage(agentId, prompt);
                      onClose();
                    } catch (err) {
                      setSendError(err?.message || "Failed to send");
                      setSending(false);
                    }
                  }}
                  className="w-full px-3 py-1.5 rounded-md text-[11px] font-medium bg-violet-600 hover:bg-violet-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center justify-center gap-1.5"
                >
                  {sending ? (
                    <>
                      <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="40 60" />
                      </svg>
                      Sending...
                    </>
                  ) : (
                    <>
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18 7.5L17.553 9 17 10.5l-1.5-.447L14 9.5l1.553-.553L17 8l.553-1.5L18 5l.553 1.5L19 8l1.5.447L21 9l-1.5.553L18 10z" />
                      </svg>
                      Ask Claude to optimize
                    </>
                  )}
                </button>
                {sendError && (
                  <div className="mt-1 text-[10px] text-red-500 dark:text-red-400">{sendError}</div>
                )}
              </div>
            )}

            <div className="mt-2 pt-2 border-t border-divider text-[10px] text-faint">
              Total from JSONL `usage` (exact). Static buckets approximate;
              Messages absorbs residual.
            </div>
          </>
        )}
      </div>
    </>
  );
}

const COMPONENT_COLOR = {
  "Messages": "bg-cyan-500",
  "MCP tools": "bg-violet-500",
  "Memory files": "bg-amber-500",
  "Custom Agents": "bg-emerald-500",
  "System overhead": "bg-gray-500",
};

function ComponentRow({ component, expanded, onToggle }) {
  const fmt = (n) => n.toLocaleString();
  const hasBreakdown = Array.isArray(component.breakdown) && component.breakdown.length > 0;
  const dotColor = COMPONENT_COLOR[component.name] || "bg-gray-500";

  return (
    <div>
      <button
        type="button"
        onClick={hasBreakdown ? onToggle : undefined}
        disabled={!hasBreakdown}
        className={`w-full flex items-center justify-between py-1 ${hasBreakdown ? "hover:bg-input rounded px-1 -mx-1" : ""}`}
      >
        <span className="flex items-center gap-1.5 min-w-0">
          <span className={`inline-block w-2 h-2 rounded-sm shrink-0 ${dotColor}`} />
          <span className="truncate text-body">{component.name}</span>
          {hasBreakdown && (
            <svg className={`w-3 h-3 shrink-0 text-dim transition-transform ${expanded ? "rotate-90" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          )}
        </span>
        <span className="tabular-nums text-dim shrink-0">
          {fmt(component.tokens)}
          <span className="text-faint ml-1">({component.percent.toFixed(1)}%)</span>
        </span>
      </button>
      {expanded && hasBreakdown && (
        <div className="ml-3.5 my-1 space-y-0.5 border-l border-divider pl-2">
          {component.breakdown.map((b, i) => (
            <div key={i} className="flex items-center justify-between text-[10px] text-dim">
              <span className="truncate font-mono">{b.name}</span>
              <span className="tabular-nums shrink-0 ml-2">
                {fmt(b.tokens)}
                {b.estimated && <span className="text-faint ml-0.5">~</span>}
              </span>
            </div>
          ))}
          {component.info && (
            <div className="text-[10px] text-faint italic mt-1">{component.info}</div>
          )}
        </div>
      )}
    </div>
  );
}
