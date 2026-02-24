import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { fetchProjects } from "../lib/api";
import { relativeTime } from "../lib/formatters";
import BotIcon from "../components/BotIcon";
import PageHeader from "../components/PageHeader";

function botState(proj) {
  if (proj.agent_active > 0 || proj.task_running > 0) return "running";
  if (proj.task_failed > 0) return "error";
  if (proj.agent_total > 0 || proj.task_completed > 0) return "completed";
  return "idle";
}

function ProjectCard({ project, onClick }) {
  const state = botState(project);
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left rounded-xl bg-surface shadow-card p-5 transition-colors active:bg-input focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 hover:ring-1 hover:ring-ring-hover"
    >
      <div className="flex items-start gap-4">
        <BotIcon state={state} className="w-10 h-10 shrink-0" />
        <div className="min-w-0 flex-1">
          <h3 className="text-base font-semibold text-heading truncate">
            {project.display_name || project.name}
          </h3>
          {project.git_remote && (
            <p className="text-xs text-dim truncate mt-0.5">{project.git_remote}</p>
          )}
          {project.description && (
            <p className="text-xs text-label mt-1 line-clamp-2">{project.description}</p>
          )}
        </div>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-4 mt-4 text-xs">
        <span className="text-label">
          <span className="font-medium text-heading">{project.agent_total}</span> agents
        </span>
        {project.agent_active > 0 && (
          <span className="text-cyan-400">{project.agent_active} active</span>
        )}
        {project.task_total > 0 && (
          <span className="text-label">
            <span className="font-medium text-heading">{project.task_total}</span> tasks
          </span>
        )}
        {project.last_activity && (
          <span className="ml-auto text-dim">
            {relativeTime(project.last_activity)}
          </span>
        )}
      </div>
    </button>
  );
}

export default function ProjectsPage({ theme, onToggleTheme }) {
  const navigate = useNavigate();
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchProjects();
      setProjects(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, [load]);

  return (
    <div className="h-full overflow-y-auto overflow-x-hidden">
      <PageHeader title="Projects" theme={theme} onToggleTheme={onToggleTheme} />
      <div className="pb-20 p-4 max-w-2xl mx-auto w-full">

      {loading && projects.length === 0 && (
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

      {!loading && !error && projects.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-faint">
          <svg className="w-12 h-12 mb-3" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
          </svg>
          <p className="text-sm">No projects registered</p>
          <p className="text-xs mt-1 text-ghost">Create one from the New tab</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {projects.map((proj) => (
          <ProjectCard
            key={proj.name}
            project={proj}
            onClick={() => navigate(`/projects/${proj.name}`)}
          />
        ))}
      </div>
      </div>
    </div>
  );
}
