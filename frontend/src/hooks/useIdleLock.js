import { useEffect, useRef, useCallback } from "react";
import { clearAuthToken } from "../lib/api";

const IDLE_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes
const ACTIVITY_KEY = "cc-last-activity";

/** Record user activity timestamp in localStorage (shared across tabs). */
function touch() {
  localStorage.setItem(ACTIVITY_KEY, String(Date.now()));
}

/** Get milliseconds since last recorded activity. */
function idleMs() {
  const last = Number(localStorage.getItem(ACTIVITY_KEY) || 0);
  return last ? Date.now() - last : 0;
}

/**
 * Hook that monitors user activity and locks (clears token + redirects
 * to /login) after IDLE_TIMEOUT_MS of inactivity.
 *
 * Listens to pointer, keyboard, scroll, and touch events. Activity
 * is shared across tabs via localStorage.
 */
export default function useIdleLock(navigate) {
  const timerRef = useRef(null);

  const lock = useCallback(() => {
    clearAuthToken();
    localStorage.removeItem(ACTIVITY_KEY);
    navigate("/login", { replace: true });
  }, [navigate]);

  const resetTimer = useCallback(() => {
    touch();
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(lock, IDLE_TIMEOUT_MS);
  }, [lock]);

  useEffect(() => {
    // On mount, check if already idle too long
    if (idleMs() > IDLE_TIMEOUT_MS) {
      lock();
      return;
    }

    // Initial touch + timer
    resetTimer();

    // User activity events (passive to avoid perf impact)
    const events = ["pointerdown", "keydown", "scroll", "touchstart"];
    const handler = () => resetTimer();
    for (const e of events) {
      window.addEventListener(e, handler, { passive: true });
    }

    // Listen for activity changes from other tabs
    const storageHandler = (e) => {
      if (e.key === ACTIVITY_KEY && e.newValue) {
        resetTimer();
      }
    };
    window.addEventListener("storage", storageHandler);

    return () => {
      for (const e of events) {
        window.removeEventListener(e, handler);
      }
      window.removeEventListener("storage", storageHandler);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [resetTimer, lock]);
}
