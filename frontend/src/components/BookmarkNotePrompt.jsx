import { useState, useEffect, useRef } from "react";
import { updateBookmark } from "../lib/api";
import { useToast } from "../contexts/ToastContext";

/**
 * Floating prompt that appears after a successful bookmark POST. Lets the
 * user type a quick note (or skip). Auto-dismisses after `idleTimeoutMs`
 * unless the user interacts.
 *
 * Props:
 *   project       — project name (required for PATCH)
 *   messageId     — bookmark target id (null = closed)
 *   onClose()     — called when prompt should disappear (saved or skipped)
 *   onSaved(note) — optional, fires after a successful PATCH so callers can
 *                   refresh local state (e.g. flip filled icon)
 */
export default function BookmarkNotePrompt({ project, messageId, onClose, onSaved }) {
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [interacted, setInteracted] = useState(false);
  const taRef = useRef(null);
  const toast = useToast();

  // Reset draft + auto-focus textarea on each new prompt
  useEffect(() => {
    if (!messageId) return;
    setDraft("");
    setInteracted(false);
    const t = setTimeout(() => taRef.current?.focus(), 50);
    return () => clearTimeout(t);
  }, [messageId]);

  // Auto-dismiss after idle period (only while user hasn't interacted)
  useEffect(() => {
    if (!messageId || interacted) return;
    const t = setTimeout(() => onClose?.(), 4500);
    return () => clearTimeout(t);
  }, [messageId, interacted, onClose]);

  if (!messageId) return null;

  const save = async () => {
    if (saving) return;
    const next = draft.trim();
    if (!next) {
      onClose?.();
      return;
    }
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
    <div
      className="fixed inset-0 z-[9998] flex items-start justify-center pt-20 px-4 pointer-events-none"
      onPointerDown={(e) => { if (e.target === e.currentTarget) skip(); }}
    >
      <div
        className="pointer-events-auto w-full max-w-md rounded-2xl bg-surface shadow-xl border border-divider p-3 animate-[toast-slide-in_0.25s_ease-out]"
        onPointerDown={() => setInteracted(true)}
      >
        <div className="flex items-center justify-between gap-2 mb-2">
          <p className="text-xs font-semibold text-label uppercase tracking-wider flex items-center gap-1.5">
            <svg className="w-3.5 h-3.5 text-amber-500" fill="currentColor" viewBox="0 0 24 24">
              <path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
            </svg>
            Bookmarked — add a note?
          </p>
          <button type="button" onClick={skip} className="text-xs text-faint hover:text-dim">
            Skip
          </button>
        </div>
        <textarea
          ref={taRef}
          value={draft}
          onChange={(e) => { setDraft(e.target.value); setInteracted(true); }}
          onKeyDown={(e) => {
            if (e.key === "Escape") { skip(); }
            if ((e.key === "Enter") && (e.metaKey || e.ctrlKey)) save();
          }}
          placeholder="Why this one? (⌘+Enter to save, Esc to skip)"
          rows={3}
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
            {saving ? "Saving…" : "Save note"}
          </button>
        </div>
      </div>
    </div>
  );
}
