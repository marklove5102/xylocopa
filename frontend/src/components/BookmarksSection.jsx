import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import FluentEmoji from "./FluentEmoji";
import { relativeTime } from "../lib/formatters";
import { updateBookmark } from "../lib/api";
import { useToast } from "../contexts/ToastContext";

// Map backend `kind` → fallback emoji when AI summary_emoji is missing.
const KIND_FALLBACK_EMOJI = {
  message: "💬",
  image: "🖼️",
  file: "📄",
};

function pickEmoji(item) {
  if (item.summary_emoji && item.summary_emoji.trim()) return item.summary_emoji;
  return KIND_FALLBACK_EMOJI[item.kind] || "💬";
}

function BookmarkRow({ projectName, item, onOpen, onDelete, onRestore, onPatched }) {
  const isFile = item.kind === "file";
  const [locallyRemoved, setLocallyRemoved] = useState(false);
  const meta = item.created_at ? relativeTime(item.created_at) : "";

  // Editing state for the top text (the user-editable "title" — backed by user_note).
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const taRef = useRef(null);
  const toast = useToast();

  const topText =
    item.body || (item.summary === null ? "Summarizing…" : "(no summary)");

  useEffect(() => {
    if (!editing) return;
    const el = taRef.current;
    if (!el) return;
    el.focus();
    const len = el.value.length;
    el.setSelectionRange(len, len);
  }, [editing]);

  const startEditing = (e) => {
    e?.stopPropagation();
    if (locallyRemoved || editing) return;
    setDraft(item.body || "");
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditing(false);
    setDraft("");
  };

  const saveEditing = async () => {
    if (saving) return;
    const next = draft.trim();
    const original = (item.body || "").trim();
    if (next === original) {
      cancelEditing();
      return;
    }
    setSaving(true);
    try {
      const updated = await updateBookmark(projectName, item.message_id, next);
      onPatched?.(item.message_id, updated);
      toast.success(next ? "Bookmark title saved" : "Reverted to AI summary");
      setEditing(false);
    } catch (err) {
      toast.error(err?.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleRowClick = () => {
    if (editing) return;
    onOpen?.();
  };

  return (
    <div className="rounded-2xl bg-surface shadow-card overflow-hidden">
      <div
        role={editing ? undefined : "button"}
        tabIndex={editing ? -1 : 0}
        onClick={handleRowClick}
        onKeyDown={(e) => {
          if (editing) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onOpen?.();
          }
        }}
        style={{ WebkitTouchCallout: "none", WebkitTapHighlightColor: "transparent" }}
        className={`w-full text-left transition-[background-color] duration-200 ${
          editing
            ? ""
            : "active:bg-input hover:bg-input/40 cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
        }`}
      >
        <div className={`flex items-start gap-3 px-5 ${editing ? "py-3" : "py-3 min-h-[68px] items-center"}`}>
          <div className="shrink-0 w-7 h-7 flex items-center justify-center -ml-1 mt-0.5">
            <FluentEmoji char={pickEmoji(item)} size={22} />
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-3">
              {editing ? (
                <textarea
                  ref={taRef}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  onBlur={saveEditing}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      e.preventDefault();
                      cancelEditing();
                    } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault();
                      taRef.current?.blur();
                    }
                  }}
                  placeholder="Title — leave empty to use AI summary"
                  rows={Math.min(6, Math.max(2, draft.split("\n").length))}
                  disabled={saving}
                  className="flex-1 bg-input rounded-lg px-2.5 py-1.5 text-[13px] leading-snug font-medium text-heading resize-none outline-none focus:ring-2 focus:ring-cyan-500 disabled:opacity-60"
                />
              ) : (
                <p className="text-[13px] leading-snug font-medium text-heading truncate">
                  {topText}
                </p>
              )}
              <span className="text-[11px] text-faint shrink-0 mt-0.5">{meta}</span>
            </div>
            <p
              className={`text-xs mt-0.5 break-words ${
                isFile ? "font-mono text-dim" : "text-dim"
              }`}
            >
              {item.title || "(untitled)"}
            </p>
          </div>

          <div className="shrink-0 self-center flex items-center gap-0.5">
            {!editing && !locallyRemoved && (
              <button
                type="button"
                onClick={startEditing}
                title="Edit title"
                aria-label="Edit bookmark title"
                className="p-1 rounded-md text-faint hover:text-heading hover:bg-input transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536M9 13l6.586-6.586a2 2 0 112.828 2.828L11.828 15.828a2 2 0 01-1.414.586H8v-2.414c0-.53.21-1.04.586-1.414z" />
                </svg>
              </button>
            )}

            {typeof onDelete === "function" && (
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => {
                  e.stopPropagation();
                  if (locallyRemoved) {
                    setLocallyRemoved(false);
                    onRestore?.(item.message_id);
                  } else {
                    setLocallyRemoved(true);
                    onDelete(item.message_id);
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.stopPropagation();
                    if (locallyRemoved) {
                      setLocallyRemoved(false);
                      onRestore?.(item.message_id);
                    } else {
                      setLocallyRemoved(true);
                      onDelete(item.message_id);
                    }
                  }
                }}
                title={locallyRemoved ? "Re-bookmark" : "Remove bookmark"}
                className={`p-1 rounded-md transition-colors cursor-pointer ${
                  locallyRemoved
                    ? "text-faint hover:text-amber-500 hover:bg-amber-500/10"
                    : "text-amber-500 hover:bg-amber-500/15"
                }`}
              >
                <svg className="w-4 h-4" fill={locallyRemoved ? "none" : "currentColor"} stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
                </svg>
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function BookmarksSection({ projectName, items, onDelete, onRestore, onPatched }) {
  const navigate = useNavigate();
  const bookmarks = items || [];

  const handleOpen = (item) => {
    if (item?.agent_id && item?.message_id) {
      navigate(`/agents/${item.agent_id}?focus=${encodeURIComponent(item.message_id)}`);
    }
  };

  if (!bookmarks.length) {
    return (
      <div>
        <h2 className="text-sm font-semibold text-label uppercase tracking-wider px-1 mb-3">
          Bookmarks
        </h2>
        <div className="rounded-2xl bg-surface shadow-card py-10 text-center">
          <div className="mb-2 opacity-70">
            <FluentEmoji char="📌" size={28} />
          </div>
          <p className="text-sm text-dim">No bookmarks yet</p>
          <p className="text-xs text-faint mt-1">Double-tap any message to save it</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h2 className="text-sm font-semibold text-label uppercase tracking-wider px-1 mb-3">
        Bookmarks
      </h2>
      <div className="space-y-2">
        {bookmarks.map((item) => (
          <BookmarkRow
            key={item.message_id}
            projectName={projectName}
            item={item}
            onOpen={() => handleOpen(item)}
            onDelete={onDelete}
            onRestore={onRestore}
            onPatched={onPatched}
          />
        ))}
      </div>
    </div>
  );
}
