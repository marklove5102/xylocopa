import { useState, useEffect } from "react";
import { fetchProjects } from "../lib/api";

/**
 * Shared hook for loading the project list.
 * Optionally polls at the given interval (ms).
 */
export default function useProjects(pollInterval = 0) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await fetchProjects();
        if (!cancelled) {
          setProjects(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();

    let interval;
    if (pollInterval > 0) {
      interval = setInterval(load, pollInterval);
    }

    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [pollInterval]);

  return { projects, loading, error };
}
