import { useHealthContext } from "../contexts/HealthContext";

/**
 * Returns the global system health snapshot (or null before first resolve).
 *
 * Backward-compatible wrapper around HealthContext: previously this hook
 * owned its own state + polling, which caused the OK chip to flicker on
 * every consumer mount (each chat-page open re-fetched /api/health). Now
 * the polling lives in HealthProvider; this hook just reads from it so
 * subsequent mounts see the already-resolved value.
 */
export default function useHealthStatus() {
  return useHealthContext();
}
