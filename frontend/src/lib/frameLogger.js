// Frame-by-frame DOM mutation logger.
//
// Toggle on:  localStorage.setItem("ah:frame-log", "1"); location.reload();
// Toggle off: localStorage.removeItem("ah:frame-log"); location.reload();
//
// Listens to MutationObserver on document.body (subtree, attributes,
// childList) and ResizeObserver on document.body. Each animation frame,
// summarizes any accumulated changes and writes them via clog so they
// land in logs/frontend-debug.log. Frames with no DOM mutation produce
// no output — so the log is a sparse "what visually changed when" trace.
import { clog } from "./api";

function nodeTag(n) {
  if (!n) return "?";
  if (n.nodeType === 3) return "#text";
  const tag = (n.nodeName || "?").toLowerCase();
  const id = n.id ? `#${n.id}` : "";
  const cls = typeof n.className === "string" && n.className ? `.${n.className.split(/\s+/).slice(0, 2).join(".")}` : "";
  const dataProj = n.getAttribute?.("data-project-name");
  const dataAgent = n.getAttribute?.("data-agent-id");
  const extra = dataProj ? `[proj=${dataProj}]` : dataAgent ? `[agent=${String(dataAgent).slice(0, 8)}]` : "";
  return `${tag}${id}${cls}${extra}`;
}

function summarizeMutations(muts) {
  const counts = new Map();
  for (const m of muts) {
    let key;
    if (m.type === "attributes") {
      const tag = nodeTag(m.target);
      const attr = m.attributeName;
      let val = "";
      if (attr === "class") {
        const cls = m.target.className?.toString?.() || "";
        val = ` "${cls.slice(0, 60)}${cls.length > 60 ? "…" : ""}"`;
      } else if (attr === "style") {
        const stl = m.target.getAttribute?.("style") || "";
        val = ` "${stl.slice(0, 60)}${stl.length > 60 ? "…" : ""}"`;
      } else if (attr === "hidden") {
        val = ` ${m.target.hasAttribute?.("hidden") ? "ON" : "OFF"}`;
      }
      key = `attr:${attr} on ${tag}${val}`;
    } else if (m.type === "childList") {
      const tag = nodeTag(m.target);
      const adds = m.addedNodes.length;
      const rems = m.removedNodes.length;
      // Sample one added/removed for context
      const sample = adds > 0 ? nodeTag(m.addedNodes[0]) : rems > 0 ? nodeTag(m.removedNodes[0]) : "";
      key = `child:+${adds}/-${rems} under ${tag}${sample ? ` (e.g. ${sample})` : ""}`;
    } else {
      key = `${m.type} on ${nodeTag(m.target)}`;
    }
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  // Sort by count desc, take top 8 to keep lines readable
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([k, v]) => (v > 1 ? `${v}× ${k}` : k))
    .join(" | ");
}

export function setupFrameLogger() {
  if (typeof window === "undefined") return;
  if (localStorage.getItem("ah:frame-log") !== "1") return;

  const pending = [];
  const mo = new MutationObserver((muts) => {
    for (const m of muts) pending.push(m);
  });

  // Wait for body to exist
  const start = () => {
    if (!document.body) {
      requestAnimationFrame(start);
      return;
    }
    mo.observe(document.body, {
      attributes: true,
      childList: true,
      subtree: true,
      characterData: false,
    });

    let frame = 0;
    let lastT = performance.now();
    const tick = () => {
      frame++;
      const now = performance.now();
      const dt = now - lastT;
      lastT = now;
      if (pending.length > 0) {
        const summary = summarizeMutations(pending);
        const n = pending.length;
        pending.length = 0;
        clog(`[frame ${frame} +${dt.toFixed(0)}ms] ${n} mut: ${summary}`);
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    clog("[frame-log] enabled — clear localStorage 'ah:frame-log' and reload to disable");
  };
  start();
}
