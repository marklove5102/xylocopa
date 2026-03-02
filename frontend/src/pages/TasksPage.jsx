import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { fetchTasksV2 } from "../lib/api";
import { TASK_STATUS_TABS, POLL_INTERVAL } from "../lib/constants";
import TaskCardV2 from "../components/TaskCardV2";
import PageHeader from "../components/PageHeader";
import FilterTabs from "../components/FilterTabs";
import useDraft from "../hooks/useDraft";
import usePageVisible from "../hooks/usePageVisible";

const ACTIVE_STATUSES = ["EXECUTING"];
const REVIEW_STATUSES = ["REVIEW", "MERGING", "CONFLICT"];
const DONE_STATUSES = ["COMPLETE", "CANCELLED", "REJECTED", "FAILED", "TIMEOUT"];

function filterTasks(tasks, tab) {
  if (tab === "ALL") return tasks;
  if (tab === "INBOX") return tasks.filter((t) => t.status === "INBOX");
  if (tab === "PENDING") return tasks.filter((t) => t.status === "PENDING");
  if (tab === "ACTIVE") return tasks.filter((t) => ACTIVE_STATUSES.includes(t.status));
  if (tab === "REVIEW") return tasks.filter((t) => REVIEW_STATUSES.includes(t.status));
  if (tab === "DONE") return tasks.filter((t) => DONE_STATUSES.includes(t.status));
  return tasks;
}

export default function TasksPage({ theme, onToggleTheme }) {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useDraft("ui:tasks-v2:filter", "ALL");
  const pollRef = useRef(null);
  const visible = usePageVisible();

  const load = useCallback(async () => {
    try {
      const data = await fetchTasksV2();
      setTasks(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!visible) return;
    load();
    pollRef.current = setInterval(load, POLL_INTERVAL);
    return () => clearInterval(pollRef.current);
  }, [load, visible]);

  // Compute counts
  const counts = useMemo(() => ({
    ALL: tasks.length,
    INBOX: tasks.filter((t) => t.status === "INBOX").length,
    PENDING: tasks.filter((t) => t.status === "PENDING").length,
    ACTIVE: tasks.filter((t) => ACTIVE_STATUSES.includes(t.status)).length,
    REVIEW: tasks.filter((t) => REVIEW_STATUSES.includes(t.status)).length,
    DONE: tasks.filter((t) => DONE_STATUSES.includes(t.status)).length,
  }), [tasks]);

  const filtered = useMemo(() => filterTasks(tasks, activeTab), [tasks, activeTab]);

  const sorted = useMemo(() =>
    [...filtered].sort((a, b) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    ),
    [filtered]);

  return (
    <div className="h-full flex flex-col">
      <PageHeader title="Tasks" theme={theme} onToggleTheme={onToggleTheme}>
        <FilterTabs tabs={TASK_STATUS_TABS} active={activeTab} onChange={setActiveTab} counts={counts} />
      </PageHeader>

      <div className="flex-1 overflow-y-auto overflow-x-hidden">
      <div className="max-w-2xl mx-auto w-full">
      <div className="pb-20 px-4 py-3 space-y-3">
        {loading && tasks.length === 0 && (
          <div className="flex justify-center py-12">
            <span className="text-dim text-sm animate-pulse">Loading tasks...</span>
          </div>
        )}

        {error && (
          <div className="bg-red-950/40 border border-red-800 rounded-xl p-4">
            <p className="text-red-400 text-sm">Failed to fetch tasks: {error}</p>
            <button type="button" onClick={load} className="mt-2 text-xs text-red-300 underline hover:text-red-200">
              Retry
            </button>
          </div>
        )}

        {!loading && !error && sorted.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-faint">
            <svg className="w-12 h-12 mb-3" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            <p className="text-sm">No tasks found</p>
          </div>
        )}

        {sorted.map((task) => (
          <TaskCardV2 key={task.id} task={task} />
        ))}

        <div className="h-4" />
      </div>
      </div>
      </div>
    </div>
  );
}
