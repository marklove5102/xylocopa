import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import FluentEmoji from "./FluentEmoji";
import { relativeTime } from "../lib/formatters";

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

function pickAgentLabel(item) {
  // Prefer human-readable agent name when present, else 8-char id slice.
  if (item.agent_name) return item.agent_name.length > 22 ? item.agent_name.slice(0, 22) + "…" : item.agent_name;
  return item.agent_id ? `xy-${item.agent_id.slice(0, 8)}` : "";
}

function BookmarkRow({ item, onClick, onUpdateNote, onDelete, onRestore }) {
  const isFile = item.kind === "file";
  const isImage = item.kind === "image";
  const [noteOpen, setNoteOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draftNote, setDraftNote] = useState(item.user_note || "");
  const [locallyRemoved, setLocallyRemoved] = useState(false);
  const taRef = useRef(null);

  useEffect(() => {
    if (editing && taRef.current) {
      taRef.current.focus();
      taRef.current.setSelectionRange(taRef.current.value.length, taRef.current.value.length);
    }
  }, [editing]);

  useEffect(() => {
    setDraftNote(item.user_note || "");
  }, [item.user_note]);

  const hasUserNote = !!(item.user_note && item.user_note.trim());
  const meta = item.created_at ? relativeTime(item.created_at) : "";

  const saveNote = async () => {
    const next = draftNote.trim();
    if (next === (item.user_note || "")) {
      setEditing(false);
      return;
    }
    if (typeof onUpdateNote === "function") {
      await onUpdateNote(item.message_id, next || null);
    }
    setEditing(false);
    if (next) setNoteOpen(true);
  };

  return (
    <div className="rounded-2xl bg-surface shadow-card overflow-hidden">
      <button
        type="button"
        onClick={onClick}
        style={{ WebkitTouchCallout: "none", WebkitTapHighlightColor: "transparent" }}
        className="w-full text-left transition-[background-color] duration-200 active:bg-input hover:bg-input/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
      >
        <div className="flex items-center gap-3 px-5 h-[68px]">
          <div className="shrink-0 w-7 h-7 flex items-center justify-center -ml-1">
            {isImage && item.media?.[0]?.path ? (
              // Future: replace with served thumbnail URL when backend exposes one.
              // For now, fall back to emoji to avoid broken-image placeholders.
              <FluentEmoji char={pickEmoji(item)} size={22} />
            ) : (
              <FluentEmoji char={pickEmoji(item)} size={22} />
            )}
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-3">
              <h3 className={`text-[15px] leading-snug truncate ${isFile ? "font-mono text-body" : "font-medium text-heading"}`}>
                {item.title || "(untitled)"}
              </h3>
              <span className="text-[11px] text-faint shrink-0 mt-0.5">{meta}</span>
            </div>
            <p className="text-sm text-dim truncate mt-0.5">
              {item.body || (item.summary === null ? "Summarizing…" : "")}
            </p>
          </div>

          {hasUserNote && (
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => { e.stopPropagation(); setNoteOpen((v) => !v); }}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.stopPropagation(); setNoteOpen((v) => !v); } }}
              className={`shrink-0 self-center text-[10px] font-semibold px-1.5 py-px rounded-full transition-colors cursor-pointer ${
                noteOpen
                  ? "bg-amber-500/30 text-amber-700 dark:text-amber-300"
                  : "bg-amber-500/15 text-amber-500 dark:text-amber-400 hover:bg-amber-500/25"
              }`}
            >
              note
            </span>
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
              className={`shrink-0 self-center p-1 rounded-md transition-colors cursor-pointer ${
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
      </button>

      {(noteOpen || editing) && (
        <div className="px-5 pb-3 -mt-1 space-y-2">
          {editing ? (
            <textarea
              ref={taRef}
              value={draftNote}
              onChange={(e) => setDraftNote(e.target.value)}
              onBlur={saveNote}
              onKeyDown={(e) => {
                if (e.key === "Escape") { setDraftNote(item.user_note || ""); setEditing(false); }
                if ((e.key === "Enter") && (e.metaKey || e.ctrlKey)) saveNote();
              }}
              placeholder="Add a note…"
              rows={3}
              className="w-full rounded-xl bg-amber-500/[0.08] border border-amber-500/30 px-3 py-2 text-sm text-body placeholder-faint resize-y focus:outline-none focus:border-amber-500/50"
            />
          ) : (
            <div className="rounded-xl bg-amber-500/[0.08] border border-amber-500/20 px-3 py-2 text-sm text-body whitespace-pre-wrap">
              {item.user_note || "(empty note)"}
            </div>
          )}
          <div className="flex items-center gap-2 text-[11px]">
            <button
              type="button"
              onClick={() => setEditing((v) => !v)}
              className="text-cyan-600 dark:text-cyan-400 hover:underline"
            >
              {editing ? "Cancel" : hasUserNote ? "Edit note" : "Add note"}
            </button>
            {typeof onDelete === "function" && (
              <>
                <span className="text-faint">·</span>
                <button
                  type="button"
                  onClick={() => onDelete(item.message_id)}
                  className="text-red-500 hover:underline"
                >
                  Remove bookmark
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* Hidden editor trigger for rows without an existing note: click reveals editor without first opening pill */}
      {!hasUserNote && !editing && !noteOpen && false}
    </div>
  );
}

export default function BookmarksSection({ projectName, items, onUpdateNote, onDelete, onRestore }) {
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
          <p className="text-xs text-faint mt-1">Long-press any message to save it</p>
        </div>
      </div>
    );
  }

  const visible = bookmarks.slice(0, 6);
  const total = bookmarks.length;

  return (
    <div>
      <h2 className="text-sm font-semibold text-label uppercase tracking-wider px-1 mb-3">
        Bookmarks
      </h2>
      <div className="space-y-2">
        {visible.map((item) => (
          <BookmarkRow
            key={item.message_id}
            item={item}
            onClick={() => handleOpen(item)}
            onUpdateNote={onUpdateNote}
            onDelete={onDelete}
            onRestore={onRestore}
          />
        ))}
      </div>
      {total > visible.length && (
        <p className="text-xs text-faint pt-3 px-1">
          Showing 6 of {total} — open chat to see more
        </p>
      )}
    </div>
  );
}
