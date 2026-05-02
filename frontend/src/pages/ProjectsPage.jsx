import { useState, useEffect, useCallback, useMemo, memo } from "react";
import { useNavigate, useNavigationType } from "react-router-dom";
import { DndContext, closestCenter, PointerSensor, TouchSensor, useSensor, useSensors, DragOverlay } from "@dnd-kit/core";
import { SortableContext, useSortable, verticalListSortingStrategy, arrayMove } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { fetchAllFolders, fetchTrashFolders, scanProjects, fetchClaudeMdPending, archiveProject, deleteProject, createProject } from "../lib/api";
import { relativeTime } from "../lib/formatters";
import ProjectRing from "../components/ProjectRing";
import FluentEmoji from "../components/FluentEmoji";
import PageHeader from "../components/PageHeader";
import useDraft from "../hooks/useDraft";
import useLongPress from "../hooks/useLongPress";
import usePageVisible from "../hooks/usePageVisible";
import { useToast } from "../contexts/ToastContext";

function DragHandle({ listeners, attributes }) {
  return (
    <button
      type="button"
      {...attributes}
      {...listeners}
      data-no-longpress
      className="touch-none p-1 -ml-2 mr-0 rounded text-ghost hover:text-faint transition-colors cursor-grab active:cursor-grabbing self-center"
      onClick={(e) => e.stopPropagation()}
    >
      <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor">
        <rect x="3" y="4" width="10" height="1.5" rx="0.75" />
        <rect x="3" y="8" width="10" height="1.5" rx="0.75" />
        <rect x="3" y="12" width="10" height="1.5" rx="0.75" />
      </svg>
    </button>
  );
}

function SortableFolderCard(props) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: props.folder.name,
    disabled: props.selecting,
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    WebkitUserSelect: "none",
    userSelect: "none",
  };
  return (
    <div ref={setNodeRef} style={style}>
      <FolderCard {...props} dragHandleProps={{ listeners, attributes }} />
    </div>
  );
}

const FolderCard = memo(function FolderCard({ folder, onClick, dragHandleProps, hasPendingClaudeMd, selecting = false, selected = false, onToggle, onEnterSelect }) {
  const running = folder.active ? (folder.agent_active || 0) : 0;

  const handleClick = () => {
    if (selecting) onToggle?.(folder.name);
    else onClick?.();
  };

  const isInner = (e) => !!e?.target?.closest?.("[data-no-longpress]");
  const longPressHandlers = useLongPress((e) => {
    if (selecting) return;
    if (isInner(e)) return;
    if (navigator.vibrate) navigator.vibrate(15);
    onEnterSelect?.(folder.name);
  }, (e) => {
    if (isInner(e)) return;
    handleClick();
  });

  return (
    <button
      type="button"
      {...longPressHandlers}
      style={{ WebkitTapHighlightColor: "transparent" }}
      data-project-name={folder.name}
      data-claudemd-pending={hasPendingClaudeMd ? "1" : undefined}
      className={`relative w-full text-left rounded-2xl bg-surface shadow-card overflow-hidden transform-gpu transition-[transform,box-shadow,ring-color,opacity,background-color,filter] duration-400 ease-[cubic-bezier(0.22,1.15,0.36,1)] active:bg-input focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 hover:ring-1 hover:ring-ring-hover ${
        selecting && selected ? "ring-2 ring-cyan-500/50 brightness-[0.88]" : ""
      }`}
    >
      {hasPendingClaudeMd && (
        <span className="absolute top-2.5 right-2.5 flex h-5 w-5 items-center justify-center rounded-full bg-amber-500 text-[9px] font-bold text-white shadow z-10">
          <span className="absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-50 animate-ping" />
          <span className="relative">!</span>
        </span>
      )}
      <div className="flex items-start gap-4 px-5 py-4">
        {dragHandleProps && !selecting && <DragHandle {...dragHandleProps} />}
        <ProjectRing
          emoji={folder.emoji}
          hasActiveAgents={running > 0}
          size={32}
          className="self-center"
        />

        <div className="min-w-0 flex-1">
          {/* Row 1: title + running pulse + time */}
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 min-w-0">
              <h3 className={`text-[16px] font-semibold truncate ${folder.active ? "text-heading" : "text-dim"}`}>
                {folder.display_name || folder.name}
              </h3>
              {running > 0 && (
                <span className="shrink-0 inline-flex items-center gap-1 text-[11px] font-semibold text-cyan-500 dark:text-cyan-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-glow" />
                  {running}
                </span>
              )}
            </div>
            {folder.last_activity && (
              <span className="text-[11px] text-faint shrink-0">
                {relativeTime(folder.last_activity)}
              </span>
            )}
          </div>

          {/* Row 2: LLM-generated recap, emoji trailing (height reserved) */}
          <div
            className="flex items-center gap-1.5 text-sm text-dim mt-1 h-5 leading-snug min-w-0"
            title={folder.resume_hint || ""}
          >
            <span className="truncate">{folder.resume_hint || ""}</span>
            {folder.resume_emoji && folder.resume_hint && (
              <FluentEmoji char={folder.resume_emoji} size={14} className="shrink-0" />
            )}
          </div>

          {/* Row 3: status pill */}
          <div className="flex items-center gap-1.5 mt-1.5">
            {folder.active ? (
              <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-px rounded-full bg-emerald-500/15 text-emerald-500 dark:text-emerald-400">
                Active
              </span>
            ) : (
              <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-px rounded-full bg-zinc-500/15 text-zinc-500 dark:text-zinc-400">
                Inactive
              </span>
            )}
          </div>
        </div>

        <svg className="w-4 h-4 text-faint shrink-0 self-center -mr-1" fill="none"
          stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </div>
    </button>
  );
});

