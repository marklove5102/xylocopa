import { useState } from "react";
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

function BookmarkRow({ item, onClick, onDelete, onRestore }) {
  const isFile = item.kind === "file";
  const isImage = item.kind === "image";
  const [locallyRemoved, setLocallyRemoved] = useState(false);
  const meta = item.created_at ? relativeTime(item.created_at) : "";

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
            {/* TODO: render thumbnail when backend exposes a served URL for media[0].path */}
            <FluentEmoji char={pickEmoji(item)} size={22} />
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-3">
              <p className="text-[15px] leading-snug truncate font-medium text-heading">
                {item.body || (item.summary === null ? "Summarizing…" : "(no summary)")}
              </p>
              <span className="text-[11px] text-faint shrink-0 mt-0.5">{meta}</span>
            </div>
            <p className={`text-xs truncate mt-0.5 ${isFile ? "font-mono text-dim" : "text-dim"}`}>
              {item.title || "(untitled)"}
            </p>
          </div>

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
    </div>
  );
}

export default function BookmarksSection({ projectName, items, onDelete, onRestore }) {
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
