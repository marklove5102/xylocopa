import { useState, useEffect, useLayoutEffect, useRef, useMemo } from "react";
import { createPortal } from "react-dom";

import { fetchSkills } from "../lib/api";

const LRU_KEY = "xy.skillUsage";
const LRU_MAX = 20;

function readLRU() {
  try {
    const raw = localStorage.getItem(LRU_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function bumpLRU(name) {
  const lru = readLRU();
  lru[name] = Date.now();
  const entries = Object.entries(lru).sort((a, b) => b[1] - a[1]).slice(0, LRU_MAX);
  try {
    localStorage.setItem(LRU_KEY, JSON.stringify(Object.fromEntries(entries)));
  } catch { /* quota — ignore */ }
}

function sourceLabel(source) {
  if (source === "personal") return "personal";
  if (source === "project") return "project";
  if (source === "bundled") return "bundled";
  if (source && source.startsWith("plugin:")) return source.slice(7);
  return source || "";
}

function sourceColor(source) {
  if (source === "personal") return "text-cyan-400";
  if (source === "project") return "text-emerald-400";
  if (source === "bundled") return "text-faint";
  if (source && source.startsWith("plugin:")) return "text-purple-400";
  return "text-faint";
}

export default function SkillPickerPanel({ project, onSelect, onClose }) {
  const anchorRef = useRef(null);
  const pickerRef = useRef(null);
  const inputRef = useRef(null);
  const [pos, setPos] = useState(null);
  const [skills, setSkills] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [activeIdx, setActiveIdx] = useState(0);

  // Load skills
  useEffect(() => {
    let cancelled = false;
    fetchSkills(project)
      .then((data) => {
        if (cancelled) return;
        setSkills(Array.isArray(data?.skills) ? data.skills : []);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || "failed to load skills");
      });
    return () => { cancelled = true; };
  }, [project]);

  // Position above anchor (matches SendLaterPicker behavior)
  useLayoutEffect(() => {
    if (!anchorRef.current) return;
    const rect = anchorRef.current.getBoundingClientRect();
    const pickerW = 320;
    const pickerH = 420;
    let right = window.innerWidth - rect.right;
    if (rect.right - pickerW < 8) right = window.innerWidth - pickerW - 8;
    if (right < 8) right = 8;
    const spaceAbove = rect.top;
    if (spaceAbove < pickerH + 8) {
      setPos({ top: rect.bottom + 4, right });
    } else {
      setPos({ bottom: window.innerHeight - rect.top + 4, right });
    }
  }, []);

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target)) onClose();
    };
    document.addEventListener("mousedown", handler);
    document.addEventListener("touchstart", handler);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("touchstart", handler);
    };
  }, [onClose]);

  // Auto-focus search input
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const lru = useMemo(() => readLRU(), []);

  const filtered = useMemo(() => {
    if (!skills) return [];
    const q = query.trim().toLowerCase();
    const matches = q
      ? skills.filter((s) =>
          s.name?.toLowerCase().includes(q) ||
          s.description?.toLowerCase().includes(q))
      : skills.slice();
    matches.sort((a, b) => {
      const la = lru[a.name] || 0;
      const lb = lru[b.name] || 0;
      if (la !== lb) return lb - la;
      return (a.name || "").localeCompare(b.name || "");
    });
    return matches;
  }, [skills, query, lru]);

  // Reset highlight when filter changes
  useEffect(() => { setActiveIdx(0); }, [query, skills]);

  const handlePick = (skill) => {
    if (!skill) return;
    bumpLRU(skill.name);
    onSelect(`/${skill.name}`);
  };

  const handleKeyDown = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      handlePick(filtered[activeIdx]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    }
  };

  const posStyle = pos
    ? { position: "fixed", ...pos }
    : { visibility: "hidden", position: "fixed" };

  const picker = (
    <div
      ref={pickerRef}
      data-card
      className="w-[320px] bg-surface border border-divider rounded-2xl shadow-xl overflow-hidden z-[9999] flex flex-col"
      style={posStyle}
    >
      <div className="px-4 py-2.5 flex items-center justify-between border-b border-divider">
        <span className="text-sm font-semibold text-heading">Skills</span>
        <button type="button" onClick={onClose}
          className="w-6 h-6 rounded-full bg-elevated flex items-center justify-center text-dim hover:text-heading transition-colors">
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="px-3 pt-2.5 pb-1.5 border-b border-divider">
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Search skills..."
          className="w-full h-8 rounded-lg bg-input px-3 text-sm text-heading placeholder-hint focus:outline-none focus:ring-1 focus:ring-cyan-500/40"
        />
      </div>

      <div className="max-h-[320px] overflow-y-auto py-1">
        {error && (
          <div className="px-4 py-3 text-xs text-red-400">{error}</div>
        )}
        {!error && skills === null && (
          <div className="px-4 py-3 text-xs text-faint">Loading...</div>
        )}
        {!error && skills && filtered.length === 0 && (
          <div className="px-4 py-3 text-xs text-faint">No skills found</div>
        )}
        {!error && filtered.map((skill, i) => (
          <button
            key={`${skill.source}:${skill.name}`}
            type="button"
            onClick={() => handlePick(skill)}
            onMouseEnter={() => setActiveIdx(i)}
            className={`w-full text-left px-4 py-2 transition-colors flex flex-col gap-0.5 ${
              i === activeIdx ? "bg-input" : "hover:bg-input"
            }`}
          >
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-sm font-medium text-heading truncate">/{skill.name}</span>
              <span className={`text-[10px] font-medium uppercase tracking-wide shrink-0 ${sourceColor(skill.source)}`}>
                {sourceLabel(skill.source)}
              </span>
            </div>
            {skill.description && (
              <span className="text-xs text-dim line-clamp-2">{skill.description}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <>
      <span ref={anchorRef} className="absolute bottom-0 right-0 w-0 h-0 pointer-events-none" />
      {createPortal(picker, document.body)}
    </>
  );
}