const SORT_OPTIONS = [
  { value: "custom", label: "Custom" },
  { value: "name-asc", label: "Name A-Z" },
  { value: "name-desc", label: "Name Z-A" },
  { value: "updated-new", label: "Newest" },
  { value: "updated-old", label: "Oldest" },
];

export default function ProjectsPage({ theme, onToggleTheme, isActive = true }) {
  const navigate = useNavigate();
  const navType = useNavigationType();
  const visible = usePageVisible();
  const [folders, setFolders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [scanResult, setScanResult] = useState(null);
  const [filter, setFilter] = useDraft("ui:projects:filter", "ALL");
  const [trashCount, setTrashCount] = useState(0);
  const [sortMode, setSortMode] = useState(() => localStorage.getItem("projects-sort-mode") || "custom");
  const [customOrder, setCustomOrder] = useState(() => {
    try { return JSON.parse(localStorage.getItem("projects-custom-order")) || []; }
    catch { return []; } // Expected: localStorage data may be corrupt or invalid JSON
  });
  const [activeDragId, setActiveDragId] = useState(null);
  const [pendingProjects, setPendingProjects] = useState([]);

  // Multi-select state
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const toast = useToast();

  const enterSelectMode = useCallback((preSelectName) => {
    setSelecting(true);
    setSelected(preSelectName ? new Set([preSelectName]) : new Set());
  }, []);

  const exitSelectMode = useCallback(() => {
    setSelecting(false);
    setSelected(new Set());
  }, []);

  const toggleOne = useCallback((name) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  // Poll claudemd-pending projects
  useEffect(() => {
    if (!visible || !isActive) return;
    const poll = () => fetchClaudeMdPending().then((r) => setPendingProjects(r.projects || [])).catch(() => {});
    poll();
    const id = setInterval(poll, 30000);
    return () => clearInterval(id);
  }, [visible, isActive]);

  // Double-tap nav: scroll to first project with pending CLAUDE.md review
  useEffect(() => {
    const handler = (e) => {
      if (e.detail?.tab !== "projects") return;
      const el = document.querySelector("[data-claudemd-pending='1']");
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("ring-2", "ring-amber-400");
      setTimeout(() => el.classList.remove("ring-2", "ring-amber-400"), 1500);
    };
    window.addEventListener("nav-scroll-to-unread", handler);
    return () => window.removeEventListener("nav-scroll-to-unread", handler);
  }, []);

  const load = useCallback(async () => {
    try {
      const [data, trash] = await Promise.all([
        fetchAllFolders(),
        fetchTrashFolders(),
      ]);
      setFolders(data);
      setTrashCount(trash.length);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // Cross-pane sync: project list changes
  useEffect(() => {
    const onDataChanged = () => load();
    window.addEventListener("projects-data-changed", onDataChanged);
    return () => window.removeEventListener("projects-data-changed", onDataChanged);
  }, [load]);

  useEffect(() => {
    if (!visible || !isActive) return;
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, [load, visible, isActive]);

  // When user swipes back (POP) to the list, flag it so the tab bar
  // click handler knows to show the list instead of auto-navigating
  // back to the last-viewed project.
  useEffect(() => {
    if (navType === "POP") {
      sessionStorage.setItem("returnedFrom:projects", "1");
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Sync customOrder when folders load — append any new projects
  useEffect(() => {
    if (folders.length === 0) return;
    setCustomOrder((prev) => {
      const names = folders.map((f) => f.name);
      const existing = prev.filter((n) => names.includes(n));
      const newNames = names.filter((n) => !prev.includes(n)).sort();
      if (newNames.length === 0 && existing.length === prev.length) return prev;
      const updated = [...existing, ...newNames];
      localStorage.setItem("projects-custom-order", JSON.stringify(updated));
      return updated;
    });
  }, [folders]);

  const handleSortChange = useCallback((value) => {
    setSortMode(value);
    localStorage.setItem("projects-sort-mode", value);
  }, []);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
  );

  const handleDragStart = useCallback((event) => setActiveDragId(event.active.id), []);
  const handleDragEnd = useCallback((event) => {
    setActiveDragId(null);
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setCustomOrder((prev) => {
      const oldIdx = prev.indexOf(active.id);
      const newIdx = prev.indexOf(over.id);
      if (oldIdx === -1 || newIdx === -1) return prev;
      const updated = arrayMove(prev, oldIdx, newIdx);
      localStorage.setItem("projects-custom-order", JSON.stringify(updated));
      return updated;
    });
  }, []);
  const handleDragCancel = useCallback(() => setActiveDragId(null), []);

  const activeCount = folders.filter((f) => f.active).length;
  const inactiveCount = folders.filter((f) => !f.active).length;

  const filtered = useMemo(() => {
    const base = folders.filter((f) => filter === "ALL" || (filter === "ACTIVE" ? f.active : !f.active));
    switch (sortMode) {
      case "name-asc":
        return [...base].sort((a, b) => (a.display_name || a.name).localeCompare(b.display_name || b.name));
      case "name-desc":
        return [...base].sort((a, b) => (b.display_name || b.name).localeCompare(a.display_name || a.name));
      case "updated-new":
        return [...base].sort((a, b) => {
          if (!a.last_activity && !b.last_activity) return 0;
          if (!a.last_activity) return 1;
          if (!b.last_activity) return -1;
          return new Date(b.last_activity) - new Date(a.last_activity);
        });
      case "updated-old":
        return [...base].sort((a, b) => {
          if (!a.last_activity && !b.last_activity) return 0;
          if (!a.last_activity) return 1;
          if (!b.last_activity) return -1;
          return new Date(a.last_activity) - new Date(b.last_activity);
        });
      case "custom":
      default:
        return [...base].sort((a, b) => {
          const ai = customOrder.indexOf(a.name);
          const bi = customOrder.indexOf(b.name);
          if (ai === -1 && bi === -1) return a.name.localeCompare(b.name);
          if (ai === -1) return 1;
          if (bi === -1) return -1;
          return ai - bi;
        });
    }
  }, [folders, filter, sortMode, customOrder]);

  const FILTER_TABS = [
    { key: "ALL", label: "All" },
    { key: "ACTIVE", label: "Active" },
    { key: "INACTIVE", label: "Inactive" },
  ];

  const allSelected = filtered.length > 0 && selected.size === filtered.length;

  const selectAll = useCallback(() => {
    setSelected(new Set(filtered.map((f) => f.name)));
  }, [filtered]);

  const deselectAll = useCallback(() => {
    setSelected(new Set());
  }, []);

  // Partition selected names by their current active/archived state, so
  // bulk actions can light up the right buttons.
  const { selectedActive, selectedArchived } = useMemo(() => {
    const active = [];
    const archived = [];
    const byName = Object.fromEntries(folders.map((f) => [f.name, f]));
    for (const name of selected) {
      const f = byName[name];
      if (!f) continue;
      if (f.active) active.push(name);
      else archived.push(name);
    }
    return { selectedActive: active, selectedArchived: archived };
  }, [selected, folders]);

  const runBulk = useCallback(async (names, fn, verb) => {
    if (names.length === 0 || bulkBusy) return;
    setBulkBusy(true);
    let ok = 0, failed = 0;
    for (const name of names) {
      try { await fn(name); ok++; } catch { failed++; }
    }
    setBulkBusy(false);
    if (failed > 0) toast.error(`${verb} ${ok}, failed ${failed}`);
    else toast.success(`${verb} ${ok} project${ok !== 1 ? "s" : ""}`);
    exitSelectMode();
    load();
    window.dispatchEvent(new CustomEvent("projects-data-changed"));
  }, [bulkBusy, toast, exitSelectMode, load]);

  const handleBulkArchive = useCallback(() => {
    if (selectedActive.length === 0) return;
    if (!confirm(`Archive ${selectedActive.length} project${selectedActive.length > 1 ? "s" : ""}?`)) return;
    runBulk(selectedActive, archiveProject, "Archived");
  }, [selectedActive, runBulk]);

  const handleBulkActivate = useCallback(() => {
    if (selectedArchived.length === 0) return;
    runBulk(selectedArchived, (name) => createProject({ name }), "Activated");
  }, [selectedArchived, runBulk]);

  const handleBulkDelete = useCallback(() => {
    if (selected.size === 0) return;
    if (!confirm(`Delete ${selected.size} project${selected.size > 1 ? "s" : ""}? Files will be moved to Trash.`)) return;
    runBulk([...selected], deleteProject, "Deleted");
  }, [selected, runBulk]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    setScanResult(null);
    try {
      const result = await scanProjects();
      await load();
      if (result.added?.length > 0) {
        setScanResult(result);
        setTimeout(() => setScanResult(null), 4000);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      // Minimum 400ms spinner display to prevent jarring sub-frame flicker
      setTimeout(() => setRefreshing(false), 400);
    }
  }, [load]);

  const headerButtons = (
    <button
      type="button"
      onClick={handleRefresh}
      disabled={refreshing}
      title="Refresh & scan"
      className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-input transition-colors disabled:opacity-50"
    >
      <svg className={`w-4 h-4 text-label ${refreshing ? "animate-spin" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
      </svg>
    </button>
  );

  const sortDropdown = (
    <select
      value={sortMode}
      onChange={(e) => handleSortChange(e.target.value)}
      className="w-full h-[36px] pl-3.5 pr-5 text-sm font-medium leading-[36px] rounded-full bg-surface text-label border-none outline-none appearance-none text-center"
      style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")", backgroundRepeat: "no-repeat", backgroundPosition: "right 6px center" }}
    >
      {SORT_OPTIONS.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );

  return (
    <div className="h-full flex flex-col">
      <PageHeader title="Projects" theme={theme} onToggleTheme={onToggleTheme} showTimeRing hideMonitor actions={!selecting ? headerButtons : undefined}>
        {selecting ? (
          <div className="grid grid-cols-3 items-center px-4 pb-2">
            <button
              type="button"
              onClick={allSelected ? deselectAll : selectAll}
              className="justify-self-start text-sm font-medium text-cyan-400 hover:text-cyan-300 transition-colors px-2 py-1"
            >
              {allSelected ? "Deselect All" : "Select All"}
            </button>
            <span className="justify-self-center text-sm text-label">
              {selected.size > 0 ? `${selected.size} selected` : "Select projects"}
            </span>
            <button
              type="button"
              onClick={exitSelectMode}
              className="justify-self-end text-sm font-semibold text-cyan-400 hover:text-cyan-300 transition-colors px-2 py-1"
            >
              Done
            </button>
          </div>
        ) : (
          <div className="flex items-center px-4 pb-3 gap-1.5">
            <div className="flex gap-1.5 overflow-x-auto no-scrollbar min-w-0">
              {FILTER_TABS.map((tab) => {
                const isActive = filter === tab.key;
                const count = { ALL: folders.length, ACTIVE: activeCount, INACTIVE: inactiveCount }[tab.key];
                return (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setFilter(tab.key)}
                    className={`shrink-0 min-h-[36px] px-3 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap ${
                      isActive
                        ? "bg-cyan-600 text-white"
                        : "bg-surface text-label hover:bg-input hover:text-body"
                    }`}
                  >
                    {tab.label}
                    {count != null && (
                      <span className={`ml-1.5 text-xs ${isActive ? "text-cyan-200" : "text-faint"}`}>
                        {count}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
            <div className="ml-auto max-w-[7rem]">{sortDropdown}</div>
          </div>
        )}
      </PageHeader>
      {/* Scan result toast */}
      {scanResult && (
        <div className="fixed left-1/2 -translate-x-1/2 z-50 pointer-events-none safe-area-toast toast-pill toast-enter" style={{ maxWidth: 300, padding: '10px 14px', borderRadius: 14, background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)', boxShadow: '0 2px 16px rgba(0,0,0,0.12), 0 0 0 0.5px rgba(0,0,0,0.06)', fontSize: 13, fontWeight: 500, color: '#1c1c1e' }}>
          {scanResult.added.length > 0
            ? `Added ${scanResult.added.length} project${scanResult.added.length !== 1 ? "s" : ""}: ${scanResult.added.join(", ")}`
            : `Scanned ${scanResult.scanned} folders — no new projects`}
          {scanResult.skipped_archived?.length > 0 &&
            ` (${scanResult.skipped_archived.length} archived skipped)`}
        </div>
      )}

      <div className="flex-1 overflow-y-auto overflow-x-hidden">
      <div className="pb-24 p-4 max-w-2xl mx-auto w-full">

      {loading && folders.length === 0 && (
        <div className="flex justify-center py-12">
          <span className="text-dim text-sm animate-pulse">Loading projects...</span>
        </div>
      )}

      {error && (
        <div className="bg-red-950/40 border border-red-800 rounded-xl p-4 mb-4">
          <p className="text-red-400 text-sm">Failed to fetch projects: {error}</p>
          <button type="button" onClick={load} className="mt-2 text-xs text-red-300 underline hover:text-red-200">
            Retry
          </button>
        </div>
      )}

      {!loading && !error && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-faint">
          <svg className="w-12 h-12 mb-3" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg>
          <p className="text-sm">
            {folders.length === 0 ? "No project folders found" : `No ${filter.toLowerCase()} projects`}
          </p>
        </div>
      )}

      {sortMode === "custom" ? (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragCancel={handleDragCancel}
        >
          <SortableContext items={filtered.map((f) => f.name)} strategy={verticalListSortingStrategy}>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {filtered.map((folder) => (
                <SortableFolderCard
                  key={folder.name}
                  folder={folder}
                  onClick={() => navigate(`/projects/${encodeURIComponent(folder.name)}`)}
                  hasPendingClaudeMd={pendingProjects.includes(folder.name)}
                  selecting={selecting}
                  selected={selected.has(folder.name)}
                  onToggle={toggleOne}
                  onEnterSelect={enterSelectMode}
                />
              ))}
            </div>
          </SortableContext>
          <DragOverlay>
            {activeDragId ? (
              <div className="opacity-90 scale-105 shadow-xl rounded-xl">
                <FolderCard
                  folder={filtered.find((f) => f.name === activeDragId)}
                  onClick={() => {}}
                />
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {filtered.map((folder) => (
            <FolderCard
              key={folder.name}
              folder={folder}
              onClick={() => navigate(`/projects/${encodeURIComponent(folder.name)}`)}
              hasPendingClaudeMd={pendingProjects.includes(folder.name)}
              selecting={selecting}
              selected={selected.has(folder.name)}
              onToggle={toggleOne}
              onEnterSelect={enterSelectMode}
            />
          ))}
        </div>
      )}

      {trashCount > 0 && (
        <button
          type="button"
          onClick={() => navigate("/projects/trash")}
          className="block mx-auto mt-8 text-sm text-faint hover:text-dim transition-colors"
        >
          Deleted projects ({trashCount})
        </button>
      )}
      </div>
      </div>

      {selecting && selected.size > 0 && (
        <div className="fixed bottom-20 left-0 right-0 z-20 px-4 pb-2 animate-bar-slide-up">
          <div className="max-w-xl mx-auto bg-surface border border-divider rounded-xl shadow-lg p-3 flex items-center justify-center gap-3">
            <button
              type="button"
              onClick={handleBulkActivate}
              disabled={bulkBusy || selectedArchived.length === 0 || selectedActive.length > 0}
              className="flex-1 flex items-center justify-center gap-2 min-h-[40px] rounded-lg bg-cyan-600 text-white text-sm font-medium hover:bg-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              {selectedArchived.length > 0 && selectedActive.length === 0
                ? `Activate ${selectedArchived.length}`
                : "Activate"}
            </button>
            <button
              type="button"
              onClick={handleBulkArchive}
              disabled={bulkBusy || selectedActive.length === 0 || selectedArchived.length > 0}
              className="flex-1 flex items-center justify-center gap-2 min-h-[40px] rounded-lg bg-zinc-600 text-white text-sm font-medium hover:bg-zinc-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 8h14M5 8a2 2 0 100-4h14a2 2 0 100 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" />
              </svg>
              {selectedActive.length > 0 && selectedArchived.length === 0
                ? `Archive ${selectedActive.length}`
                : "Archive"}
            </button>
            <button
              type="button"
              onClick={handleBulkDelete}
              disabled={bulkBusy}
              className="flex-1 flex items-center justify-center gap-2 min-h-[40px] rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              {bulkBusy ? "..." : `Delete ${selected.size}`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
