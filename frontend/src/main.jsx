import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "katex/dist/katex.min.css";
import "./index.css";
import App from "./App.jsx";
import { registerSW } from "virtual:pwa-register";

// --- Reload tracing probe ---------------------------------------------------
// Logs every reload trigger to /api/debug/auth-diag so we can tell which of
// these is causing white-screen refreshes: (A) SW controllerchange from
// VitePWA autoUpdate, (B) explicit window.location.reload() from app code,
// (C) vite HMR full-reload after ws reconnect, (D) iOS background kill
// (no event at all — absence is the signal).  Remove after root cause pinned.
(function installReloadProbe() {
  const beacon = (payload) => {
    try {
      const body = JSON.stringify({ ...payload, ts: Date.now(), path: location.pathname });
      if (navigator.sendBeacon) {
        navigator.sendBeacon("/api/debug/auth-diag", new Blob([body], { type: "application/json" }));
      } else {
        fetch("/api/debug/auth-diag", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
          keepalive: true,
        }).catch(() => {});
      }
    } catch { /* best-effort */ }
  };
  try {
    const origReload = window.location.reload.bind(window.location);
    window.location.reload = function (...args) {
      beacon({ action: "reload-trace", reason: "location.reload", stack: (new Error().stack || "").slice(0, 1500) });
      return origReload(...args);
    };
  } catch { /* some browsers block reassigning location.reload */ }
  window.addEventListener("pagehide", (e) => {
    beacon({ action: "reload-trace", reason: "pagehide", persisted: e.persisted });
  });
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      beacon({ action: "reload-trace", reason: "sw-controllerchange" });
    });
  }
  try {
    const nav = performance.getEntriesByType("navigation")[0];
    if (nav?.type === "reload") {
      beacon({ action: "reload-trace", reason: "load-after-reload" });
    }
  } catch { /* performance API may be restricted */ }
})();

// Register VitePWA service worker with autoUpdate.
// Precaches all static assets (JS/CSS/HTML with content hashes).
if ("serviceWorker" in navigator) {
  registerSW({
    onRegisteredSW(swUrl, registration) {
      if (!registration) return;
      // Check for SW updates every 30 minutes (background)
      setInterval(() => { registration.update(); }, 30 * 60 * 1000);
      // Also check on every tab/app focus — catches rebuilds immediately
      // when user switches back to the app (mobile PWA, iPad, etc.)
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") registration.update();
      });
    },
  });
}

// Global error handlers — catch async/event-handler errors that React
// error boundaries cannot intercept.  Shows a raw DOM toast so it works
// even if React itself has crashed.
function showErrorToast(msg) {
  // Skip expected auth errors
  if (typeof msg === "string" && msg.includes("Not authenticated")) return;

  let container = document.getElementById("global-error-toast");
  if (!container) {
    container = document.createElement("div");
    container.id = "global-error-toast";
    Object.assign(container.style, {
      position: "fixed",
      bottom: "80px",
      left: "50%",
      transform: "translateX(-50%)",
      zIndex: "99999",
      maxWidth: "90vw",
      padding: "10px 18px",
      borderRadius: "10px",
      background: "#dc2626",
      color: "#fff",
      fontSize: "13px",
      fontFamily: "system-ui, sans-serif",
      boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
      pointerEvents: "none",
      opacity: "0",
      transition: "opacity 0.3s",
    });
    document.body.appendChild(container);
  }
  container.textContent = String(msg).slice(0, 200);
  container.style.opacity = "1";
  clearTimeout(container._timer);
  container._timer = setTimeout(() => {
    container.style.opacity = "0";
  }, 5000);
}

window.addEventListener("error", (e) => {
  showErrorToast(e.message || "Uncaught error");
});

window.addEventListener("unhandledrejection", (e) => {
  const msg = e.reason?.message || e.reason || "Unhandled promise rejection";
  showErrorToast(msg);
});

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>
);
