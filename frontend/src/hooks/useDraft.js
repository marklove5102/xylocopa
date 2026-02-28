import { useState, useCallback } from "react";

/**
 * Persist a draft value in localStorage across navigation and refresh.
 * Returns [value, setValue, clearDraft].
 * setValue auto-syncs to localStorage on every call.
 * clearDraft removes the key (call after successful submission).
 */
export default function useDraft(key, initialValue = "") {
  const storageKey = key ? `draft:${key}` : null;
  // Use simple string mode only when initialValue is a string
  const stringMode = typeof initialValue === "string";

  const [value, _setValue] = useState(() => {
    if (!storageKey) return initialValue;
    try {
      const stored = localStorage.getItem(storageKey);
      if (stored !== null) {
        return stringMode ? stored : JSON.parse(stored);
      }
    } catch { /* ignore */ }
    return initialValue;
  });

  const setValue = useCallback((v) => {
    _setValue((prev) => {
      const next = typeof v === "function" ? v(prev) : v;
      if (storageKey) {
        try {
          if (stringMode) {
            if (next) localStorage.setItem(storageKey, next);
            else localStorage.removeItem(storageKey);
          } else {
            localStorage.setItem(storageKey, JSON.stringify(next));
          }
        } catch { /* ignore */ }
      }
      return next;
    });
  }, [storageKey, stringMode]);

  const clearDraft = useCallback(() => {
    if (storageKey) {
      try { localStorage.removeItem(storageKey); } catch { /* ignore */ }
    }
  }, [storageKey]);

  return [value, setValue, clearDraft];
}
