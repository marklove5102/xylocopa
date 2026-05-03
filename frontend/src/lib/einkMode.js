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

function tryEnterFullscreen() {
  if (typeof document === "undefined") return;
  if (isStandalone()) return;
  // Already in fullscreen?
  if (document.fullscreenElement || document.webkitFullscreenElement) return;
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
  if (!document.fullscreenElement && !document.webkitFullscreenElement) return;
  try {
    const exit = document.exitFullscreen || document.webkitExitFullscreen;
    if (!exit) return;
    const result = exit.call(document);
    if (result && typeof result.catch === "function") result.catch(() => {});
  } catch { /* best-effort */ }
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
  // that user gesture is what unlocks the Fullscreen API. Direct call
  // here, no need for a deferred listener.
  if (on) tryEnterFullscreen();
  else tryExitFullscreen();
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
  // On startup we can't request fullscreen directly — it requires a
  // user gesture. Instead, wire a one-shot listener that fires on the
  // first interaction. Skipped in standalone (PWA install already has
  // no browser chrome).
  if (on && !isStandalone() && typeof document !== "undefined") {
    let fired = false;
    const trigger = () => {
      if (fired) return;
      fired = true;
      tryEnterFullscreen();
      document.removeEventListener("click", trigger, true);
      document.removeEventListener("touchend", trigger, true);
      document.removeEventListener("keydown", trigger, true);
    };
    document.addEventListener("click", trigger, true);
    document.addEventListener("touchend", trigger, true);
    document.addEventListener("keydown", trigger, true);
  }
}
