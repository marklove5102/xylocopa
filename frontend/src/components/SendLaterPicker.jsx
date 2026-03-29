import { useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback } from "react";
import { createPortal } from "react-dom";

const DAYS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

export default function SendLaterPicker({ onSelect, onClose, onClear, title = "Remind At" }) {
  const anchorRef = useRef(null);
  const pickerRef = useRef(null);
  const [pos, setPos] = useState(null);

  const now = useMemo(() => new Date(), []);
  const [viewYear, setViewYear] = useState(now.getFullYear());
  const [viewMonth, setViewMonth] = useState(now.getMonth());
  const [selectedDay, setSelectedDay] = useState(null); // { year, month, day }
  const [hour, setHour] = useState(9);
  const [minute, setMinute] = useState(0);

  // Position picker above anchor, respecting screen edges
  useLayoutEffect(() => {
    if (!anchorRef.current) return;
    const rect = anchorRef.current.getBoundingClientRect();
    const pickerW = 280;
    const pickerH = 420;
    let right = window.innerWidth - rect.right;
    if (rect.right - pickerW < 8) right = window.innerWidth - pickerW - 8;
    // If not enough space above, show below
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

  // Calendar grid for current view month
  const calendarDays = useMemo(() => {
    const firstDay = new Date(viewYear, viewMonth, 1).getDay();
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
    const cells = [];
    for (let i = 0; i < firstDay; i++) cells.push(null);
    for (let d = 1; d <= daysInMonth; d++) cells.push(d);
    return cells;
  }, [viewYear, viewMonth]);

  const isToday = useCallback((day) => {
    return day && viewYear === now.getFullYear() && viewMonth === now.getMonth() && day === now.getDate();
  }, [viewYear, viewMonth, now]);

  const isSelected = useCallback((day) => {
    if (!day || !selectedDay) return false;
    return selectedDay.year === viewYear && selectedDay.month === viewMonth && selectedDay.day === day;
  }, [selectedDay, viewYear, viewMonth]);

  const isPast = useCallback((day) => {
    if (!day) return false;
    const d = new Date(viewYear, viewMonth, day, 23, 59, 59);
    return d < now;
  }, [viewYear, viewMonth, now]);

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(y => y - 1); }
    else setViewMonth(m => m - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(y => y + 1); }
    else setViewMonth(m => m + 1);
  };

  const selectPreset = (date) => {
    onSelect(date.toISOString());
  };

  const handleToday = () => {
    const d = new Date();
    d.setHours(hour, minute, 0, 0);
    if (d <= new Date()) d.setHours(d.getHours() + 1, 0, 0, 0);
    selectPreset(d);
  };

  const handleEvening = () => {
    const d = new Date();
    d.setHours(20, 0, 0, 0);
    if (d <= new Date()) { d.setDate(d.getDate() + 1); }
    selectPreset(d);
  };

  const handleTomorrow = () => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    d.setHours(9, 0, 0, 0);
    selectPreset(d);
  };

  const handleDayClick = (day) => {
    if (!day || isPast(day)) return;
    setSelectedDay({ year: viewYear, month: viewMonth, day });
  };

  const handleConfirm = () => {
    if (!selectedDay) return;
    const d = new Date(selectedDay.year, selectedDay.month, selectedDay.day, hour, minute, 0, 0);
    if (d <= new Date()) return;
    onSelect(d.toISOString());
  };

  const cycleHour = (delta) => setHour(h => ((h + delta - 1 + 24) % 24) + 1);
  const cycleMinute = (delta) => setMinute(m => (m + delta + 60) % 60);

  const posStyle = pos
    ? { position: "fixed", ...pos }
    : { visibility: "hidden", position: "fixed" };

  const picker = (
    <div
      ref={pickerRef}
      data-card
      className="w-[280px] bg-surface border border-divider rounded-2xl shadow-xl overflow-hidden z-[9999]"
      style={posStyle}
    >
      {/* Header */}
      <div className="px-4 py-2.5 flex items-center justify-between border-b border-divider">
        <span className="text-sm font-semibold text-heading">{title}</span>
        <div className="flex items-center gap-2">
          {onClear && (
            <button type="button" onClick={() => { onClear(); onClose(); }}
              className="text-xs text-red-400 hover:text-red-300 font-medium">
              Clear
            </button>
          )}
          <button type="button" onClick={onClose}
            className="w-6 h-6 rounded-full bg-elevated flex items-center justify-center text-dim hover:text-heading">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      {/* Presets */}
      <div className="py-1 border-b border-divider">
        <button type="button" onClick={handleToday}
          className="w-full text-left px-4 py-2 text-sm text-body hover:bg-input transition-colors flex items-center gap-2.5">
          <svg className="w-4 h-4 text-amber-400 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
          </svg>
          Today
        </button>
        <button type="button" onClick={handleEvening}
          className="w-full text-left px-4 py-2 text-sm text-body hover:bg-input transition-colors flex items-center gap-2.5">
          <svg className="w-4 h-4 text-indigo-400 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
          </svg>
          This Evening
        </button>
        <button type="button" onClick={handleTomorrow}
          className="w-full text-left px-4 py-2 text-sm text-body hover:bg-input transition-colors flex items-center gap-2.5">
          <svg className="w-4 h-4 text-orange-400 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
          </svg>
          Tomorrow 9 AM
        </button>
      </div>

      {/* Calendar */}
      <div className="px-3 pt-3 pb-2">
        {/* Month nav */}
        <div className="flex items-center justify-between mb-2 px-1">
          <span className="text-xs font-semibold text-heading">
            {MONTHS[viewMonth]} {viewYear}
          </span>
          <div className="flex items-center gap-1">
            <button type="button" onClick={prevMonth}
              className="w-6 h-6 rounded-full hover:bg-input flex items-center justify-center text-dim hover:text-heading transition-colors">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <button type="button" onClick={nextMonth}
              className="w-6 h-6 rounded-full hover:bg-input flex items-center justify-center text-dim hover:text-heading transition-colors">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </button>
          </div>
        </div>

        {/* Day headers */}
        <div className="grid grid-cols-7 mb-1">
          {DAYS.map(d => (
            <div key={d} className="text-center text-[10px] font-medium text-faint py-0.5">{d}</div>
          ))}
        </div>

        {/* Day cells */}
        <div className="grid grid-cols-7">
          {calendarDays.map((day, i) => (
            <button
              key={i}
              type="button"
              disabled={!day || isPast(day)}
              onClick={() => handleDayClick(day)}
              className={`h-8 text-xs rounded-full flex items-center justify-center transition-colors ${
                !day ? ""
                  : isPast(day) ? "text-faint/30 cursor-not-allowed"
                  : isSelected(day) ? "bg-cyan-500 text-white font-semibold"
                  : isToday(day) ? "bg-cyan-500/15 text-cyan-400 font-semibold hover:bg-cyan-500/25"
                  : "text-body hover:bg-input"
              }`}
            >
              {day || ""}
            </button>
          ))}
        </div>
      </div>

      {/* Time + Confirm */}
      <div className="border-t border-divider px-4 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-1">
          <span className="text-xs text-dim mr-1">Time</span>
          <button type="button" onClick={() => cycleHour(-1)}
            className="w-5 h-5 rounded bg-input text-dim hover:text-heading flex items-center justify-center text-[10px] font-bold">-</button>
          <span className="text-sm font-semibold text-heading w-5 text-center">{hour}</span>
          <button type="button" onClick={() => cycleHour(1)}
            className="w-5 h-5 rounded bg-input text-dim hover:text-heading flex items-center justify-center text-[10px] font-bold">+</button>
          <span className="text-sm text-dim">:</span>
          <button type="button" onClick={() => cycleMinute(-5)}
            className="w-5 h-5 rounded bg-input text-dim hover:text-heading flex items-center justify-center text-[10px] font-bold">-</button>
          <span className="text-sm font-semibold text-heading w-5 text-center">{String(minute).padStart(2, "0")}</span>
          <button type="button" onClick={() => cycleMinute(5)}
            className="w-5 h-5 rounded bg-input text-dim hover:text-heading flex items-center justify-center text-[10px] font-bold">+</button>
        </div>
        <button
          type="button"
          onClick={handleConfirm}
          disabled={!selectedDay}
          className={`w-8 h-8 rounded-full flex items-center justify-center transition-all active:scale-90 ${
            selectedDay ? "bg-cyan-500 text-white hover:bg-cyan-400" : "bg-elevated text-faint cursor-not-allowed"
          }`}
          title="Confirm"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </button>
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
