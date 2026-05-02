import { createContext, useContext, useEffect, useMemo, useRef, useState, useCallback } from "react";
import { fetchAgents, getAuthToken } from "../lib/api";
import { useWebSocketContext } from "./WebSocketContext";
import usePageVisible from "../hooks/usePageVisible";
import { POLL_INTERVAL } from "../lib/constants";

const AgentsContext = createContext(null);

/**
 * Single source of truth for the full agent list across the app.
 *
 * Why this exists:
 *   AgentsPage / AgentPickerPanel each used to call fetchAgents() on
 *   mount and again every poll tick, so every navigation back to the
 *   list incurred a fresh HTTP round-trip and showed a "Loading
 *   agents..." flash. The backend already broadcasts agent_update /
 *   agent_created over WebSocket, so we can keep one warm copy here
 *   and let consumers subscribe — same model as UnreadProvider.
 *
 * Lifecycle:
 *   - Mount once (under WebSocketProvider) → seed via HTTP fetchAgents().
 *   - WS agent_update / agent_created → in-place merge (no refetch).
 *   - WS reconnect → resync via fetchAgents() to close any gap.
 *   - 'agents-data-changed' window event → resync (used by code paths
 *     that mutate state without a corresponding WS event, e.g. bulk
 *     delete, adopt unlinked, mark read).
 *   - Periodic POLL_INTERVAL refresh while the page is visible — kept
 *     as a safety net for fields the WS payload doesn't carry (name,
 *     starred, deferred_to, deletes).
 */
export function AgentsProvider({ children }) {
  const { subscribe, onOpen } = useWebSocketContext();
  const visible = usePageVisible();
  const [agents, setAgents] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);

  const inFlightRef = useRef(null);

  const refresh = useCallback(async (reason) => {
    if (!getAuthToken()) return;
    if (inFlightRef.current) return inFlightRef.current;
    const p = (async () => {
      try {
        const data = await fetchAgents();
        const list = Array.isArray(data) ? data : [];
        setAgents(list);
        setError(null);
        setLoaded(true);
        // eslint-disable-next-line no-console
        console.info(`[agents] ${reason}`, list.length);
      } catch (err) {
        setError(err.message || String(err));
        setLoaded(true);
      } finally {
        inFlightRef.current = null;
      }
    })();
    inFlightRef.current = p;
    return p;
  }, []);

  // Initial seed
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current) return;
    if (!getAuthToken()) return;
    seededRef.current = true;
    refresh("seed");
  }, [refresh]);

  // WS incremental updates — agent_update merges fields, agent_created prepends.
  useEffect(() => {
    const unsub = subscribe((event) => {
      if (event?.type === "agent_update") {
        const d = event.data || {};
        const { agent_id } = d;
        if (!agent_id) return;
        setAgents((prev) =>
          prev.map((a) => {
            if (a.id !== agent_id) return a;
            const next = { ...a };
            if (d.status !== undefined) next.status = d.status;
            if (d.unread_count !== undefined) next.unread_count = d.unread_count;
            if (d.last_message_preview !== undefined) next.last_message_preview = d.last_message_preview;
            if (d.last_message_at !== undefined) next.last_message_at = d.last_message_at;
            if (d.has_pending_suggestions !== undefined) next.has_pending_suggestions = d.has_pending_suggestions;
            if (d.insight_status !== undefined) next.insight_status = d.insight_status;
            return next;
          })
        );
        return;
      }
      if (event?.type === "agent_created") {
        const newAgent = event.data;
        if (!newAgent?.id) return;
        setAgents((prev) => {
          if (prev.some((a) => a.id === newAgent.id)) return prev;
          return [newAgent, ...prev];
        });
        return;
      }
    });
    return unsub;
  }, [subscribe]);

  // WS reconnect → HTTP resync to catch missed events.
  useEffect(() => {
    if (typeof onOpen !== "function") return;
    const unsub = onOpen(() => {
      if (!seededRef.current) return; // initial seed already covers first open
      refresh("ws-reopen");
    });
    return unsub;
  }, [onOpen, refresh]);

  // Explicit invalidation hook used by mutation-heavy paths
  // (bulk delete, adopt, mark-read, etc.) where the page wants the
  // authoritative server state.
  useEffect(() => {
    const onDataChanged = () => refresh("agents-data-changed");
    window.addEventListener("agents-data-changed", onDataChanged);
    return () => window.removeEventListener("agents-data-changed", onDataChanged);
  }, [refresh]);

  // Background polling as a safety net for fields/events not covered
  // by WS (deletes, name changes, starred toggles done elsewhere).
  // Throttle to POLL_INTERVAL and only when the page is visible.
  useEffect(() => {
    if (!visible) return;
    const t = setInterval(() => refresh("poll"), POLL_INTERVAL);
    return () => clearInterval(t);
  }, [visible, refresh]);

  const value = useMemo(() => ({
    agents,
    loaded,
    error,
    refresh,
    setAgents,
  }), [agents, loaded, error, refresh]);

  return <AgentsContext.Provider value={value}>{children}</AgentsContext.Provider>;
}

const _fallback = {
  agents: [],
  loaded: false,
  error: null,
  refresh: async () => {},
  setAgents: () => {},
};

export function useAgents() {
  const ctx = useContext(AgentsContext);
  if (!ctx) return _fallback;
  return ctx;
}
