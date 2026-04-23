// Hierarchical back-navigation helpers.
//
// Every page has a level; forward navigation carries a nested state chain
// { from, fromState } so back can skip sibling/deeper pages and jump to the
// first ancestor at a shallower level.

export function pageLevel(path) {
  if (!path) return 0;
  const p = path.split("?")[0].split("#")[0];
  if (p.startsWith("/new")) return 3;
  if (/^\/agents\/[^/]+/.test(p)) return 2;
  if (/^\/tasks\/[^/]+/.test(p)) return 2;
  if (/^\/projects\/[^/]+/.test(p)) return 1;
  return 0;
}

export function forwardState(location) {
  // If current location is a modal (react-router backgroundLocation pattern),
  // treat the background page as the effective parent so back skips the modal.
  const bg = location.state && location.state.backgroundLocation;
  if (bg) {
    return { from: bg.pathname + (bg.search || ""), fromState: bg.state || null };
  }
  return { from: location.pathname + location.search, fromState: location.state || null };
}

export function resolveBack(currentPath, state, fallback = "/agents") {
  const level = pageLevel(currentPath);
  let s = state;
  while (s && s.from && pageLevel(s.from) >= level) {
    s = s.fromState;
  }
  if (s && s.from) return { to: s.from, state: s.fromState || null };
  return { to: fallback, state: null };
}
