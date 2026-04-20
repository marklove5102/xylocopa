# TODO

Priority-ordered backlog. Move items between sections as priorities shift.
PROGRESS.md tracks completed work; this file tracks what's next.

## High

_(empty)_

## Medium

### Offline-robust adoption of externally-created CLI sessions
When a user runs `claude` outside the Xylocopa webapp, adoption depends entirely
on the `SessionStart` hook POSTing to `/api/hooks/agent-session-start` live.
If the backend is down at that exact moment, the session is lost to adoption
forever (until the user manually restarts the `claude` process).

**Observed.** 2026-04-19: backend was killed by systemd-oomd at 20:12; user
started `claude` in `/home/jyao073/xylocopa` at 21:58 (cwd matches the
registered `xylocopa` project); backend restarted at 21:59 via `./run.sh`.
The session ran fine but never surfaced in the unlinked-sessions UI because
the hook's HTTP POST at 21:58 hit connection-refused and the offline branch
in `orchestrator/hooks/session-start.sh` only writes a signal file when
`AGENT_ID` is non-empty (managed agent). Unmanaged sessions silently exit.

**Why Medium, not High.** Backend uptime is now materially better after the
pm2-systemd migration (oomd can no longer SIGKILL the vte-spawn scope that
pm2 was living in). This bug only bites during backend-down windows, which
should be rare going forward. But the failure mode is silent, so it's worth
fixing before the next time it matters.

**Fix A (small, ~40 lines).** Add an unmanaged-offline fallback to
`session-start.sh`: when the HTTP POST fails and `AGENT_ID` is empty, write
`/tmp/xy-pending-sessions/<session_id>.json` with `session_id`, `cwd`,
`tmux_pane`, and a timestamp. On backend startup, scan that directory and
replay each entry through the same `_write_unlinked_entry()` path the hook
handler uses, then unlink the files. Covers the exact failure above.

**Fix B (larger, true tmux polling).** The docstring at
`routers/hooks.py:1125` claims a "polling-based tmux scan fallback" exists
as a complement to the push path — it does not. Implement it: periodically
`tmux list-panes -a -F '#{pane_pid} #{session_name}'`, walk each pane's
child process tree for a `claude` executable, compare session names against
`xy-*`/`ah-*` prefix and the `agents.tmux_pane` column, and write unlinked
entries for the diff. This covers the "user never runs claude live while
backend is up" case too (e.g. started claude, claude restarts its own
session internally, hook retry window missed, etc.).

**Recommendation.** Ship Fix A first. Consider Fix B only if the silent-loss
pattern recurs despite Fix A, or if we want adoption to work for users whose
hooks are not installed at all.

## Low

### Project state reconciliation + orphan cleanup
Unify the two divergent project-listing endpoints (`/api/projects` reads DB,
`/api/projects/folders` scans filesystem) into a single reconcile pipeline,
and add a manually-triggered orphan cleanup script.

**Status.** The immediate user-visible symptom — xylocopa repo missing
from the Projects grid — was hand-patched on 2026-04-18 by deleting the
stale `agenthive` DB row and creating
`~/xylocopa-projects/xylocopa → /home/jyao073/xylocopa` symlink. This
TODO is structural prevention, not a pending bug.

**Background.** The grid page (`/api/projects/folders`,
`orchestrator/routers/projects.py:815`) lists filesystem dirs in
`PROJECTS_DIR` joined with DB stats. The picker (`/api/projects`, line 723)
reads DB rows filtered by `archived=False`. Projects whose `Project.path`
falls outside `PROJECTS_DIR` (e.g. xylocopa self-hosting) appear in the
picker but not the grid. Manual fs deletes leave DB orphans; manual fs
adds leave unregistered dirs. `registry.yaml` is a third source of truth
seeded into DB on startup (`main.py:79`), and `_remove_from_registry()`
writes back — so all three must stay in sync.

**Proposed design.**
- Single reconcile pass on app startup + manual refresh button:
  scan `PROJECTS_DIR` and DB together, classify into Active /
  Inactive (archived) / Unregistered (fs-only) / External (DB row, path
  outside PROJECTS_DIR but exists) / Orphan (DB row, path missing).
- One-way update direction: FS → DB → `registry.yaml`.
- Picker shows only Active. Grid shows Active + Inactive (Inactive
  cannot receive new tasks). Orphans live in a separate monitor view
  with cleanup actions.

**Orphan cleanup script (`orchestrator/reconcile.py`, dry-run + apply):**
- Project layer: missing fs path, dead symlinks, unregistered dirs,
  registry.yaml ↔ DB drift.
- FK orphans: `agents.project` / `tasks.project_name` → missing project;
  `messages.agent_id` → missing agent; `agents.task_id` → missing task;
  `starred_sessions.project` → missing.
- Session layer: `agents.session_id` → missing JSONL;
  `~/.claude/projects/<path>/` for deleted projects;
  starred sessions for missing JSONL.
- Residue: stale `xy-*` tmux sessions, `.trash/` entries older than
  N days (report only, no auto-purge), session_cache stale entries.

**Triggers for promoting to Medium/High.**
- A second fs/DB-divergence bug surfaces.
- Project count grows past ~100 (perf concern).
- Self-hosting / external-path projects become a regular pattern.

**Quick wins available without the full refactor.**
- Add union in folders endpoint: include DB rows whose `path` is not in
  PROJECTS_DIR, so xylocopa-style external projects show in the grid
  automatically without requiring a manual symlink.
