import { createContext, useContext, useEffect, useRef, useCallback, useMemo, useSyncExternalStore } from "react";
import { useWebSocketContext } from "./WebSocketContext";

/**
 * Global executing-agents tracker — single source of truth for whether
 * an agent is actively working.  Uses the same detection logic as the
 * chat page's old hookActive state (grace timers on tool end, immediate
 * clear on agent_stream_end) but lifted to app level so every page
 * (agent list, project detail, chat) reads the same value.
 *
 * Signals:
 *   active  ← agent_stream, tool_activity, agent_update(EXECUTING), generating_agents seed
 *   inactive← agent_stream_end, agent_update(terminal: STOPPED/ERROR/STARTING)
 *   grace   ← tool_activity phase="end" starts 30s timer; if no new activity → inactive
 */

const ExecutingAgentsContext = createContext(null);

export function ExecutingAgentsProvider({ children }) {
  const { subscribe } = useWebSocketContext();

  // --- mutable refs (no React re-render on mutation) ---
  const activeRef = useRef(new Set());
  const graceTimersRef = useRef(new Map());   // agentId → timeoutId
  const lastActivityRef = useRef(new Map());  // agentId → timestamp
  const listenersRef = useRef(new Set());

  // Notify all useSyncExternalStore consumers
  const notify = useCallback(() => {
    for (const fn of listenersRef.current) {
      try { fn(); } catch { /* ignore */ }
    }
  }, []);

  const markActive = useCallback((agentId) => {
    clearTimeout(graceTimersRef.current.get(agentId));
    graceTimersRef.current.delete(agentId);
    lastActivityRef.current.set(agentId, Date.now());
    if (!activeRef.current.has(agentId)) {
      const next = new Set(activeRef.current);
      next.add(agentId);
      activeRef.current = next;
      notify();
    }
  }, [notify]);

  const markInactive = useCallback((agentId) => {
    clearTimeout(graceTimersRef.current.get(agentId));
    graceTimersRef.current.delete(agentId);
    lastActivityRef.current.delete(agentId);
    if (activeRef.current.has(agentId)) {
      const next = new Set(activeRef.current);
      next.delete(agentId);
      activeRef.current = next;
      notify();
    }
  }, [notify]);

  const startGraceTimer = useCallback((agentId) => {
    clearTimeout(graceTimersRef.current.get(agentId));
    graceTimersRef.current.set(agentId, setTimeout(() => {
      graceTimersRef.current.delete(agentId);
      const lastTime = lastActivityRef.current.get(agentId) || 0;
      if (Date.now() - lastTime >= 29_000) {
        markInactive(agentId);
      }
    }, 30_000));
  }, [markInactive]);

  // Subscribe to WebSocket events (mirrors old hookActive logic)
  useEffect(() => {
    return subscribe((event) => {
      // Streaming content → active
      if (event.type === "agent_stream" && event.data?.agent_id) {
        markActive(event.data.agent_id);
        return;
      }
      // Tool activity → active; grace timer on tool end
      if (event.type === "tool_activity" && event.data?.agent_id) {
        const aid = event.data.agent_id;
        markActive(aid);
        if (event.data.phase === "end") {
          startGraceTimer(aid);
        }
        return;
      }
      // Stop signal → immediate inactive
      if (event.type === "agent_stream_end" && event.data?.agent_id) {
        markInactive(event.data.agent_id);
        return;
      }
      // Seed from backend on connect/reconnect
      if (event.type === "generating_agents" && event.data?.agent_ids) {
        for (const id of event.data.agent_ids) markActive(id);
        return;
      }
      // Status update from hook
      if (event.type === "agent_update" && event.data?.agent_id) {
        const s = event.data.status;
        if (s === "EXECUTING") {
          markActive(event.data.agent_id);
        } else if (s !== "IDLE") {
          // Terminal status (STOPPED, ERROR, STARTING) → inactive
          markInactive(event.data.agent_id);
        }
        return;
      }
    });
  }, [subscribe, markActive, markInactive, startGraceTimer]);

  // Cleanup grace timers on unmount
  useEffect(() => {
    return () => {
      for (const t of graceTimersRef.current.values()) clearTimeout(t);
    };
  }, []);

  // useSyncExternalStore plumbing
  const subscribeStore = useCallback((listener) => {
    listenersRef.current.add(listener);
    return () => listenersRef.current.delete(listener);
  }, []);
  const getSnapshot = useCallback(() => activeRef.current, []);

  const value = useMemo(() => ({
    subscribeStore,
    getSnapshot,
    markActive,
    markInactive,
  }), [subscribeStore, getSnapshot, markActive, markInactive]);

  return (
    <ExecutingAgentsContext.Provider value={value}>
      {children}
    </ExecutingAgentsContext.Provider>
  );
}

/**
 * Returns a Set<agentId> of agents currently executing.
 * Shared across all consumers — survives page navigation.
 */
export function useExecutingAgents() {
  const ctx = useContext(ExecutingAgentsContext);
  return useSyncExternalStore(ctx.subscribeStore, ctx.getSnapshot);
}

/**
 * Returns the context API for imperative use (e.g. seeding from display file).
 */
export function useExecutingAgentsApi() {
  const ctx = useContext(ExecutingAgentsContext);
  return ctx;
}
