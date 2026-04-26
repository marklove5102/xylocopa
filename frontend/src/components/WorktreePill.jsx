import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

export default function WorktreePill({ name, padY = "py-px" }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const pillRef = useRef(null);
  const popRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (pillRef.current?.contains(e.target)) return;
      if (popRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", handler);
    return () => document.removeEventListener("pointerdown", handler);
  }, [open]);

  const toggle = (e) => {
    e.stopPropagation();
    if (!open) {
      const rect = pillRef.current?.getBoundingClientRect();
      if (rect) setPos({ top: rect.bottom, left: rect.left + rect.width / 2 });
    }
    setOpen((v) => !v);
  };

  const display = name || "(unnamed)";

  return (
    <span className="shrink-0 inline-flex items-center">
      <span
        ref={pillRef}
        role="button"
        tabIndex={0}
        onClick={toggle}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(e); } }}
        className={`text-[10px] font-medium px-1.5 ${padY} rounded-full bg-purple-500/15 text-purple-500 dark:text-purple-400 inline-flex items-center cursor-pointer hover:bg-purple-500/25 transition-colors`}
      >
        <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 3v12M18 9a3 3 0 100-6 3 3 0 000 6zm0 0v3a3 3 0 01-3 3H9m-3 0a3 3 0 100 6 3 3 0 000-6z" />
        </svg>
      </span>
      {open && pos && createPortal(
        <div
          ref={popRef}
          className="fixed z-[61] px-2 py-1.5 rounded-lg bg-surface border border-divider shadow-lg flex items-center gap-2 whitespace-nowrap"
          style={{ top: pos.top, left: pos.left, transform: "translateX(-50%)" }}
        >
          <span className="text-[11px] text-dim">worktree:</span>
          <span className="text-[11px] font-mono text-body select-all">{display}</span>
          {name && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                navigator.clipboard.writeText(name).catch(() => {});
                setOpen(false);
              }}
              className="text-[10px] text-cyan-500 dark:text-cyan-400 hover:underline"
            >
              Copy
            </button>
          )}
        </div>,
        document.body
      )}
    </span>
  );
}
