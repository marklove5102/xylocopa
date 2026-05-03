import { useEffect, useMemo, useState } from "react";
import { useWsEvent } from "./useWebSocket";

/**
 * Live context-usage snapshot for an agent.
 *
 * Returns null when no data yet; otherwise:
 *   { total, limit, percent, model, captured_at, has_data, session_id,
 *     components, suggestions, ... }
 *
 * Source of truth has moved to the persisted columns on the agent row
 * (context_total, context_limit, context_percent, context_captured_at,
 * context_breakdown). The chat page already has the agent record from
 * briefCache + fetchAgent, so we just project those fields here. WS
 * `context_usage_update` events merge into a local override so live
 * updates take precedence over the (slightly older) DB-persisted snapshot.
 *
 * Pass the `agent` object (not just an id) so the hook can derive the
 * snapshot synchronously without a separate HTTP fetch.
 */
export default function useContextUsage(agent) {
  const [wsOverride, setWsOverride] = useState(null);

  // Reset override when the agent id changes (switching chats)
  const agentId = agent?.id;
  useEffect(() => { setWsOverride(null); }, [agentId]);

  useWsEvent((event) => {
    if (event.type !== "context_usage_update") return;
    if (!event.data || event.data.agent_id !== agentId) return;
    setWsOverride(event.data);
  }, [agentId]);

  return useMemo(() => {
    // Live WS payload wins.
    if (wsOverride) return wsOverride;
    if (!agent) return null;
    if (agent.context_total == null && agent.context_percent == null) return null;
    let breakdown = {};
    if (agent.context_breakdown) {
      try { breakdown = JSON.parse(agent.context_breakdown); } catch { /* ignore */ }
    }
    return {
      total: agent.context_total,
      limit: agent.context_limit,
      percent: agent.context_percent,
      captured_at: agent.context_captured_at,
      model: agent.model,
      has_data: agent.context_total != null,
      session_id: agent.session_id,
      ...breakdown,  // components / suggestions / free / etc.
    };
  }, [agent, wsOverride]);
}
