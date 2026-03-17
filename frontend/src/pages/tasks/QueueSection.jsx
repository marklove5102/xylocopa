import { useState, useEffect, useCallback, useRef } from "react";
import { fetchQueueStatus, updateProjectSettings } from "../../lib/api";
import QueueCard from "../../components/cards/QueueCard";
import { useWsEvent } from "../../hooks/useWebSocket";

export default function QueueSection() {
  const [data, setData] = useState(null);
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem("queue-section-collapsed") === "true"; } catch { return false; }
  });
  const [expandedTaskId, setExpandedTaskId] = useState(null);
  const [editingCap, setEditingCap] = useState(null); // { project, value }

  const load = useCallback(async () => {
    try {
      const res = await fetchQueueStatus();
      setData(res);
    } catch { /* ignore */ }
  }, []);

  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, [load]);

  useWsEvent((event) => {
    if (event.type === "task_update" || event.type === "agent_update") {
      loadRef.current();
    }
  });

  const toggleCollapse = () => {
    const next = !collapsed;
    setCollapsed(next);
    try { localStorage.setItem("queue-section-collapsed", String(next)); } catch { /* skip */ }
  };

  if (!data) return null;

  const { tasks, capacity } = data;
  const pendingTasks = tasks.filter(t => t.status === "PENDING");
  const executingTasks = tasks.filter(t => t.status === "EXECUTING");
  const totalQueued = pendingTasks.length + executingTasks.length;

  if (totalQueued === 0 && Object.keys(capacity).length === 0) return null;

  // Group capacity by projects that have queue activity
  const activeProjects = Object.entries(capacity).filter(([name]) =>
    tasks.some(t => t.project_name === name) || capacity[name].active > 0
  );

  const handleCapSave = async (project) => {
    if (!editingCap || editingCap.project !== project) return;
    const val = parseInt(editingCap.value, 10);
    if (isNaN(val) || val < 1) { setEditingCap(null); return; }
    try {
      await updateProjectSettings(project, { max_concurrent: val });
      load();
    } catch { /* skip */ }
    setEditingCap(null);
  };

  return (
    <div className="mb-4">
      {/* Header */}
      <button
        type="button"
        onClick={toggleCollapse}
        className="w-full flex items-center gap-2 px-1 py-2 text-left group"
      >
        <svg
          className={`w-3 h-3 text-faint transition-transform ${collapsed ? "" : "rotate-90"}`}
          fill="currentColor" viewBox="0 0 20 20"
        >
          <path fillRule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clipRule="evenodd" />
        </svg>
        <span className="text-xs font-semibold text-faint uppercase tracking-wide">
          Queue
        </span>
        {totalQueued > 0 && (
          <span className="text-[10px] font-bold px-1.5 py-px rounded-full bg-cyan-500/15 text-cyan-500">
            {totalQueued}
          </span>
        )}
        {/* Capacity pills */}
        <div className="flex items-center gap-1.5 ml-auto">
          {activeProjects.map(([name, cap]) => (
            <span key={name} className={`text-[10px] font-medium px-1.5 py-px rounded-full ${
              cap.active >= cap.max_concurrent
                ? "bg-amber-500/15 text-amber-500"
                : "bg-elevated text-dim"
            }`}>
              {name.slice(0, 12)} {cap.active}/{cap.max_concurrent}
            </span>
          ))}
        </div>
      </button>

      {/* Content */}
      {!collapsed && (
        <div className="space-y-2">
          {/* Capacity bars */}
          {activeProjects.length > 0 && (
            <div className="flex flex-wrap gap-2 px-1 pb-1">
              {activeProjects.map(([name, cap]) => {
                const pct = cap.max_concurrent > 0 ? Math.min(100, (cap.active / cap.max_concurrent) * 100) : 0;
                const isEditing = editingCap?.project === name;
                return (
                  <div key={name} className="flex items-center gap-2 text-xs text-dim min-w-[180px]">
                    <span className="font-medium text-body truncate max-w-[80px]">{name}</span>
                    <div className="flex-1 h-1.5 rounded-full bg-elevated overflow-hidden min-w-[40px]">
                      <div
                        className={`h-full rounded-full transition-all ${
                          pct >= 100 ? "bg-amber-500" : pct >= 70 ? "bg-yellow-500" : "bg-cyan-500"
                        }`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="tabular-nums text-faint shrink-0">
                      {cap.active}/
                      {isEditing ? (
                        <input
                          type="number"
                          min={1}
                          value={editingCap.value}
                          onChange={(e) => setEditingCap({ project: name, value: e.target.value })}
                          onBlur={() => handleCapSave(name)}
                          onKeyDown={(e) => { if (e.key === "Enter") handleCapSave(name); if (e.key === "Escape") setEditingCap(null); }}
                          autoFocus
                          className="w-8 bg-input text-heading text-center rounded px-0.5 outline-none border border-edge/30 focus:border-cyan-500/50"
                        />
                      ) : (
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setEditingCap({ project: name, value: String(cap.max_concurrent) }); }}
                          className="text-faint hover:text-heading transition-colors cursor-pointer"
                          title="Click to edit capacity"
                        >
                          {cap.max_concurrent}
                        </button>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Pending tasks */}
          {pendingTasks.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] font-semibold text-faint uppercase tracking-wide px-1">
                Waiting ({pendingTasks.length})
              </p>
              {pendingTasks.map((task, i) => (
                <QueueCard
                  key={task.id}
                  task={task}
                  position={i + 1}
                  expanded={expandedTaskId === task.id}
                  onExpand={(id) => setExpandedTaskId(prev => prev === id ? null : id)}
                  onRefresh={load}
                />
              ))}
            </div>
          )}

          {/* Executing tasks */}
          {executingTasks.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] font-semibold text-faint uppercase tracking-wide px-1">
                Running ({executingTasks.length})
              </p>
              {executingTasks.map((task) => (
                <QueueCard
                  key={task.id}
                  task={task}
                  position="~"
                  expanded={expandedTaskId === task.id}
                  onExpand={(id) => setExpandedTaskId(prev => prev === id ? null : id)}
                  onRefresh={load}
                />
              ))}
            </div>
          )}

          {totalQueued === 0 && (
            <p className="text-xs text-faint px-1 py-2">No tasks in queue</p>
          )}
        </div>
      )}
    </div>
  );
}
