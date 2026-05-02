import { useState, useRef } from "react";

/**
 * Token budget pill — sits between Stop and Monitor in the chat header.
 *
 *   [● 12%]   green   <60%
 *   [● 65%]   amber   60-80%
 *   [● 85%]   red     80-95%
 *   [● 96%]   red+pulse  >95%
 *
 * Click → popover with per-component breakdown + suggestions.
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
  const [expanded, setExpanded] = useState({});

  // Single source of truth: usage prop already carries components +
  // suggestions, refreshed via WS push on every assistant turn.
  const hasData = !!usage?.has_data;
  const total = hasData ? (usage.total || 0) : 0;
  const limit = usage?.limit || 200_000;
  const free = Math.max(0, limit - total);
  const pct = hasData ? (usage.percent || 0) : 0;
  const fmt = (n) => n.toLocaleString();

  const components = usage?.components || [];
  const suggestions = usage?.suggestions || [];

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

            {usage?.lifetime && (
              <LifetimeSection lifetime={usage.lifetime} />
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

function LifetimeSection({ lifetime }) {
  const [expanded, setExpanded] = useState(false);
  const fmt = (n) => (n || 0).toLocaleString();
  const fmtTok = (n) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
  };
  const cost = lifetime.estimated_cost_usd || 0;
  const fmtCost = (c) => c >= 100 ? `$${c.toFixed(0)}` : c >= 1 ? `$${c.toFixed(2)}` : `$${c.toFixed(4)}`;
  const sc = lifetime.session_count || 0;
  const hc = lifetime.history_session_count || 0;
  const sessionStr = sc <= 1 ? "current session" : `${sc} CC sessions (${hc} historical)`;
  const byKind = lifetime.by_kind || {};
  const pricing = lifetime.pricing_per_million || {};

  return (
    <div className="mt-3 pt-2 border-t border-divider">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between py-0.5 hover:bg-input rounded px-1 -mx-1"
      >
        <span className="flex items-center gap-1.5">
          <span className="font-semibold text-body">Lifetime spend</span>
          <svg className={`w-3 h-3 text-dim transition-transform ${expanded ? "rotate-90" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </span>
        <span className="tabular-nums text-body">
          {fmtTok(lifetime.total_tokens || 0)} <span className="text-dim">·</span> {fmtCost(cost)}
        </span>
      </button>
      <div className="text-[10px] text-faint pl-1">{sessionStr} · {lifetime.turn_count || 0} turns</div>

      {expanded && (
        <div className="mt-1.5 ml-1 space-y-0.5 text-[10px]">
          <LifetimeRow label="Input (fresh)"  tokens={byKind.input_tokens}                rate={pricing.input}        />
          <LifetimeRow label="Cache write"    tokens={byKind.cache_creation_input_tokens} rate={pricing.cache_create} />
          <LifetimeRow label="Cache read"     tokens={byKind.cache_read_input_tokens}     rate={pricing.cache_read}   />
          <LifetimeRow label="Output"         tokens={byKind.output_tokens}               rate={pricing.output}       />
          {lifetime.pricing_model && (
            <div className="text-faint italic mt-1">
              Pricing for {lifetime.pricing_model} (USD/M tokens)
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function LifetimeRow({ label, tokens, rate }) {
  const t = tokens || 0;
  const r = rate || 0;
  const cost = (t * r) / 1_000_000;
  const fmt = (n) => n.toLocaleString();
  const fmtCost = (c) => c >= 1 ? `$${c.toFixed(2)}` : `$${c.toFixed(4)}`;
  return (
    <div className="flex items-center justify-between text-dim">
      <span>{label} <span className="text-faint">@ ${r.toFixed(2)}</span></span>
      <span className="tabular-nums">
        {fmt(t)} <span className="text-faint">·</span> {fmtCost(cost)}
      </span>
    </div>
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
