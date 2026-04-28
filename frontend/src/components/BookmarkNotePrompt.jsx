import { useState, useEffect, useRef } from "react";
import { updateBookmark } from "../lib/api";
import { useToast } from "../contexts/ToastContext";

/**
 * Floating prompt that appears after a successful bookmark POST.
 *
 * Two-stage:
 *   1. Compact pill "📑 Bookmarked · Add note" at the top of the viewport.
 *      Auto-dismisses after `idleTimeoutMs` if the user doesn't expand.
 *   2. On tap → expands to a small card with textarea + Save/Skip.
 *
 * Props:
 *   project       — project name (required for PATCH)
 *   messageId     — bookmark target id (null = closed)
 *   onClose()     — called when prompt should disappear (saved or skipped)
 *   onSaved(note) — optional, fires after a successful PATCH
 */
export default function BookmarkNotePrompt({ project, messageId, onClose, onSaved }) {
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const taRef = useRef(null);
  const toast = useToast();

  // Reset on each new prompt
  useEffect(() => {
    if (!messageId) return;
    setDraft("");
    setExpanded(false);
    setSaving(false);
  }, [messageId]);

  // Focus textarea right after expansion
  useEffect(() => {
    if (!expanded) return;
    const t = setTimeout(() => taRef.current?.focus(), 50);
    return () => clearTimeout(t);
  }, [expanded]);

  // Auto-dismiss only while still collapsed
  useEffect(() => {
    if (!messageId || expanded) return;
    const t = setTimeout(() => onClose?.(), 4500);
    return () => clearTimeout(t);
  }, [messageId, expanded, onClose]);

  if (!messageId) return null;

  const save = async () => {
    if (saving) return;
    const next = draft.trim();
    if (!next) { onClose?.(); return; }
    setSaving(true);
    try {
      await updateBookmark(project, messageId, next);
      toast.success("Note saved");
      onSaved?.(next);
      onClose?.();
    } catch (err) {
      toast.error(err?.message || "Failed to save note");
      setSaving(false);
    }
  };

  const skip = () => onClose?.();

  return (
    <div className="fixed inset-x-0 top-3 z-[9998] flex justify-center px-4 pointer-events-none">
      {!expanded ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="pointer-events-auto inline-flex items-center gap-2 rounded-full bg-amber-500/[0.12] dark:bg-amber-500/[0.18] border border-amber-500/30 backdrop-blur-md px-3 py-1.5 text-xs shadow-lg animate-[toast-slide-in_0.25s_ease-out]"
        >
          <svg className="w-3.5 h-3.5 text-amber-500" fill="currentColor" viewBox="0 0 24 24">
            <path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
          </svg>
          <span className="text-amber-700 dark:text-amber-300 font-medium">Bookmarked</span>
          <span className="text-amber-600/70 dark:text-amber-400/80">· Add note</span>
          <span
            role="button"
            tabIndex={-1}
            onClick={(e) => { e.stopPropagation(); skip(); }}
            className="text-amber-600/60 dark:text-amber-400/60 hover:text-amber-700 dark:hover:text-amber-300 ml-1 px-1"
            title="Dismiss"
          >
            ×
          </span>
        </button>
      ) : (
        <div className="pointer-events-auto w-full max-w-sm rounded-2xl bg-surface shadow-xl border border-divider p-3 animate-[toast-slide-in_0.25s_ease-out]">
          <div className="flex items-center justify-between gap-2 mb-2">
            <p className="text-xs font-semibold text-label uppercase tracking-wider flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-amber-500" fill="currentColor" viewBox="0 0 24 24">
                <path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
              </svg>
              Add a note
            </p>
            <button type="button" onClick={skip} className="text-xs text-faint hover:text-dim">
              Skip
            </button>
          </div>
          <textarea
            ref={taRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") { skip(); }
              if ((e.key === "Enter") && (e.metaKey || e.ctrlKey)) save();
            }}
            placeholder="Why this one? (⌘+Enter saves, Esc skips)"
            rows={2}
            className="w-full rounded-xl bg-amber-500/[0.06] border border-amber-500/25 px-3 py-2 text-sm text-body placeholder-faint resize-y focus:outline-none focus:border-amber-500/50"
          />
          <div className="flex items-center justify-end gap-2 mt-2">
            <button
              type="button"
              onClick={skip}
              disabled={saving}
              className="text-xs px-3 py-1 rounded-full text-dim hover:bg-input transition-colors"
            >
              Skip
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saving || !draft.trim()}
              className="text-xs px-3 py-1 rounded-full bg-amber-500/15 text-amber-600 dark:text-amber-400 hover:bg-amber-500/25 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
