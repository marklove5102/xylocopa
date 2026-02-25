import { useEffect, useRef, useCallback, useState } from "react";
import { getAuthToken } from "../lib/api";

/** Show a browser notification for relevant WebSocket events.
 *  Only fires when the tab is hidden (user is elsewhere). */
function showBrowserNotification(event) {
  if (document.visibilityState === "visible") return;
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;

  const d = event.data || {};
  let title, body;

  if (event.type === "agent_update") {
    const s = d.status;
    if (s === "IDLE") { title = "Agent done"; body = d.agent_id?.slice(0, 8); }
    else if (s === "ERROR") { title = "Agent error"; body = d.agent_id?.slice(0, 8); }
    else return; // Don't notify for EXECUTING/SYNCING transitions
  } else {
    return; // Only notify on agent status changes
  }

  try {
    const n = new Notification(title, { body, tag: d.agent_id, renotify: true });
    n.onclick = () => { window.focus(); n.close(); };
    setTimeout(() => n.close(), 8000);
  } catch { /* ignore */ }
}

/**
 * Auto-reconnecting WebSocket hook for real-time status updates.
 *
 * Usage:
 *   const { lastEvent, connected } = useWebSocket();
 *   useEffect(() => { if (lastEvent?.type === "task_update") refresh(); }, [lastEvent]);
 */
export default function useWebSocket() {
  const wsRef = useRef(null);
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState(null);
  const reconnectTimer = useRef(null);
  const reconnectDelay = useRef(1000);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    let url = `${proto}//${window.location.host}/ws/status`;
    const token = getAuthToken();
    if (token) {
      url += `?token=${encodeURIComponent(token)}`;
    }

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        reconnectDelay.current = 1000; // Reset backoff
      };

      ws.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data);
          if (event.type !== "pong") {
            setLastEvent(event);
            showBrowserNotification(event);
          }
        } catch {
          // ignore non-JSON
        }
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        // Reconnect with exponential backoff (max 30s)
        reconnectTimer.current = setTimeout(() => {
          reconnectDelay.current = Math.min(reconnectDelay.current * 1.5, 30000);
          connect();
        }, reconnectDelay.current);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      // WebSocket constructor can throw if URL is invalid
      reconnectTimer.current = setTimeout(connect, reconnectDelay.current);
    }
  }, []);

  useEffect(() => {
    connect();

    // Send ping every 30s to keep connection alive
    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send("ping");
      }
    }, 30000);

    return () => {
      clearInterval(pingInterval);
      clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return { lastEvent, connected };
}
