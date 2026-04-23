import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import {
  fetchAllFolders,
  fetchProjectAgents,
  fetchProjectSessions,
  createAgent,
  createProject,
  deleteProject as deleteProjectApi,
  archiveProject as archiveProjectApi,
  renameProject as renameProjectApi,
  starSession,
  unstarSession,
  scanAgents,
  fetchProjectFile,
  refreshClaudeMd,
  refreshClaudeMdStatus,
  discardClaudeMd,
  summarizeProgress,
  summarizeProgressStatus,
  applyProgressSummary,
  updateProjectSettings,
  rebuildInsights,
  fetchTaskCounts,
} from "../lib/api";
import BotIcon from "../components/BotIcon";
import ProjectRing from "../components/ProjectRing";
import EmojiPicker from "../components/EmojiPicker";
import AgentRow from "../components/AgentRow";
import useDraft from "../hooks/useDraft";
import { relativeTime } from "../lib/formatters";
import { AGENT_STATUS_COLORS, AGENT_STATUS_TEXT_COLORS, modelDisplayName, agentBotState } from "../lib/constants";
import FilterTabs from "../components/FilterTabs";
import ProjectFileModal from "../components/ProjectFileModal";
import ProjectBrowserModal from "../components/ProjectBrowserModal";
import ClaudeMdDiffModal from "../components/ClaudeMdDiffModal";
import usePageVisible from "../hooks/usePageVisible";
import { useToast } from "../contexts/ToastContext";

const AGENT_TABS = [
  { key: "starred", label: "Starred" },
  { key: "active", label: "Active" },
  { key: "stopped", label: "Stopped" },
  { key: "sessions", label: "Sessions" },
];

function TaskRing({ total, completed, pct: pctOverride, size = 22 }) {
  if (!total && pctOverride == null) return null;
  const pct = pctOverride != null ? pctOverride : Math.round(completed / total * 100);
  const r = (size - 4) / 2, c = 2 * Math.PI * r;
  const offset = c * (1 - pct / 100);
  const color = pct >= 80 ? "#22c55e" : pct >= 50 ? "#eab308" : "#f87171";
  const half = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0">
      <circle cx={half} cy={half} r={r} fill="transparent" stroke={color} strokeWidth={2} opacity={0.18} />
      <circle cx={half} cy={half} r={r} fill="transparent" stroke={color} strokeWidth={2}
        strokeLinecap="round" strokeDasharray={c} strokeDashoffset={offset}
        transform={`rotate(-90 ${half} ${half})`} style={{ transition: "stroke-dashoffset 0.6s ease" }} />
      <text x={half} y={half} textAnchor="middle" dominantBaseline="central"
        fill={color} style={{ fontSize: `${size * 0.32}px`, fontWeight: 700 }}>
        {pct}
      </text>
    </svg>
  );
}

