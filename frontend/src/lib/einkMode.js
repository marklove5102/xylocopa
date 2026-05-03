// E-ink mode toggle.
//
// Auto-detection (UA sniff + @media (update: slow)) is unreliable —
// devices like Bigme ship Chromium that reports a generic Android Chrome
// UA and doesn't honor the standard e-ink media features. So this is a
// manually-toggled mode in Settings > Display.
//
// When on, adds `eink` class to <html>. CSS in index.css under `html.eink`
// swaps tokens to grayscale, kills animations / transitions / shadows /
// blurs, replaces shimmer skeletons with static blocks. Also requests
// browser fullscreen to maximize the e-ink reading area (Android Chrome
// doesn't expose a fullscreen toggle in its UI; PWA standalone install
// already has no chrome so we skip the API there).

const STORAGE_KEY = "xy:eink-mode";

function isStandalone() {
  if (typeof window === "undefined") return false;
  try {
    return window.matchMedia?.("(display-mode: standalone)")?.matches
        || window.matchMedia?.("(display-mode: fullscreen)")?.matches
        || window.navigator?.standalone === true;
  } catch {
    return false;
  }
}

function isFullscreen() {
  if (typeof document === "undefined") return false;
  return !!(document.fullscreenElement || document.webkitFullscreenElement);
}

function tryEnterFullscreen() {
  if (typeof document === "undefined") return;
  if (isStandalone()) return;
  if (isFullscreen()) return;
  try {
    const el = document.documentElement;
    const req = el.requestFullscreen || el.webkitRequestFullscreen;
    if (!req) return;
    const result = req.call(el);
    if (result && typeof result.catch === "function") result.catch(() => {});
  } catch { /* best-effort: some embedded webviews disallow it */ }
}

function tryExitFullscreen() {
  if (typeof document === "undefined") return;
  if (isStandalone()) return;
  if (!isFullscreen()) return;
  try {
    const exit = document.exitFullscreen || document.webkitExitFullscreen;
    if (!exit) return;
    const result = exit.call(document);
    if (result && typeof result.catch === "function") result.catch(() => {});
  } catch { /* best-effort */ }
}

// Arm a one-shot listener that triggers fullscreen on the user's next
// interaction. Required because requestFullscreen() can only be invoked
// from a user gesture. Self-removes after firing.
let armedListenerActive = false;
function armNextGestureFullscreen() {
  if (typeof document === "undefined") return;
  if (armedListenerActive) return;
  armedListenerActive = true;
  const trigger = () => {
    armedListenerActive = false;
    tryEnterFullscreen();
    document.removeEventListener("click", trigger, true);
    document.removeEventListener("touchend", trigger, true);
    document.removeEventListener("keydown", trigger, true);
  };
  document.addEventListener("click", trigger, true);
  document.addEventListener("touchend", trigger, true);
  document.addEventListener("keydown", trigger, true);
}

// Auto-recovery: when user exits fullscreen (system back gesture, swipe
// down, Escape key, etc.) and eink mode is still on, re-arm the
// one-shot listener so the next interaction puts them back in fullscreen.
// Set up once at startup, lives for the SPA lifetime.
let fullscreenChangeBound = false;
function setupFullscreenAutoRecover() {
  if (typeof document === "undefined") return;
  if (fullscreenChangeBound) return;
  fullscreenChangeBound = true;
  const handler = () => {
    if (!getEinkMode()) return;
    if (isStandalone()) return;
    if (!isFullscreen()) {
      // Just exited; re-arm for next gesture.
      armNextGestureFullscreen();
    }
  };
  document.addEventListener("fullscreenchange", handler);
  document.addEventListener("webkitfullscreenchange", handler);
  // Visibility recovery: returning to the tab from background may also
  // drop fullscreen on some Android browsers — re-arm on visibility
  // change too.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && getEinkMode()
        && !isStandalone() && !isFullscreen()) {
      armNextGestureFullscreen();
    }
  });
}

export function getEinkMode() {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setEinkMode(on) {
  try {
    if (on) localStorage.setItem(STORAGE_KEY, "1");
    else localStorage.removeItem(STORAGE_KEY);
  } catch { /* localStorage may be blocked (private mode) */ }
  applyEinkMode(on);
  // setEinkMode is always called from a click handler in MonitorPage —
  // that user gesture is what unlocks the Fullscreen API.
  if (on) {
    tryEnterFullscreen();
    setupFullscreenAutoRecover();
  } else {
    tryExitFullscreen();
  }
}

export function applyEinkMode(on) {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("eink", !!on);
  if (on) {
    try {
      document.querySelectorAll("video, audio").forEach((el) => {
        if (!el.paused) el.pause();
        el.removeAttribute("autoplay");
      });
    } catch { /* best-effort */ }
  }
}

export function applyEinkModeFromStorage() {
  const on = getEinkMode();
  applyEinkMode(on);
  if (on && !isStandalone() && typeof document !== "undefined") {
    armNextGestureFullscreen();
    setupFullscreenAutoRecover();
  }
}
