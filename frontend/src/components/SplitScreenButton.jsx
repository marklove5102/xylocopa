import { useNavigate, useLocation } from "react-router-dom";
import { useCallback, useEffect, useState, useRef } from "react";
import DraggableFab from "./DraggableFab";
import { fetchUnreadList, getAuthToken } from "../lib/api";
import { useWebSocketContext } from "../contexts/WebSocketContext";

const defaultPos = () => ({
  x: window.innerWidth - 64,
  y: window.innerHeight - 140,
});

export default function SplitScreenButton() {
  const navigate = useNavigate();
  const location = useLocation();
  const [unreadAgents, setUnreadAgents] = useState([]);
  const pathnameRef = useRef(location.pathname);
  pathnameRef.current = location.pathname;
  const { subscribe } = useWebSocketContext();

  // Hide on split screen page itself and on login
  const hidden = location.pathname === "/split" || location.pathname === "/login";

  // Event-driven refresh: WebSocket new_message / agent_update fire
  // almost simultaneously with the backend's unread_count++ and push
  // notification, so the FAB should update in near-real-time rather
  // than waiting for the 5s poll tick.  Polling stays as a safety net
  // for missed events (reconnect gaps, etc.).
  useEffect(() => {
    if (hidden) return;
    let cancelled = false;
    let debounceTimer = null;
    const poll = () => {
      if (!getAuthToken()) return;
      fetchUnreadList()
        .then((r) => { if (!cancelled) setUnreadAgents(r.agents || []); })
        .catch(() => { /* network blips fine — next tick retries */ });
    };
    const pollDebounced = () => {
      if (debounceTimer) return;
      debounceTimer = setTimeout(() => {
        debounceTimer = null;
        poll();
      }, 150);
    };
    poll();
    const id = setInterval(poll, 5000);
    const onDataChanged = () => poll();
    window.addEventListener("agents-data-changed", onDataChanged);
    const unsub = subscribe((event) => {
      if (event.type === "new_message" || event.type === "agent_update") {
        pollDebounced();
      }
    });
    return () => {
      cancelled = true;
      clearInterval(id);
      if (debounceTimer) clearTimeout(debounceTimer);
      window.removeEventListener("agents-data-changed", onDataChanged);
      unsub();
    };
  }, [hidden, subscribe]);

  const unreadTotal = unreadAgents.reduce((s, a) => s + (a.unread_count || 0), 0);
  const hasUnread = unreadAgents.length > 0 && unreadTotal > 0;

  const handleTap = useCallback(() => {
    if (hasUnread) {
      // Jump to oldest unread (FIFO — index 0 is oldest per backend sort)
      const next = unreadAgents[0];
      if (next) {
        navigate(`/agents/${next.id}`);
        return;
      }
    }
    navigate("/split", { state: { initialPath: location.pathname } });
  }, [hasUnread, unreadAgents, navigate, location.pathname]);

  const handleLongPress = useCallback(() => {
    // Always open split-screen, even with unread messages (escape hatch)
    navigate("/split", { state: { initialPath: location.pathname } });
  }, [navigate, location.pathname]);

  if (hidden) return null;

  if (hasUnread) {
    const label = unreadTotal > 99 ? "99+" : String(unreadTotal);
    return (
      <DraggableFab
        storageKey="ah:fab-pos-split-v3"
        defaultPosition={defaultPos}
        onClick={handleTap}
        onLongPress={handleLongPress}
        className="w-11 h-11 flex items-center justify-center rounded-full bg-cyan-500 hover:bg-cyan-400 shadow-lg text-white font-semibold text-base transition-colors"
      >
        {label}
      </DraggableFab>
    );
  }

  return (
    <DraggableFab
      storageKey="ah:fab-pos-split-v3"
      defaultPosition={defaultPos}
      onClick={handleTap}
      onLongPress={handleLongPress}
      className="w-11 h-11 flex items-center justify-center rounded-full bg-surface shadow-lg border border-edge text-dim hover:text-cyan-400 hover:border-cyan-500/50 transition-colors hover:shadow-cyan-500/10"
    >
      {/* Mobile: top-bottom split icon */}
      <svg className="w-5 h-5 md:hidden" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}>
        <rect x="3" y="2" width="18" height="9" rx="2" />
        <rect x="3" y="13" width="18" height="9" rx="2" />
      </svg>
      {/* Desktop: left-right split icon */}
      <svg className="w-5 h-5 hidden md:block" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}>
        <rect x="2" y="3" width="9" height="18" rx="2" />
        <rect x="13" y="3" width="9" height="18" rx="2" />
      </svg>
    </DraggableFab>
  );
}