function ProjectStatsPopover({ stats, onClose, containerRef }) {
  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose, containerRef]);

  const wTotal = stats?.weekly_total ?? 0;
  const wCompleted = stats?.weekly_completed ?? 0;
  const wFailed = stats?.weekly_failed ?? 0;
  const wTimeout = stats?.weekly_timeout ?? 0;
  const wCancelled = stats?.weekly_cancelled ?? 0;
  const wRejected = stats?.weekly_rejected ?? 0;
  const wRetries = stats?.weekly_retries ?? 0;
  const wPct = stats?.weekly_success_pct ?? 0;
  const ringColor = wTotal === 0 ? "#9ca3af" : wPct >= 80 ? "#22c55e" : wPct >= 50 ? "#eab308" : "#f87171";

  const rows = [
    { label: "Completed", count: wCompleted, color: "#22c55e" },
    { label: "Retries",   count: wRetries,   color: "#fb923c" },
    { label: "Failed",    count: wFailed,    color: "#f87171" },
    { label: "Timeout",   count: wTimeout,   color: "#f59e0b" },
    { label: "Dropped",   count: wCancelled, color: "#9ca3af" },
    { label: "Rejected",  count: wRejected,  color: "#a78bfa" },
  ].filter(r => r.count > 0);

  const daily = stats?.daily;
  const hasDaily = daily && daily.some(d => d.total > 0);

  return (
    <div className="absolute right-0 top-full mt-2 z-50" style={{ minWidth: 260 }}>
      <div className="absolute -top-1.5 right-3"
        style={{ width: 12, height: 12, transform: "rotate(45deg)", background: "var(--color-surface)", borderTop: "1px solid var(--color-edge)", borderLeft: "1px solid var(--color-edge)" }} />
      <div className="bg-surface border border-edge rounded-xl shadow-lg overflow-hidden" style={{ boxShadow: "0 8px 30px var(--color-shadow)" }}>
        {/* Header */}
        <div className="px-4 pt-4 pb-3 flex items-center gap-3">
          <svg width="44" height="44" viewBox="0 0 44 44">
            <circle cx="22" cy="22" r="17" fill="transparent" stroke={ringColor} strokeWidth="3.5" opacity={0.18} />
            <circle cx="22" cy="22" r="17" fill="transparent" stroke={ringColor} strokeWidth="3.5"
              strokeLinecap="round" strokeDasharray={2 * Math.PI * 17} strokeDashoffset={2 * Math.PI * 17 * (1 - wPct / 100)}
              transform="rotate(-90 22 22)" style={{ transition: "stroke-dashoffset 0.6s ease" }} />
            <text x="22" y="22" textAnchor="middle" dominantBaseline="central"
              fill={ringColor} style={{ fontSize: "12px", fontWeight: 700 }}>{wPct}</text>
          </svg>
          <div>
            <div className="text-heading text-sm font-semibold">Weekly Success Rate</div>
            <div className="text-dim text-xs mt-0.5">{wTotal} tasks{wRetries > 0 ? ` · ${wRetries} retries` : ""}</div>
          </div>
        </div>

        <div className="border-t border-divider" />

        {/* Breakdown */}
        <div className="px-4 py-2.5 space-y-1.5">
          {rows.length === 0 ? (
            <div className="text-dim text-xs py-1">No completed tasks this week</div>
          ) : rows.map(r => (
            <div key={r.label} className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: r.color }} />
                <span className="text-body">{r.label}</span>
              </div>
              <span className="text-heading font-medium tabular-nums">{r.count}</span>
            </div>
          ))}
        </div>

        {/* Progress bar (adjusted for retries) */}
        {wTotal > 0 && (() => {
          const adjTotal = wTotal + wRetries;
          return (
            <div className="px-4 pb-3">
              <div className="h-1.5 rounded-full overflow-hidden flex" style={{ backgroundColor: "var(--color-input)" }}>
                {wCompleted > 0 && <div style={{ width: `${(wCompleted / adjTotal) * 100}%`, backgroundColor: "#22c55e" }} />}
                {wRetries > 0 && <div style={{ width: `${(wRetries / adjTotal) * 100}%`, backgroundColor: "#fb923c" }} />}
                {wFailed > 0 && <div style={{ width: `${(wFailed / adjTotal) * 100}%`, backgroundColor: "#f87171" }} />}
                {wTimeout > 0 && <div style={{ width: `${(wTimeout / adjTotal) * 100}%`, backgroundColor: "#f59e0b" }} />}
                {wCancelled > 0 && <div style={{ width: `${(wCancelled / adjTotal) * 100}%`, backgroundColor: "#9ca3af" }} />}
                {wRejected > 0 && <div style={{ width: `${(wRejected / adjTotal) * 100}%`, backgroundColor: "#a78bfa" }} />}
              </div>
            </div>
          );
        })()}

        {/* Daily sparkline */}
        {hasDaily && (() => {
          const W = 228, H = 72, PX = 8, PY = 14;
          const plotW = W - PX * 2, plotH = H - PY * 2;
          const points = daily.map((d, i) => ({
            x: PX + (i / Math.max(daily.length - 1, 1)) * plotW,
            pct: d.success_pct, total: d.total, date: d.date,
          }));
          const validPts = points.filter(p => p.pct != null);
          const yOf = (pct) => PY + plotH - (pct / 100) * plotH;
          const linePath = validPts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${yOf(p.pct).toFixed(1)}`).join(" ");
          const fillPath = validPts.length >= 2
            ? `${linePath} L${validPts[validPts.length - 1].x.toFixed(1)},${H - PY} L${validPts[0].x.toFixed(1)},${H - PY} Z` : "";
          const dayLabels = daily.map(d => ["S","M","T","W","T","F","S"][new Date(d.date + "T00:00:00").getDay()]);

          return (
            <div className="border-t border-divider px-4 py-2.5">
              <div className="text-faint text-[10px] uppercase tracking-wider font-medium mb-1.5">Daily Success Rate</div>
              <svg width={W} height={H + 14} viewBox={`0 0 ${W} ${H + 14}`} className="w-full" style={{ maxWidth: W }}>
                <defs>
                  <linearGradient id="projSparkFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#22c55e" stopOpacity="0.25" />
                    <stop offset="100%" stopColor="#22c55e" stopOpacity="0.02" />
                  </linearGradient>
                </defs>
                {[0, 50, 100].map(pct => (
                  <line key={pct} x1={PX} x2={W - PX} y1={yOf(pct)} y2={yOf(pct)}
                    stroke="var(--color-edge)" strokeWidth="0.5" strokeDasharray={pct === 50 ? "2,2" : "none"} opacity={0.5} />
                ))}
                {fillPath && <path d={fillPath} fill="url(#projSparkFill)" />}
                {validPts.length >= 2 && <path d={linePath} fill="none" stroke="#22c55e" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />}
                {validPts.map((p, i) => (
                  <circle key={i} cx={p.x} cy={yOf(p.pct)} r="2.5" fill="#22c55e" stroke="var(--color-surface)" strokeWidth="1" />
                ))}
                {validPts.map((p, i) => (
                  <text key={`lbl${i}`} x={p.x} y={yOf(p.pct) - 5} textAnchor="middle" fill="var(--color-heading)"
                    style={{ fontSize: "9px", fontWeight: 600 }}>{p.pct}%</text>
                ))}
                {points.map((p, i) => (
                  <text key={`day${i}`} x={p.x} y={H + 10} textAnchor="middle" fill="var(--color-dim)"
                    style={{ fontSize: "9px" }}>{dayLabels[i]}</text>
                ))}
              </svg>
            </div>
          );
        })()}

      </div>
    </div>
  );
}

function projectBotState(proj) {
  if (!proj.active) return "idle";
  if ((proj.agent_active || 0) > 0) return "running";
  if (proj.agent_count > 0) return "completed";
  return "idle";
}


function formatSessionTime(unixMs) {
  if (!unixMs) return "";
  const d = new Date(unixMs);
  const now = new Date();
  const diffMs = now - d;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  return d.toLocaleDateString();
}

function SessionRow({ session, project, projectActive, onResume, onError, onToggleStar }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [copied, setCopied] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [starLoading, setStarLoading] = useState(false);

  const handleCopyId = (e) => {
    e.stopPropagation();
    navigator.clipboard.writeText(session.session_id).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  };

  const handleStarClick = async (e) => {
    e.stopPropagation();
    if (starLoading) return;
    setStarLoading(true);
    try {
      if (session.starred) {
        await unstarSession(project, session.session_id);
      } else {
        await starSession(project, session.session_id);
      }
      if (onToggleStar) onToggleStar(session.session_id, !session.starred);
    } catch (err) {
      console.error("Star toggle failed:", err);
      if (onError) onError(err.message || "Failed to update star");
    } finally {
      setStarLoading(false);
    }
  };

  const handleSync = async (e) => {
    e.stopPropagation();
    if (syncing || resuming || !projectActive) return;
    setSyncing(true);
    try {
      const agent = await createAgent({
        project,
        prompt: session.first_message || "Synced CLI session",
        mode: "AUTO",
        resume_session_id: session.session_id,
        sync_session: true,
      });
      if (onResume) onResume();
      navigate(`/agents/${agent.id}`, { state: { from: location.pathname + location.search } });
    } catch (err) {
      setSyncing(false);
      if (onError) onError(err.message);
    }
  };

  const handleClick = async () => {
    if (resuming || syncing) return;
    // Block resume for inactive projects
    if (!projectActive && !session.linked_agent_id) {
      if (onError) onError("Please activate this project first");
      return;
    }
    // If already linked to an agent, navigate directly
    if (session.linked_agent_id) {
      navigate(`/agents/${session.linked_agent_id}`, { state: { from: location.pathname + location.search } });
      return;
    }
    // Otherwise, create a new agent that resumes this session
    setResuming(true);
    try {
      const agent = await createAgent({
        project,
        prompt: session.first_message || "Continue previous conversation",
        mode: "AUTO",
        resume_session_id: session.session_id,
      });
      if (onResume) onResume();
      navigate(`/agents/${agent.id}`, { state: { from: location.pathname + location.search } });
    } catch (err) {
      setResuming(false);
      if (onError) onError(err.message);
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={resuming}
      className="w-full text-left rounded-xl bg-surface shadow-card p-4 flex items-center gap-3 transition-colors active:bg-input focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 hover:ring-1 hover:ring-ring-hover disabled:opacity-60"
    >
      <div
        className="relative shrink-0 cursor-pointer hover:opacity-70 transition-opacity"
        onClick={handleCopyId}
        title={`Copy session ID: ${session.session_id}`}
      >
        {/* Clock icon */}
        <svg className="w-9 h-9 text-label" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9" />
          <path strokeLinecap="round" d="M12 7v5l3 3" />
        </svg>
        {copied && (
          <span className="absolute -bottom-5 left-1/2 -translate-x-1/2 text-[10px] text-cyan-400 font-medium whitespace-nowrap">
            Copied!
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-heading truncate flex-1">
            {session.first_message || "Untitled session"}
          </h3>
          <span className="text-xs text-dim shrink-0">
            {formatSessionTime(session.last_activity_at)}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <span className="text-xs text-label">
            {session.message_count} message{session.message_count !== 1 ? "s" : ""}
          </span>
          {session.linked_agent_id ? (
            <span className="inline-flex items-center gap-1 text-xs text-cyan-400 bg-cyan-500/10 px-1.5 py-0.5 rounded font-medium">
              Linked to agent
            </span>
          ) : resuming ? (
            <span className="inline-flex items-center gap-1 text-xs text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded font-medium animate-pulse">
              Resuming...
            </span>
          ) : syncing ? (
            <span className="inline-flex items-center gap-1 text-xs text-violet-400 bg-violet-500/10 px-1.5 py-0.5 rounded font-medium animate-pulse">
              Syncing...
            </span>
          ) : !projectActive ? (
            <span className="inline-flex items-center gap-1 text-xs text-dim bg-elevated px-1.5 py-0.5 rounded font-medium">
              Activate to resume
            </span>
          ) : (
            <>
              <span className="inline-flex items-center gap-1 text-xs text-violet-400 bg-violet-500/10 px-1.5 py-0.5 rounded font-medium">
                Click to resume
              </span>
              <button
                type="button"
                onClick={handleSync}
                className="inline-flex items-center gap-1 text-xs text-violet-400 bg-violet-500/10 px-1.5 py-0.5 rounded font-medium hover:bg-violet-500/20 transition-colors"
                title="Import CLI history and live-sync"
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Sync
              </button>
            </>
          )}
        </div>
      </div>
      <button
        type="button"
        onClick={handleStarClick}
        disabled={starLoading}
        className="shrink-0 p-1.5 rounded-lg hover:bg-input transition-colors disabled:opacity-50"
        title={session.starred ? "Unstar session" : "Star session"}
      >
        {session.starred ? (
          <svg className="w-5 h-5 text-amber-400" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
          </svg>
        ) : (
          <svg className="w-5 h-5 text-label hover:text-amber-400 transition-colors" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
          </svg>
        )}
      </button>
    </button>
  );
}

export default function ProjectDetailPage({ theme, onToggleTheme }) {
  const { name } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const visible = usePageVisible();

  // Remember last-viewed project so the tab bar can auto-navigate back.
  // Clear returnedFrom since the user is actively viewing a project.
  useEffect(() => {
    if (name) localStorage.setItem("lastViewed:projects", name);
    sessionStorage.removeItem("returnedFrom:projects");
  }, [name]);

  const [project, setProject] = useState(null);
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [agentTab, setAgentTab] = useDraft(`ui:project:${name}:tab`, "active");

  // Sessions (lazy-loaded)
  const [sessions, setSessions] = useState(null);
  const [sessionsLoading, setSessionsLoading] = useState(false);

  // Starred session IDs (eagerly loaded for agent rows)
  const [starredIds, setStarredIds] = useState(new Set());

  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const emojiAnchorRef = useRef(null);
  const [emojiAnchorRect, setEmojiAnchorRect] = useState(null);
  const toast = useToast();

  const [refreshing, setRefreshing] = useState(false);
  const [fileModal, setFileModal] = useState(null); // "CLAUDE.md" | "PROGRESS.md" | null
  const [showBrowser, setShowBrowser] = useState(false);
  const [fileExists, setFileExists] = useState({ "CLAUDE.md": null, "PROGRESS.md": null });
  const [refreshingClaudeMd, setRefreshingClaudeMd] = useState(false);
  const [claudeMdReady, setClaudeMdReady] = useState(false); // completed result available
  const [diffData, setDiffData] = useState(null); // response from refresh-claudemd
  const [summarizingProgress, setSummarizingProgress] = useState(false);
  const [progressReady, setProgressReady] = useState(false);
  const [progressDiffData, setProgressDiffData] = useState(null);

  // Rename
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [showRenameConfirm, setShowRenameConfirm] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const nameInputRef = useRef(null);

  // Task stats popover
  const [showStats, setShowStats] = useState(false);
  const [projectStats, setProjectStats] = useState(null);
  const statsRingRef = useRef(null);

  // Activate / Archive / Delete
  const [activating, setActivating] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const showToast = useCallback((message, type = "success") => {
    if (type === "error") toast.error(message);
    else toast.success(message);
  }, [toast]);

  // Auto-select name input when rename starts (useEffect runs after DOM commit)
  useEffect(() => {
    if (editingName) nameInputRef.current?.select();
  }, [editingName]);

  // Rename handlers
  const startRename = () => {
    setNameDraft(project?.display_name || project?.name || "");
    setEditingName(true);
  };

  const requestRename = () => {
    const trimmed = nameDraft.trim();
    if (!trimmed || trimmed === (project?.display_name || project?.name)) {
      setEditingName(false);
      return;
    }
    setEditingName(false);
    setShowRenameConfirm(true);
  };

  const deriveSlug = (text) =>
    text.trim().toLowerCase().replace(/[^a-z0-9._-]/g, "-").replace(/-{2,}/g, "-").replace(/^-+|-+$/g, "");

  const confirmRename = async () => {
    const slug = deriveSlug(nameDraft);
    if (!slug) {
      showToast("Invalid project name", "error");
      setShowRenameConfirm(false);
      return;
    }
    setRenaming(true);
    try {
      const displayName = nameDraft.trim() !== slug ? nameDraft.trim() : undefined;
      await renameProjectApi(name, slug, displayName);
      showToast("Project renamed!");
      setShowRenameConfirm(false);

      // Clean up old localStorage keys that embed the project name
      try {
        // Tab state from useDraft
        localStorage.removeItem(`draft:ui:project:${name}:tab`);
        // Update lastViewed to new name
        const lastViewed = localStorage.getItem("lastViewed:projects");
        if (lastViewed === name) {
          localStorage.setItem("lastViewed:projects", slug);
        }
        // Update custom order array
        const orderRaw = localStorage.getItem("projects-custom-order");
        if (orderRaw) {
          const order = JSON.parse(orderRaw);
          const idx = order.indexOf(name);
          if (idx !== -1) {
            order[idx] = slug;
            localStorage.setItem("projects-custom-order", JSON.stringify(order));
          }
        }
      } catch { /* ignore localStorage errors */ }

      navigate(`/projects/${encodeURIComponent(slug)}`, { replace: true });
    } catch (err) {
      showToast("Rename failed: " + err.message, "error");
      setShowRenameConfirm(false);
    } finally {
      setRenaming(false);
    }
  };

  // Fetch project + agents
  const loadData = useCallback(async () => {
    try {
      const [folders, agentList, stats] = await Promise.all([
        fetchAllFolders(),
        fetchProjectAgents(name),
        fetchTaskCounts(name).catch(() => null),
      ]);
      const folder = folders.find((f) => f.name === name);
      if (!folder) {
        navigate("/projects", { replace: true });
        return;
      }
      setProject(folder);
      setAgents(agentList);
      if (stats) setProjectStats(stats);
      setLoadError(null);
    } catch (err) {
      console.error("Failed to load project data:", err);
      setLoadError(err.message || "Failed to load project data");
    } finally {
      setLoading(false);
    }
  }, [name, navigate]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    scanAgents().catch(() => {});
    await loadData();
    // Minimum 400ms spinner display to prevent jarring sub-frame flicker
    setTimeout(() => setRefreshing(false), 400);
  }, [loadData]);

  const pollRef = useRef(null);
  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    setRefreshingClaudeMd(true);
    pollRef.current = setInterval(async () => {
      try {
        const res = await refreshClaudeMdStatus(name);
        if (res.status === "complete") {
          stopPolling();
          setRefreshingClaudeMd(false);
          setClaudeMdReady(true);
        } else if (res.status === "error") {
          stopPolling();
          setRefreshingClaudeMd(false);
          showToast(res.message || "Failed to analyze project — try again", "error");
        }
      } catch (err) {
        console.error("CLAUDE.md refresh poll failed:", err);
        stopPolling();
        setRefreshingClaudeMd(false);
        showToast("Failed to check refresh status", "error");
      }
    }, 2000);
  }, [name, stopPolling, showToast]);

  // Check for pending/complete job on mount
  useEffect(() => {
    if (!name) return;
    refreshClaudeMdStatus(name).then((res) => {
      if (res.status === "running") startPolling();
      else if (res.status === "complete") setClaudeMdReady(true);
    }).catch(() => {});
    return stopPolling;
  }, [name, startPolling, stopPolling]);

  const handleRefreshClaudeMd = useCallback(async () => {
    setRefreshingClaudeMd(true);
    setClaudeMdReady(false);
    try {
      await refreshClaudeMd(name);
      startPolling();
    } catch (err) {
      setRefreshingClaudeMd(false);
      showToast(err.message || "Failed to analyze project — try again", "error");
    }
  }, [name, showToast, startPolling]);

  const handleReviewUpdates = useCallback(async () => {
    try {
      const res = await refreshClaudeMdStatus(name);
      if (res.status === "complete") {
        setDiffData(res.data);
      } else {
        showToast("Update expired — run refresh again", "error");
        setClaudeMdReady(false);
      }
    } catch {
      showToast("Failed to load updates", "error");
    }
  }, [name, showToast]);

  // --- PROGRESS.md summary polling ---
  const progressPollRef = useRef(null);
  const stopProgressPolling = useCallback(() => {
    if (progressPollRef.current) { clearInterval(progressPollRef.current); progressPollRef.current = null; }
  }, []);

  const startProgressPolling = useCallback(() => {
    stopProgressPolling();
    setSummarizingProgress(true);
    progressPollRef.current = setInterval(async () => {
      try {
        const res = await summarizeProgressStatus(name);
        if (res.status === "complete") {
          stopProgressPolling();
          setSummarizingProgress(false);
          setProgressReady(true);
        } else if (res.status === "error") {
          stopProgressPolling();
          setSummarizingProgress(false);
          showToast(res.message || "Failed to summarize — try again", "error");
        }
      } catch (err) {
        console.error("PROGRESS.md summary poll failed:", err);
        stopProgressPolling();
        setSummarizingProgress(false);
        showToast("Failed to check summary status", "error");
      }
    }, 2000);
  }, [name, stopProgressPolling, showToast]);

  useEffect(() => {
    if (!name) return;
    summarizeProgressStatus(name).then((res) => {
      if (res.status === "running") startProgressPolling();
      else if (res.status === "complete") setProgressReady(true);
    }).catch(() => {});
    return stopProgressPolling;
  }, [name, startProgressPolling, stopProgressPolling]);

  const handleSummarizeProgress = useCallback(async () => {
    setSummarizingProgress(true);
    setProgressReady(false);
    try {
      await summarizeProgress(name);
      startProgressPolling();
    } catch (err) {
      setSummarizingProgress(false);
      showToast(err.message || "Failed to start summary — try again", "error");
    }
  }, [name, showToast, startProgressPolling]);

  const handleReviewProgressSummary = useCallback(async () => {
    try {
      const res = await summarizeProgressStatus(name);
      if (res.status === "complete") {
        setProgressDiffData(res.data);
      } else {
        showToast("Summary expired — run again", "error");
        setProgressReady(false);
      }
    } catch {
      showToast("Failed to load summary", "error");
    }
  }, [name, showToast]);

  const handleToggleAutoProgress = useCallback(async (enabled) => {
    try {
      const updated = await updateProjectSettings(name, { auto_progress_summary: enabled });
      setProject((prev) => prev ? { ...prev, auto_progress_summary: updated.auto_progress_summary } : prev);
      showToast(enabled ? "Daily auto-summary enabled" : "Daily auto-summary disabled");
    } catch (err) {
      showToast(err.message || "Failed to update setting", "error");
    }
  }, [name, showToast]);

  const handleToggleAiInsights = useCallback(async (enabled) => {
    try {
      const updated = await updateProjectSettings(name, { ai_insights: enabled });
      setProject((prev) => prev ? { ...prev, ai_insights: updated.ai_insights } : prev);
      showToast(enabled ? "AI-filtered insights enabled" : "AI-filtered insights disabled");
    } catch (err) {
      showToast(err.message || "Failed to update setting", "error");
    }
  }, [name, showToast]);

  const handleEmojiSelect = useCallback(async (char) => {
    setProject((prev) => prev ? { ...prev, emoji: char } : prev);
    try {
      await updateProjectSettings(name, { emoji: char });
      showToast(`Icon updated to ${char}`);
      window.dispatchEvent(new CustomEvent("projects-data-changed"));
    } catch (err) {
      showToast(err.message || "Failed to save icon", "error");
    }
  }, [name, showToast]);

  const handleEmojiClear = useCallback(async () => {
    setProject((prev) => prev ? { ...prev, emoji: null } : prev);
    try {
      await updateProjectSettings(name, { emoji: null });
      showToast("Icon reset to default");
      window.dispatchEvent(new CustomEvent("projects-data-changed"));
    } catch (err) {
      showToast(err.message || "Failed to reset icon", "error");
    }
  }, [name, showToast]);

  const openEmojiPicker = useCallback(() => {
    const rect = emojiAnchorRef.current?.getBoundingClientRect();
    if (rect) setEmojiAnchorRect(rect);
    setShowEmojiPicker(true);
  }, []);

  const closeEmojiPicker = useCallback(() => setShowEmojiPicker(false), []);

  const [rebuildingInsights, setRebuildingInsights] = useState(false);
  const handleRebuildInsights = useCallback(async () => {
    setRebuildingInsights(true);
    try {
      const res = await rebuildInsights(name);
      showToast(`Rebuilt insights: ${res.purged} purged, ${res.imported} imported`);
    } catch (err) {
      showToast(err.message || "Failed to rebuild insights", "error");
    } finally {
      setRebuildingInsights(false);
    }
  }, [name, showToast]);

  useEffect(() => {
    if (!visible) return;
    loadData();
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, [loadData, visible]);

  // Check CLAUDE.md / PROGRESS.md existence
  useEffect(() => {
    if (!name) return;
    Promise.all([
      fetchProjectFile(name, "CLAUDE.md").catch(() => ({ exists: false })),
      fetchProjectFile(name, "PROGRESS.md").catch(() => ({ exists: false })),
    ]).then(([c, p]) => {
      setFileExists({ "CLAUDE.md": c.exists, "PROGRESS.md": p.exists });
    });
  }, [name]);

  // Fetch sessions on mount (for starred IDs + counts)
  useEffect(() => {
    fetchProjectSessions(name)
      .then((data) => {
        setStarredIds(new Set(data.filter((s) => s.starred).map((s) => s.session_id)));
        setSessions(data);
      })
      .catch(() => {});
  }, [name]);

  // Lazy-fetch sessions when starred or sessions tab is selected
  useEffect(() => {
    if ((agentTab !== "sessions" && agentTab !== "starred") || sessions !== null) return;
    let cancelled = false;
    setSessionsLoading(true);
    fetchProjectSessions(name)
      .then((data) => { if (!cancelled) setSessions(data); })
      .catch(() => { if (!cancelled) setSessions([]); })
      .finally(() => { if (!cancelled) setSessionsLoading(false); });
    return () => { cancelled = true; };
  }, [agentTab, name, sessions]);

  // Poll sessions while sessions/starred tab is visible
  useEffect(() => {
    if (!visible || (agentTab !== "sessions" && agentTab !== "starred")) return;
    const timer = setInterval(() => {
      fetchProjectSessions(name)
        .then((data) => {
          setSessions(data);
          setStarredIds(new Set(data.filter((s) => s.starred).map((s) => s.session_id)));
        })
        .catch(() => {});
    }, 10000);
    return () => clearInterval(timer);
  }, [visible, agentTab, name]);

  // Filter agents by tab
  const filtered =
    agentTab === "active"
      ? agents.filter((a) => a.status !== "STOPPED")
      : agents.filter((a) => a.status === "STOPPED");

  // Tab counts
  const tabCounts = {
    starred: (sessions || []).filter((s) => s.starred).length,
    active: agents.filter(a => a.status !== "STOPPED").length,
    stopped: agents.filter((a) => a.status === "STOPPED").length,
    sessions: sessions != null ? sessions.length : 0,
  };

  // Activate project
  const handleActivate = async () => {
    setActivating(true);
    try {
      await createProject({ name });
      showToast("Project activated!");
      await loadData();
    } catch (err) {
      showToast("Activate failed: " + err.message, "error");
    } finally {
      setActivating(false);
    }
  };

  // Archive project
  const handleArchive = async () => {
    setArchiving(true);
    try {
      await archiveProjectApi(name);
      showToast("Project archived");
      await loadData();
    } catch (err) {
      showToast("Archive failed: " + err.message, "error");
    } finally {
      setArchiving(false);
    }
  };

  // Delete project
  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteProjectApi(name);
      navigate("/projects", { replace: true });
    } catch (err) {
      showToast("Delete failed: " + err.message, "error");
    } finally {
      setDeleting(false);
      setShowDelete(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <span className="text-dim text-sm animate-pulse">Loading...</span>
      </div>
    );
  }

  if (!project && loadError) {
    return (
      <div className="px-4 py-10">
        <div className="bg-red-950/40 border border-red-800 rounded-xl p-4">
          <p className="text-red-400 text-sm">Failed to load project: {loadError}</p>
          <button type="button" onClick={loadData} className="mt-2 text-xs text-red-300 underline hover:text-red-200">
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!project) return null;

  return (
    <div className="h-full flex flex-col">
      {/* Fixed Header */}
      <div className="shrink-0 bg-page border-b border-divider relative z-10 safe-area-pt">
        <div className="max-w-2xl mx-auto px-4 pt-3">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => { localStorage.removeItem("lastViewed:projects"); navigate("/projects", { replace: true }); }}
              title="Back to projects"
              aria-label="Back to projects"
              className="shrink-0 w-7 h-9 -ml-2 flex items-center justify-center rounded-lg text-label hover:text-heading hover:bg-input transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <button
              ref={emojiAnchorRef}
              type="button"
              onClick={openEmojiPicker}
              title="Change project icon"
              className="shrink-0 rounded-lg p-1 -m-1 hover:bg-input transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500"
            >
              <ProjectRing
                emoji={project.emoji}
                hasActiveAgents={(project.agent_active || 0) > 0}
                size={36}
              />
            </button>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                {editingName ? (
                  <input
                    ref={nameInputRef}
                    value={nameDraft}
                    onChange={(e) => setNameDraft(e.target.value)}
                    onBlur={requestRename}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") requestRename();
                      if (e.key === "Escape") setEditingName(false);
                    }}
                    maxLength={100}
                    className="text-lg font-bold text-heading min-w-0 flex-1 bg-input border border-cyan-500 rounded px-1.5 py-0.5 outline-none"
                  />
                ) : (
                  <h1
                    onDoubleClick={startRename}
                    title="Double-tap to rename"
                    className="text-lg font-bold text-heading truncate select-none"
                  >
                    {project.display_name || project.name}
                  </h1>
                )}
                {project.active ? (
                  <span className="shrink-0 px-2 py-0.5 text-[10px] font-bold uppercase rounded-full bg-emerald-500/15 text-emerald-400 tracking-wide">Active</span>
                ) : (
                  <span className="shrink-0 px-2 py-0.5 text-[10px] font-bold uppercase rounded-full bg-zinc-500/15 text-zinc-400 tracking-wide">Inactive</span>
                )}
                <div className="ml-auto flex items-center gap-1">
                  {(project.task_total || 0) > 0 && (
                    <div className="relative" ref={statsRingRef}>
                      <button
                        type="button"
                        onClick={() => {
                          if (!showStats) {
                            fetchTaskCounts(project.name).then(setProjectStats).catch(() => {});
                          }
                          setShowStats(v => !v);
                        }}
                        title={`Weekly: ${projectStats?.weekly_completed ?? (project.task_completed || 0)}/${projectStats?.weekly_total ?? project.task_total} tasks completed`}
                        className="shrink-0 flex items-center justify-center rounded-md hover:bg-white/5 transition-colors p-0.5"
                      >
                        <TaskRing total={projectStats?.weekly_total ?? project.task_total} completed={projectStats?.weekly_completed ?? (project.task_completed || 0)} pct={projectStats?.weekly_success_pct} size={24} />
                      </button>
                      {showStats && projectStats && (
                        <ProjectStatsPopover stats={projectStats} onClose={() => setShowStats(false)} containerRef={statsRingRef} />
                      )}
                    </div>
                  )}
                  {["CLAUDE.md", "PROGRESS.md"].map((fn) => {
                    const letter = fn === "CLAUDE.md" ? "C" : "P";
                    const exists = fileExists[fn];
                    const color = exists === false ? "text-zinc-500 hover:text-zinc-400" : "text-cyan-400 hover:text-cyan-300";
                    return (
                      <button
                        key={fn}
                        type="button"
                        onClick={() => setFileModal(fn)}
                        title={fn}
                        className={`relative shrink-0 w-6 h-6 flex items-center justify-center rounded-md hover:bg-white/5 transition-colors ${color}`}
                      >
                        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                          <path strokeLinecap="round" strokeLinejoin="round" d="M14 2v6h6" />
                          <text x="12" y="17" textAnchor="middle" fill="currentColor" stroke="none" fontSize="7" fontWeight="700" fontFamily="system-ui">{letter}</text>
                        </svg>
                        {fn === "CLAUDE.md" && claudeMdReady && (
                          <span className="absolute -top-1 -right-1 flex h-3 w-3 items-center justify-center rounded-full bg-amber-500 text-[7px] font-bold text-white">1</span>
                        )}
                      </button>
                    );
                  })}
                  <button
                    type="button"
                    onClick={() => setShowBrowser(true)}
                    title="Browse files"
                    className="shrink-0 w-6 h-6 flex items-center justify-center rounded-md text-zinc-400 hover:text-zinc-300 hover:bg-white/5 transition-colors"
                  >
                    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    onClick={handleRefresh}
                    title="Refresh"
                    className="w-6 h-6 flex items-center justify-center rounded-md hover:bg-white/5 transition-colors"
                  >
                    <svg className={`w-4 h-4 text-label ${refreshing ? "animate-spin" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div className="max-w-2xl mx-auto mt-3">
          <FilterTabs tabs={AGENT_TABS} active={agentTab} onChange={setAgentTab} counts={tabCounts} />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden">
      <div className="pb-24 p-4 max-w-2xl mx-auto w-full space-y-5">

      {/* Inactive project banner */}
      {!project.active && (
        <div className="rounded-xl bg-amber-500/10 border border-amber-500/20 p-4 flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-amber-300">This project is inactive</p>
            <p className="text-xs text-amber-400/70 mt-0.5">Activate to create new agents and run tasks</p>
          </div>
          <button
            type="button"
            disabled={activating}
            onClick={handleActivate}
            className="shrink-0 px-4 py-2 rounded-lg bg-cyan-600 text-white text-sm font-semibold hover:bg-cyan-500 disabled:opacity-50 transition-colors"
          >
            {activating ? "Activating..." : "Activate"}
          </button>
        </div>
      )}

      {/* Agent list */}
      <div>
        {agentTab === "sessions" || agentTab === "starred" ? (
          sessionsLoading ? (
            <div className="text-center py-8 text-faint text-sm animate-pulse">Loading sessions...</div>
          ) : (() => {
            const list = agentTab === "starred"
              ? (sessions || []).filter((s) => s.starred)
              : sessions || [];
            return list.length === 0 ? (
              <div className="text-center py-8 text-faint text-sm">
                {agentTab === "starred" ? "No starred sessions" : "No sessions found"}
              </div>
            ) : (
              <div className="space-y-2">
                {list.map((s) => (
                  <SessionRow
                    key={s.session_id}
                    session={s}
                    project={name}
                    projectActive={project?.active}
                    onResume={() => { setSessions(null); loadData(); }}
                    onError={(msg) => showToast(msg, "error")}
                    onToggleStar={(sid, starred) => {
                      setSessions((prev) =>
                        prev ? prev.map((ss) =>
                          ss.session_id === sid ? { ...ss, starred } : ss
                        ) : prev
                      );
                    }}
                  />
                ))}
              </div>
            );
          })()
        ) : filtered.length === 0 ? (
          <div className="text-center py-8 text-faint text-sm">
            No {agentTab} agents
          </div>
        ) : (
          <div className="space-y-3">
            {filtered.map((agent) => (
              <AgentRow
                key={agent.id}
                agent={agent}
                hideProjectTag
                onClick={() => navigate(`/agents/${agent.id}`, { state: { from: location.pathname + location.search } })}
              />
            ))}
          </div>
        )}
      </div>

      {/* Project settings */}
      <div className="rounded-xl bg-surface shadow-card p-4 space-y-3">
        <h2 className="text-sm font-semibold text-label uppercase tracking-wider">Settings</h2>
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm text-body">Refresh CLAUDE.md</p>
            <p className="text-xs text-dim">AI-analyze project and propose updates</p>
          </div>
          {claudeMdReady ? (
            <button
              type="button"
              onClick={handleReviewUpdates}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-amber-500 text-white text-xs font-medium hover:bg-amber-400 transition-colors flex items-center gap-1.5"
            >
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-white" />
              </span>
              Review Updates
            </button>
          ) : (
            <button
              type="button"
              disabled={refreshingClaudeMd}
              onClick={handleRefreshClaudeMd}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-cyan-600 text-white text-xs font-medium hover:bg-cyan-500 disabled:opacity-50 transition-colors flex items-center gap-1.5"
            >
              {refreshingClaudeMd ? (
                <>
                  <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="31.4" strokeLinecap="round" /></svg>
                  Analyzing...
                </>
              ) : (
                <>
                  <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clipRule="evenodd" /></svg>
                  Refresh CLAUDE.md
                </>
              )}
            </button>
          )}
        </div>
        {/* Daily summary settings hidden — per-agent insights still available */}
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm text-body">Rebuild Insights DB</p>
            <p className="text-xs text-dim">Re-import all insights from PROGRESS.md</p>
          </div>
          <button
            type="button"
            disabled={rebuildingInsights}
            onClick={handleRebuildInsights}
            className="shrink-0 px-3 py-1.5 rounded-lg bg-cyan-600/20 text-cyan-400 text-xs font-medium hover:bg-cyan-600/30 disabled:opacity-50 transition-colors"
          >
            {rebuildingInsights ? "Rebuilding..." : "Rebuild"}
          </button>
        </div>
        {project.active ? (
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm text-body">Archive Project</p>
              <p className="text-xs text-dim">Deactivate — code and history stay, re-activate anytime</p>
            </div>
            <button
              type="button"
              disabled={archiving}
              onClick={handleArchive}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-amber-600/20 text-amber-400 text-xs font-medium hover:bg-amber-600/30 disabled:opacity-50 transition-colors"
            >
              {archiving ? "Archiving..." : "Archive"}
            </button>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm text-body">Activate Project</p>
              <p className="text-xs text-dim">Register this folder to create agents and run tasks</p>
            </div>
            <button
              type="button"
              disabled={activating}
              onClick={handleActivate}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-cyan-600/20 text-cyan-400 text-xs font-medium hover:bg-cyan-600/30 disabled:opacity-50 transition-colors"
            >
              {activating ? "Activating..." : "Activate"}
            </button>
          </div>
        )}
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm text-body">Delete Project</p>
            <p className="text-xs text-dim">Move files to .trash</p>
          </div>
          <button
            type="button"
            onClick={() => setShowDelete(true)}
            className="shrink-0 px-3 py-1.5 rounded-lg bg-red-600/20 text-red-400 text-xs font-medium hover:bg-red-600/30 transition-colors"
          >
            Delete
          </button>
        </div>
      </div>

      {/* Rename confirmation modal */}
      {showRenameConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="bg-surface rounded-2xl p-6 max-w-sm w-full space-y-4 shadow-card">
            <h3 className="text-lg font-bold text-heading">Rename Project?</h3>
            <p className="text-sm text-label">
              This will rename <span className="font-semibold text-heading">"{name}"</span> to{" "}
              <span className="font-semibold text-heading">"{deriveSlug(nameDraft)}"</span>.
            </p>
            <p className="text-xs text-dim">
              All agents, tasks, session references, and local files will be updated. This cannot be undone.
            </p>
            <div className="flex gap-3">
              <button
                type="button"
                disabled={renaming}
                onClick={confirmRename}
                className="flex-1 min-h-[44px] rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-semibold text-sm transition-colors disabled:opacity-50"
              >
                {renaming ? "Renaming..." : "Rename"}
              </button>
              <button
                type="button"
                onClick={() => setShowRenameConfirm(false)}
                className="flex-1 min-h-[44px] rounded-lg bg-input hover:bg-elevated text-body text-sm transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation modal */}
      {showDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="bg-surface rounded-2xl p-6 max-w-sm w-full space-y-4 shadow-card">
            <h3 className="text-lg font-bold text-heading">Delete "{project.display_name}"?</h3>
            <p className="text-sm text-label">
              This will remove the project record. Agents will remain in history. This cannot be undone.
            </p>
            <div className="flex gap-3">
              <button
                type="button"
                disabled={deleting}
                onClick={handleDelete}
                className="flex-1 min-h-[44px] rounded-lg bg-red-600 hover:bg-red-500 text-white font-semibold text-sm transition-colors disabled:opacity-50"
              >
                {deleting ? "Deleting..." : "Delete"}
              </button>
              <button
                type="button"
                onClick={() => setShowDelete(false)}
                className="flex-1 min-h-[44px] rounded-lg bg-input hover:bg-elevated text-body text-sm transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
      </div>

      {fileModal && (
        <ProjectFileModal
          project={name}
          filename={fileModal}
          onClose={() => {
            setFileModal(null);
            // Refresh existence state after modal closes
            Promise.all([
              fetchProjectFile(name, "CLAUDE.md").catch(() => ({ exists: false })),
              fetchProjectFile(name, "PROGRESS.md").catch(() => ({ exists: false })),
            ]).then(([c, p]) => {
              setFileExists({ "CLAUDE.md": c.exists, "PROGRESS.md": p.exists });
            });
          }}
        />
      )}

      {showBrowser && (
        <ProjectBrowserModal
          project={name}
          onClose={() => setShowBrowser(false)}
        />
      )}

      {diffData && (
        <ClaudeMdDiffModal
          data={diffData}
          project={name}
          onClose={() => { setDiffData(null); setClaudeMdReady(false); discardClaudeMd(name).catch(() => {}); }}
          onApplied={(lines, error) => {
            setDiffData(null);
            setClaudeMdReady(false);
            if (error) {
              showToast("Apply failed: " + error, "error");
            } else {
              showToast(`CLAUDE.md updated (${lines} lines)`);
            }
          }}
        />
      )}
      {progressDiffData && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="bg-surface rounded-xl shadow-2xl max-w-2xl w-full max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
              <h3 className="text-sm font-semibold text-label">PROGRESS.md Summary</h3>
              <button type="button" onClick={() => { setProgressDiffData(null); setProgressReady(false); }} className="text-dim hover:text-body">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              {progressDiffData.message ? (
                <p className="text-sm text-dim">{progressDiffData.message}</p>
              ) : progressDiffData.diff ? (
                <pre className="text-xs font-mono whitespace-pre-wrap text-body">{progressDiffData.diff}</pre>
              ) : (
                <pre className="text-xs font-mono whitespace-pre-wrap text-body">{progressDiffData.proposed}</pre>
              )}
            </div>
            <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-border">
              <button
                type="button"
                onClick={() => { setProgressDiffData(null); setProgressReady(false); }}
                className="px-3 py-1.5 rounded-lg text-xs text-dim hover:text-body transition-colors"
              >
                Discard
              </button>
              {!progressDiffData.message && (
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      const res = await applyProgressSummary(name);
                      setProgressDiffData(null);
                      setProgressReady(false);
                      showToast(`PROGRESS.md updated (${res.lines} lines)`);
                    } catch (err) {
                      showToast("Apply failed: " + (err.message || "unknown error"), "error");
                    }
                  }}
                  className="px-3 py-1.5 rounded-lg bg-cyan-600 text-white text-xs font-medium hover:bg-cyan-500 transition-colors"
                >
                  Apply
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {showEmojiPicker && (
        <EmojiPicker
          current={project?.emoji || null}
          anchorRect={emojiAnchorRect}
          onSelect={handleEmojiSelect}
          onClear={handleEmojiClear}
          onClose={closeEmojiPicker}
        />
      )}
    </div>
  );
}
