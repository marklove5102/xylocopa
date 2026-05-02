import { useEffect, useState } from "react";
import { useWsEvent } from "./useWebSocket";
import { fetchAgentContextUsage } from "../lib/api";

/**
 * Fetches and live-updates an agent's context usage snapshot.
 *
 * Returns null while loading; otherwise:
 *   { total, limit, percent, model, captured_at, has_data, session_id }
 *
 * Subscribes to the `context_usage_update` WS event for live updates after
 * each new assistant turn. Refetches once on agent_id change.
 */
export default function useContextUsage(agentId) {
  const [snap, setSnap] = useState(null);

  useEffect(() => {
    if (!agentId) { setSnap(null); return; }
    let cancelled = false;
    fetchAgentContextUsage(agentId)
      .then((data) => { if (!cancelled && data) setSnap(data); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [agentId]);

  useWsEvent((event) => {
    if (event.type !== "context_usage_update") return;
    if (!event.data || event.data.agent_id !== agentId) return;
    setSnap(event.data);
  }, [agentId]);

  return snap;
}
