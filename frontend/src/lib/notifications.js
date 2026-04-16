const MUTED_KEY = "xylocopa-muted-agents";
const AGENTS_NOTIF_KEY = "xylocopa-agents-notifications-enabled";
const TASKS_NOTIF_KEY = "xylocopa-tasks-notifications-enabled";

// One-time migration of legacy "agenthive-*" localStorage keys
try {
  const pairs = [
    ["agenthive-muted-agents", MUTED_KEY],
    ["agenthive-agents-notifications-enabled", AGENTS_NOTIF_KEY],
    ["agenthive-tasks-notifications-enabled", TASKS_NOTIF_KEY],
  ];
  for (const [oldK, newK] of pairs) {
    const legacy = localStorage.getItem(oldK);
    if (legacy !== null) {
      if (localStorage.getItem(newK) === null) localStorage.setItem(newK, legacy);
      localStorage.removeItem(oldK);
    }
  }
} catch {}

/** Get the set of muted agent IDs from localStorage. */
function getMutedAgents() {
  try {
    const v = localStorage.getItem(MUTED_KEY);
    return v ? new Set(JSON.parse(v)) : new Set();
  } catch (err) {
    console.warn("getMutedAgents: failed to read muted agents:", err);
    return new Set();
  }
}

/** Check if a specific agent is muted. */
export function isAgentMuted(agentId) {
  return getMutedAgents().has(agentId);
}

/** Set mute state for a specific agent. */
export function setAgentMuted(agentId, muted) {
  const set = getMutedAgents();
  if (muted) set.add(agentId);
  else set.delete(agentId);
  localStorage.setItem(MUTED_KEY, JSON.stringify([...set]));
  window.dispatchEvent(new CustomEvent("agent-mute-changed", { detail: { agentId, muted } }));
}

/** Check if agent notifications are globally enabled. */
export function isAgentNotificationsEnabled() {
  const v = localStorage.getItem(AGENTS_NOTIF_KEY);
  return v !== "0";
}

/** Set global agent notifications enabled state. */
export function setAgentNotificationsEnabled(enabled) {
  localStorage.setItem(AGENTS_NOTIF_KEY, enabled ? "1" : "0");
}

/** Check if task notifications are globally enabled. */
export function isTaskNotificationsEnabled() {
  const v = localStorage.getItem(TASKS_NOTIF_KEY);
  return v !== "0";
}

/** Set global task notifications enabled state. */
export function setTaskNotificationsEnabled(enabled) {
  localStorage.setItem(TASKS_NOTIF_KEY, enabled ? "1" : "0");
}

/** Agents currently being viewed (across all panes / tabs). */
const _viewingAgents = new Set();
/** Number of active TasksPage / TaskDetailPage instances viewing tasks. */
let _viewingTasksCount = 0;

export function registerViewing(agentId) { if (agentId) _viewingAgents.add(agentId); }
export function unregisterViewing(agentId) { if (agentId) _viewingAgents.delete(agentId); }
export function registerViewingTasks() { _viewingTasksCount++; }
export function unregisterViewingTasks() { _viewingTasksCount = Math.max(0, _viewingTasksCount - 1); }

/** No-op — notifications are now handled entirely by backend web push. */
export function clearAgentNotified(_agentId) {}
