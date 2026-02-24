import { useState, useEffect } from "react";
import { fetchHealth } from "../lib/api";

/** Polls /api/health every 15s and returns the health object (or null while loading). */
export default function useHealthStatus() {
  const [health, setHealth] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        const data = await fetchHealth();
        if (!cancelled) setHealth(data);
      } catch {
        if (!cancelled) setHealth({ status: "error", db: "unknown", claude_cli: "unknown" });
      }
    };

    check();
    const interval = setInterval(check, 15000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  return health;
}
