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
          className="bookmark-note-pill toast-enter pointer-events-auto inline-flex items-center gap-2 whitespace-nowrap"
        >
          <svg className="w-[18px] h-[18px] text-amber-500 shrink-0" fill="currentColor" viewBox="0 0 24 24">
            <path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
          </svg>
          <span className="bookmark-note-text">Bookmarked · Add note</span>
          <span
            role="button"
            tabIndex={-1}
            onClick={(e) => { e.stopPropagation(); skip(); }}
            className="bookmark-note-dismiss"
            title="Dismiss"
          >
            ×
          </span>
        </button>
      ) : (
        <div className="bookmark-note-card toast-enter pointer-events-auto">
          <div className="flex items-center justify-between gap-2 mb-2">
            <p className="bookmark-note-text font-semibold flex items-center gap-1.5">
              <svg className="w-[18px] h-[18px] text-amber-500" fill="currentColor" viewBox="0 0 24 24">
                <path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
              </svg>
              Add a note
            </p>
            <button type="button" onClick={skip} className="bookmark-note-skip">
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
            className="bookmark-note-textarea"
          />
          <div className="flex items-center justify-end gap-2 mt-2">
            <button
              type="button"
              onClick={skip}
              disabled={saving}
              className="bookmark-note-btn-skip"
            >
              Skip
            </button>
            <button
              type="button"
              onClick={save}
              disabled={saving || !draft.trim()}
              className="bookmark-note-btn-save"
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
        /* Match ToastContext.jsx pill chrome — white, blur, 14px, soft shadow */
        .bookmark-note-pill,
        .bookmark-note-card {
          background: rgba(255, 255, 255, 0.95);
          backdrop-filter: blur(12px);
          -webkit-backdrop-filter: blur(12px);
          border-radius: 14px;
          box-shadow: 0 2px 16px rgba(0,0,0,0.12), 0 0 0 0.5px rgba(0,0,0,0.06);
        }
        .bookmark-note-pill {
          padding: 10px 14px;
          transition: transform 0.15s ease, box-shadow 0.15s ease;
        }
        .bookmark-note-pill:hover {
          transform: translateY(-1px);
        }
        .bookmark-note-card {
          padding: 12px;
          width: min(360px, calc(100vw - 32px));
        }
        .dark .bookmark-note-pill,
        .dark .bookmark-note-card {
          background: rgba(44, 44, 46, 0.92);
          box-shadow: 0 2px 16px rgba(0,0,0,0.30), 0 0 0 0.5px rgba(255,255,255,0.08);
        }
        .bookmark-note-text {
          color: #1c1c1e;
          font-size: 13px;
          font-weight: 500;
          line-height: 1.3;
        }
        .dark .bookmark-note-text { color: #f5f5f7; }
        .bookmark-note-dismiss {
          margin-left: 4px;
          color: rgba(28, 28, 30, 0.4);
          font-size: 16px;
          line-height: 1;
          padding: 0 4px;
          cursor: pointer;
          transition: color 0.15s;
        }
        .bookmark-note-dismiss:hover { color: rgba(28, 28, 30, 0.85); }
        .dark .bookmark-note-dismiss { color: rgba(245, 245, 247, 0.45); }
        .dark .bookmark-note-dismiss:hover { color: rgba(245, 245, 247, 0.95); }
        .bookmark-note-skip {
          font-size: 12px;
          color: rgba(28, 28, 30, 0.5);
          transition: color 0.15s;
        }
        .bookmark-note-skip:hover { color: rgba(28, 28, 30, 0.85); }
        .dark .bookmark-note-skip { color: rgba(245, 245, 247, 0.5); }
        .dark .bookmark-note-skip:hover { color: rgba(245, 245, 247, 0.9); }
        .bookmark-note-textarea {
          width: 100%;
          border-radius: 10px;
          background: rgba(0, 0, 0, 0.03);
          border: 0.5px solid rgba(0, 0, 0, 0.08);
          padding: 8px 10px;
          font-size: 13px;
          color: #1c1c1e;
          resize: vertical;
          outline: none;
          transition: border-color 0.15s;
        }
        .bookmark-note-textarea:focus { border-color: rgba(0, 0, 0, 0.20); }
        .bookmark-note-textarea::placeholder { color: rgba(28, 28, 30, 0.35); }
        .dark .bookmark-note-textarea {
          background: rgba(255, 255, 255, 0.04);
          border-color: rgba(255, 255, 255, 0.10);
          color: #f5f5f7;
        }
        .dark .bookmark-note-textarea:focus { border-color: rgba(255, 255, 255, 0.25); }
        .dark .bookmark-note-textarea::placeholder { color: rgba(245, 245, 247, 0.35); }
        .bookmark-note-btn-skip {
          font-size: 12px;
          padding: 4px 12px;
          border-radius: 9999px;
          color: rgba(28, 28, 30, 0.55);
          transition: background-color 0.15s;
        }
        .bookmark-note-btn-skip:hover { background-color: rgba(0, 0, 0, 0.05); }
        .dark .bookmark-note-btn-skip { color: rgba(245, 245, 247, 0.55); }
        .dark .bookmark-note-btn-skip:hover { background-color: rgba(255, 255, 255, 0.06); }
        .bookmark-note-btn-save {
          font-size: 12px;
          padding: 4px 12px;
          border-radius: 9999px;
          background-color: rgba(28, 28, 30, 0.85);
          color: #fff;
          font-weight: 500;
          transition: background-color 0.15s, opacity 0.15s;
        }
        .bookmark-note-btn-save:hover:not(:disabled) { background-color: #1c1c1e; }
        .bookmark-note-btn-save:disabled { opacity: 0.4; cursor: not-allowed; }
        .dark .bookmark-note-btn-save { background-color: rgba(245, 245, 247, 0.92); color: #1c1c1e; }
        .dark .bookmark-note-btn-save:hover:not(:disabled) { background-color: #f5f5f7; }
      `}</style>
    </div>
  );
}
