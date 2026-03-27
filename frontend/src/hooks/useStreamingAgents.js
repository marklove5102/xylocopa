import { useExecutingAgents } from "../contexts/ExecutingAgentsContext";

/**
 * Track which agents are actively working.
 * Thin re-export of the global ExecutingAgentsContext — all consumers
 * share the same state, surviving page navigation.
 * @returns {Set} activeAgents - Set of agent IDs currently active
 */
export function useStreamingAgents() {
  return useExecutingAgents();
}
