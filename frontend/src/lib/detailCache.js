// Module-level caches for dynamic-route detail pages.
//
// These pages (`/projects/:name`, `/tasks/:id`) mount fresh on every
// navigation. Without a cache, re-entering a page shows a loading
// state until 4 parallel fetches resolve — visible as a flash even
// when the data hasn't changed. The keep-mounted main tabs (Projects/
// Agents/Tasks/Git) avoid this because they survive navigation; the
// detail pages don't, so we stash their data here.
//
// Pattern (cache-first + background refetch):
//   const cached = projectDetailCache.get(name);
//   if (cached) {
//     // Render from cache immediately
//     setProject(cached.project); setAgents(cached.agents); ...
//     setLoading(false);
//   }
//   // Always fetch fresh in the background
//   const fresh = await fetchEverything();
//   projectDetailCache.set(name, fresh);
//   setProject(fresh.project); ...
//
// Lifetime: in-memory only, lost on full page reload. That's fine —
// the SW precache + browser http cache handle cold-start latency.
//
// Invalidation: callers should invalidate on user-driven mutations
// (rename, archive, delete) so stale data doesn't paint after the
// action completes. Background polls are not invalidations — they
// just overwrite the entry.

function makeCache() {
  const store = new Map();
  return {
    get(key) { return store.get(key); },
    set(key, value) { store.set(key, { ...value, ts: Date.now() }); },
    invalidate(key) { store.delete(key); },
    clear() { store.clear(); },
    size() { return store.size; },
  };
}

// Keys: project name. Value shape: { project, agents, stats, bookmarks, ts }
export const projectDetailCache = makeCache();

// Keys: task id. Value shape: { task, related, ts }
export const taskDetailCache = makeCache();
