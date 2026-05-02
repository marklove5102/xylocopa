import { createContext, useContext, useMemo, useReducer, useCallback, useRef } from "react";

/**
 * Stage-2 PILOT — single source of truth for the agent list, read-only
 * for ProjectDetailPage; AgentsPage remains the only writer.
 *
 * State shape: { byId: Map<id, AgentBrief>, order: id[], version: number }
 *   - byId  : id → row, the canonical store
 *   - order : insertion order (most-recent prepended; matches the
 *             `[newAgent, ...prev]` semantic AgentsPage uses for
 *             agent_created)
 *   - version : monotonically incremented every reducer step so that
 *             memoized selectors (`useMemo`) can depend on it without
 *             paying for deep-equal checks
 *
 * Actions (dispatched via useAgentsActions(); split from the read
 * context so consumers that only call dispatch don't re-render on
 * every update — same pattern as Redux's connect with mapDispatch):
 *   - seed(list)           : full replace, used for initial fetch +
 *                            WS-reconnect resync
 *   - setMany(list, mode)  : 'merge' (default; preserves rows the API
 *                            didn't return — important for filtered
 *                            fetches that may shrink the response set)
 *                            or 'replace' (drops anything not in list)
 *   - prepend(brief)       : WS agent_created; dedup by id
 *   - patchOne(id, partial): WS agent_update; if id unknown, upserts a
 *                            partial row (handles direct-URL races for
 *                            AgentChatPage's eventual Stage-2b migration)
 *   - upsert(brief)        : single full row; reserved for Stage-2b's
 *                            AgentChatPage → store migration
 *   - remove(id)           : drop a row (delete flow)
 *
 * Read hooks:
 *   - useAgents(filter?)   : returns the filtered list, memoized on
 *                            `version` + filter identity
 *   - useAgent(id)         : returns one row from byId (or undefined)
 *
 * IMPORTANT: AgentsPage is currently the only writer. ProjectDetailPage
 * dispatches no mutations — it only reads. If a mutation path needs to
 * trigger a refetch, dispatch a window 'agents-data-changed' event;
 * AgentsPage already listens.
 */

const ACTION = {
  SEED: "seed",
  SET_MANY: "set_many",
  PREPEND: "prepend",
  PATCH_ONE: "patch_one",
  UPSERT: "upsert",
  REMOVE: "remove",
};

const initialState = {
  byId: new Map(),
  order: [],
  version: 0,
};

function reducer(state, action) {
  switch (action.type) {
    case ACTION.SEED: {
      const list = Array.isArray(action.list) ? action.list : [];
      const byId = new Map();
      const order = [];
      for (const a of list) {
        if (!a?.id) continue;
        if (!byId.has(a.id)) order.push(a.id);
        byId.set(a.id, a);
      }
      return { byId, order, version: state.version + 1 };
    }

    case ACTION.SET_MANY: {
      const list = Array.isArray(action.list) ? action.list : [];
      const mode = action.mode === "replace" ? "replace" : "merge";
      if (mode === "replace") {
        // Replace mode is the same as seed — drop any row not in `list`.
        return reducer(state, { type: ACTION.SEED, list });
      }
      // Merge: keep existing rows the API didn't return, update/insert
      // the ones it did. Order rule: existing rows keep their slot;
      // new rows append at the front (matches WS prepend semantics).
      const byId = new Map(state.byId);
      const order = state.order.slice();
      for (const a of list) {
        if (!a?.id) continue;
        if (!byId.has(a.id)) order.unshift(a.id);
        byId.set(a.id, a);
      }
      return { byId, order, version: state.version + 1 };
    }

    case ACTION.PREPEND: {
      const brief = action.brief;
      if (!brief?.id) return state;
      if (state.byId.has(brief.id)) return state; // dedup
      const byId = new Map(state.byId);
      byId.set(brief.id, brief);
      const order = [brief.id, ...state.order];
      return { byId, order, version: state.version + 1 };
    }

    case ACTION.PATCH_ONE: {
      const { id, partial } = action;
      if (!id) return state;
      const byId = new Map(state.byId);
      const existing = byId.get(id);
      if (existing) {
        // Merge fields, preserving keys partial doesn't carry. Special-case
        // undefined: a deliberate "leave-alone" signal from WS payloads
        // that omit fields they didn't change.
        const next = { ...existing };
        for (const k of Object.keys(partial || {})) {
          if (partial[k] !== undefined) next[k] = partial[k];
        }
        byId.set(id, next);
        return { byId, order: state.order, version: state.version + 1 };
      }
      // Unknown id: upsert as a partial row so a direct-URL load that
      // races the seed still gets the WS update applied. Order rule:
      // append at the front (same as PREPEND).
      byId.set(id, { id, ...(partial || {}) });
      const order = [id, ...state.order];
      return { byId, order, version: state.version + 1 };
    }

    case ACTION.UPSERT: {
      const brief = action.brief;
      if (!brief?.id) return state;
      const byId = new Map(state.byId);
      const order = state.order.slice();
      if (!byId.has(brief.id)) order.unshift(brief.id);
      byId.set(brief.id, brief);
      return { byId, order, version: state.version + 1 };
    }

    case ACTION.REMOVE: {
      const { id } = action;
      if (!id || !state.byId.has(id)) return state;
      const byId = new Map(state.byId);
      byId.delete(id);
      const order = state.order.filter((x) => x !== id);
      return { byId, order, version: state.version + 1 };
    }

    default:
      return state;
  }
}

