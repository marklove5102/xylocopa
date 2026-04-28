import { useState, useEffect, useRef } from "react";
import { updateBookmark } from "../lib/api";
import { useToast } from "../contexts/ToastContext";

/**
 * Floating prompt that appears after a successful bookmark POST.
 *
 * Two-stage:
 *   1. Compact pill (toast-style, top-right on desktop / top-center on mobile)
 *      auto-dismisses after `idleTimeoutMs` if the user doesn't expand.
 *   2. On tap → expands to a small card with textarea + Save/Skip.
 *
 * Positioning mirrors ToastContext (`.toast-container .safe-area-toast`) so it
 * sits next to native toasts instead of clipping the chat header.
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
    <div className="bookmark-note-anchor safe-area-toast">
      {!expanded ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="bookmark-note-pill toast-enter pointer-events-auto inline-flex items-center gap-2"
        >
          <svg className="w-4 h-4 text-amber-500 shrink-0" fill="currentColor" viewBox="0 0 24 24">
            <path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
          </svg>
          <span className="text-amber-700 dark:text-amber-300 font-semibold text-[13px]">Bookmarked</span>
          <span className="text-amber-600/80 dark:text-amber-400/85 text-[13px]">· Add note</span>
          <span
            role="button"
            tabIndex={-1}
            onClick={(e) => { e.stopPropagation(); skip(); }}
            className="text-amber-600/60 dark:text-amber-400/60 hover:text-amber-700 dark:hover:text-amber-300 ml-1 text-base leading-none"
            title="Dismiss"
          >
            ×
          </span>
        </button>
      ) : (
        <div className="bookmark-note-card toast-enter pointer-events-auto">
          <div className="flex items-center justify-between gap-2 mb-2">
            <p className="text-[13px] font-semibold text-label flex items-center gap-1.5">
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
      <style>{`
        .bookmark-note-anchor {
          position: fixed;
          z-index: 9998;
          pointer-events: none;
          left: 50%;
          transform: translateX(-50%);
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 8px;
        }
        @media (min-width: 640px) {
          .bookmark-note-anchor {
            left: auto;
            right: 16px;
            transform: none;
            align-items: flex-end;
          }
        }
        .bookmark-note-pill {
          background: rgba(255, 248, 230, 0.96);
          backdrop-filter: blur(12px);
          -webkit-backdrop-filter: blur(12px);
          border: 0.5px solid rgba(245, 158, 11, 0.35);
          border-radius: 14px;
          padding: 10px 14px;
          max-width: 300px;
          box-shadow: 0 2px 16px rgba(0,0,0,0.10), 0 0 0 0.5px rgba(0,0,0,0.04);
        }
        .dark .bookmark-note-pill {
          background: rgba(60, 45, 20, 0.92);
          border-color: rgba(245, 158, 11, 0.40);
          box-shadow: 0 2px 16px rgba(0,0,0,0.30), 0 0 0 0.5px rgba(255,255,255,0.06);
        }
        .bookmark-note-card {
          background: rgba(255,255,255,0.95);
          backdrop-filter: blur(12px);
          -webkit-backdrop-filter: blur(12px);
          border-radius: 14px;
          padding: 12px;
          width: min(360px, calc(100vw - 32px));
          box-shadow: 0 2px 16px rgba(0,0,0,0.12), 0 0 0 0.5px rgba(0,0,0,0.06);
        }
        .dark .bookmark-note-card {
          background: rgba(44,44,46,0.94);
          box-shadow: 0 2px 16px rgba(0,0,0,0.30), 0 0 0 0.5px rgba(255,255,255,0.08);
        }
      `}</style>
    </div>
  );
}
