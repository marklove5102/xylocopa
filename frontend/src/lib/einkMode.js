// E-ink mode toggle.
//
// Auto-detection (UA sniff + @media (update: slow)) is unreliable —
// devices like Bigme ship Chromium that reports a generic Android Chrome
// UA and doesn't honor the standard e-ink media features. So this is a
// manually-toggled mode in Settings > Display.
//
// When on, adds `eink` class to <html>. CSS in index.css under `html.eink`
// swaps tokens to pure black/white, kills animations / transitions /
// shadows / blurs, and replaces shimmer skeletons with static blocks.

const STORAGE_KEY = "xy:eink-mode";

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
}

export function applyEinkMode(on) {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("eink", !!on);
  // Defensive: pause any auto-playing media so it doesn't trigger
  // continuous e-ink repaints. einkbro does this via a JS injection.
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
  applyEinkMode(getEinkMode());
}