const AgentsStateContext = createContext(null);
const AgentsActionsContext = createContext(null);

export function AgentsProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  // Stable actions object — referentially stable so consumers using it in
  // useEffect dep arrays don't re-fire on every state change.
  const actionsRef = useRef(null);
  if (!actionsRef.current) {
    actionsRef.current = {
      seed: (list) => dispatch({ type: ACTION.SEED, list }),
      setMany: (list, mode) => dispatch({ type: ACTION.SET_MANY, list, mode }),
      prepend: (brief) => dispatch({ type: ACTION.PREPEND, brief }),
      patchOne: (id, partial) => dispatch({ type: ACTION.PATCH_ONE, id, partial }),
      upsert: (brief) => dispatch({ type: ACTION.UPSERT, brief }),
      remove: (id) => dispatch({ type: ACTION.REMOVE, id }),
    };
  }

  return (
    <AgentsStateContext.Provider value={state}>
      <AgentsActionsContext.Provider value={actionsRef.current}>
        {children}
      </AgentsActionsContext.Provider>
    </AgentsStateContext.Provider>
  );
}

// Fallback so consumers rendered outside the provider (e.g. /login) don't crash.
const _fallbackState = initialState;
const _fallbackActions = {
  seed: () => {},
  setMany: () => {},
  prepend: () => {},
  patchOne: () => {},
  upsert: () => {},
  remove: () => {},
};

/**
 * Read the (optionally filtered) agent list. Memoized on `version` so
 * the returned array identity is stable across renders that don't
 * actually change the underlying data — important because most consumers
 * pass it to a downstream useMemo that does heavy filter/sort work.
 *
 * @param {(a: AgentBrief) => boolean} [filter] optional predicate
 */
export function useAgents(filter) {
  const ctx = useContext(AgentsStateContext) || _fallbackState;
  const { byId, order, version } = ctx;
  return useMemo(() => {
    const out = [];
    for (const id of order) {
      const a = byId.get(id);
      if (!a) continue;
      if (filter && !filter(a)) continue;
      out.push(a);
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, filter]);
}

/** Read a single agent by id. */
export function useAgent(id) {
  const ctx = useContext(AgentsStateContext) || _fallbackState;
  return ctx.byId.get(id);
}

/** Get the dispatcher (stable identity). Use in writers — AgentsPage today. */
export function useAgentsActions() {
  return useContext(AgentsActionsContext) || _fallbackActions;
}
