import { createContext, useContext, useState, useEffect, useCallback } from "react";
import {
  fetchHealth as apiFetchHealth,
  fetchAgents as apiFetchAgents,
  fetchSystemStats,
  fetchStorageStats,
  fetchTokenUsage,
  fetchTaskCounts,
} from "../lib/api";
import usePageVisible from "../hooks/usePageVisible";

const MonitorContext = createContext(null);

const BG_INTERVAL = 5 * 60 * 1000; // 5-minute background refresh

export function MonitorProvider({ children }) {
  const visible = usePageVisible();
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(false);
  const [agents, setAgents] = useState([]);
  const [agentCounts, setAgentCounts] = useState({});
  const [sysStats, setSysStats] = useState(null);
  const [tokenUsage, setTokenUsage] = useState(null);
  const [storageStats, setStorageStats] = useState(null);
  const [taskStats, setTaskStats] = useState(null);
  const [monitorActive, setMonitorActive] = useState(false);

  const fetchHealth = useCallback(async () => {
    try {
      const data = await apiFetchHealth();
      setHealth(data);
      setHealthError(false);
    } catch (err) {
      console.error("MonitorContext: failed to fetch health:", err);
      setHealthError(true);
    }
  }, []);

  const fetchAgents = useCallback(async () => {
    try {
      const data = await apiFetchAgents("limit=200");
      setAgents(data);
      const counts = {};
      for (const a of data) counts[a.status] = (counts[a.status] || 0) + 1;
      setAgentCounts(counts);
    } catch (err) {
      console.error("MonitorContext: failed to fetch agents:", err);
    }
  }, []);

  const fetchSysStats = useCallback(async () => {
    try {
      setSysStats(await fetchSystemStats());
    } catch (err) {
      console.error("MonitorContext: failed to fetch system stats:", err);
    }
  }, []);

  const fetchUsage = useCallback(async () => {
    try {
      const data = await fetchTokenUsage();
      setTokenUsage(data);
    } catch (err) {
      console.error("MonitorContext: failed to fetch token usage:", err);
      // Mark as error so UI can show a degraded state instead of hiding
      setTokenUsage((prev) => prev ?? { _error: true });
    }
  }, []);

  const fetchStorage = useCallback(async () => {
    try {
      setStorageStats(await fetchStorageStats());
    } catch (err) {
      console.error("MonitorContext: failed to fetch storage stats:", err);
    }
  }, []);

  const fetchTasks = useCallback(async () => {
    try {
      setTaskStats(await fetchTaskCounts());
    } catch (err) {
      console.error("MonitorContext: failed to fetch task counts:", err);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await Promise.all([
      fetchHealth(), fetchAgents(),
      fetchSysStats(), fetchStorage(), fetchTasks(),
    ]);
  }, [fetchHealth, fetchAgents, fetchSysStats, fetchStorage, fetchTasks]);

  // Background warm-up: prefetch monitor data shortly after app mount and
  // keep it fresh every minute so the first/subsequent trips to MonitorPage
  // show everything instantly. Active fast-polling (5s) takes over once
  // MonitorPage mounts; this loop only runs while monitor is inactive.
  useEffect(() => {
    if (!visible || monitorActive) return;
    const initial = setTimeout(() => { refreshAll(); fetchUsage(); }, 2000);
    const id = setInterval(() => { refreshAll(); fetchUsage(); }, 60 * 1000);
    return () => { clearTimeout(initial); clearInterval(id); };
  }, [visible, monitorActive, refreshAll, fetchUsage]);

  // Initial fetch + background poll only when MonitorPage is active
  useEffect(() => {
    if (!visible || !monitorActive) return;
    refreshAll(); fetchUsage();
    const id = setInterval(refreshAll, BG_INTERVAL);
    return () => clearInterval(id);
  }, [visible, monitorActive, refreshAll, fetchUsage]);

  // Fast polling when MonitorPage is active and tab is visible
  useEffect(() => {
    if (!visible || !monitorActive) return;
    // Agents, sysStats: every 5s
    const fastId = setInterval(() => {
      fetchAgents(); fetchSysStats();
    }, 5000);
    // Health: every 10s
    const healthId = setInterval(fetchHealth, 10000);
    // Storage, task stats: every 30s
    const slowId = setInterval(() => {
      fetchStorage(); fetchTasks();
    }, 30000);
    // Token usage: every 10 minutes
    const usageId = setInterval(fetchUsage, 10 * 60 * 1000);
    return () => {
      clearInterval(fastId);
      clearInterval(healthId);
      clearInterval(slowId);
      clearInterval(usageId);
    };
  }, [visible, monitorActive, fetchAgents, fetchSysStats, fetchHealth, fetchStorage, fetchTasks, fetchUsage]);

  const activate = useCallback(() => setMonitorActive(true), []);
  const deactivate = useCallback(() => setMonitorActive(false), []);

  return (
    <MonitorContext.Provider value={{
      health, healthError, agents, agentCounts, sysStats, tokenUsage, storageStats, taskStats,
      refresh: refreshAll, refreshTokenUsage: fetchUsage, activate, deactivate,
    }}>
      {children}
    </MonitorContext.Provider>
  );
}

export function useMonitor() {
  const ctx = useContext(MonitorContext);
  if (!ctx) throw new Error("useMonitor must be used within MonitorProvider");
  return ctx;
}
