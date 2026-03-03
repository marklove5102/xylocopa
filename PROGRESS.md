# PROGRESS.md
> Read this file at the start of every task. Append only, never delete entries.
> Updated when tasks complete — contains what worked, what failed, and why.

## cc-orchestrator — Lessons Learned

<!-- Entry format:
### YYYY-MM-DD | Task: {title} | Status: success/abandoned
- What: (one line summary)
- Attempts: (what was tried)
- Resolution: (what finally worked)
- Lesson: (what future agents should know)
-->

### 2026-02-23 | Task: Phase 1 Scheduler Core (1.1–1.4) | Status: success

### What was done
- **1.1 Database Schema**: models.py (Task, Project, SystemConfig tables), database.py (SQLite WAL mode, session factory), config.py (env vars)
- **1.2 FastAPI CRUD**: Full task lifecycle (create/list/get/cancel/retry), project listing, enhanced health check, Pydantic schemas, registry.yaml loading on startup
- **1.3 Worker Manager**: Subprocess lifecycle management — start/stop/logs/status/cleanup, resource limits
- **1.4 Task Dispatcher**: Async scheduling loop with harvest/timeout/retry/assign phases, startup crash recovery, concurrency limits (global + per-project)

### Problems encountered
- Test tasks kept retrying because .env has placeholder API keys

### Solutions
- Cancelled test tasks manually; auto-retry stops at MAX_RETRIES=3

### Lessons learned
- SQLAlchemy `expire_on_commit=False` is essential for reading task fields after commit in the same session
- SQLite WAL mode + `check_same_thread=False` needed for async dispatcher + sync API sharing the same DB
- `datetime.now(timezone.utc)` instead of `datetime.utcnow()` to avoid naive datetime comparison issues

### 2026-02-24 | Task: Session Persistence + Auth Simplification | Status: success

### What was done
1. **Session persistence**: Session files and refreshed tokens survive restarts. `--resume` works across restarts.
2. **Auth simplification**: Switched to `CLAUDE_CODE_OAUTH_TOKEN` env var (generated via `claude setup-token`, valid ~1 year). Simplified credential management.

### Problems encountered
- `plan_manager.py` (since removed) also imported old config vars — missed on first pass

### Solutions
- Updated all module imports alongside worker_manager.py

### Lessons learned
- `CLAUDE_CODE_OAUTH_TOKEN` is the officially recommended auth method — eliminates credential file management entirely
- When removing config vars, grep the entire codebase for imports — not just the file you're working on
- Plan mode was later removed entirely (commit ad1c2c9) — only INTERVIEW and AUTO modes remain

### 2026-02-26 | Task: Worktree Session Resolution + tmux Recovery | Status: success

### What was done

**Worktree session directory resolution (critical bug fix)**
- Claude Code stores session JSONL files based on the CWD where it launched, not the project root
- Worktree agents launch from `{project}/.claude/worktrees/{name}/`, so their sessions end up in a completely different `~/.claude/projects/` subdirectory
- Created `_resolve_session_jsonl(session_id, project_path, worktree)` helper that checks both project root and worktree session dirs
- Fixed **13 call sites** across agent_dispatcher.py that used `session_source_dir(project_path)` directly:
  - `_dispatch_pending_messages()` — resume pre-check
  - `_sync_session_loop_inner()` — session parsing
  - `import_session_history()` — history import
  - `_reap_dead_agents()` — liveness freshness check
  - `_detect_successor_session()` — scans both session dirs for successors
  - `_spawn_successor_agent()` — new session parsing
  - `_dedup_pane_agents()` — mtime comparison
  - `_recover_agents()` — recovery JSONL path + liveness
  - `_auto_detect_cli_sessions()` — scans worktree session dirs + Tier 0 agent lookup

**tmux recovery pane assignment (critical bug fix)**
- On server restart, `_recover_agents()` re-detects tmux panes for each agent
- `_detect_tmux_pane_for_session()` filters out panes owned by non-STOPPED agents via `_get_pane_owner()`
- During recovery, agents' OWN panes get filtered (they're non-STOPPED), making them match wrong panes
- Multiple agents got assigned the same pane → dedup conflict → one agent force-stopped
- Fix: Use tmux session name `ah-{agent_id[:8]}` for definitive matching (built `session_name_to_pane` dict once at startup)

**CWD matching for worktree agents (bug fix)**
- 4 locations used exact `cwd == project_path` comparison
- Worktree agent CWDs like `{project}/.claude/worktrees/streaming` failed this check
- Fix: subdirectory matching `cwd == proj or cwd.startswith(proj + "/")`

**Auto-detect Tier 0 matching (enhancement)**
- `_auto_detect_cli_sessions()` used PID/session-file matching, which sometimes picked the wrong stopped agent
- Added Tier 0: if tmux session name is `ah-{id}`, directly look up that agent by ID prefix

**Schema/API fixes**
- Added `session_id` to `AgentOut` and `AgentBrief` schemas
- Added `AgentStatus.SYNCING` to active agent count queries
- Added `metadata` column to messages table (migration in database.py)

### Problems encountered
1. Worktree agent had 5 messages from wrong session file (looked correct because first message happened to match)
2. Pane dedup caused silent agent termination on every restart
3. Wrong agent revived by auto-detect when multiple stopped agents existed for same project
4. `session_source_dir()` was called in 13+ places, each one a potential worktree bug

### Solutions
1. Created unified `_resolve_session_jsonl()` that checks both dirs, then did a comprehensive audit of ALL call sites
2. Used tmux session name as authoritative pane→agent mapping (not PID/session heuristics)
3. Added Tier 0 matching in auto-detect using tmux session name
4. Systematic grep + fix of every `session_source_dir()` call site

### Lessons learned
- **Claude Code session directory isolation**: Sessions are stored under `~/.claude/projects/{path-encoded-cwd}/`. Worktree CWD differs from project root → different directory. This is the #1 source of bugs for worktree features.
- **tmux session names are authoritative**: `ah-{agent_id[:8]}` is more reliable than any PID/file heuristic for pane matching. Always prefer session name matching over other methods.
- **Self-exclusion during recovery**: When recovering agents, their own panes appear "owned" by themselves (non-STOPPED), causing `_get_pane_owner()` to filter them out. Must handle this edge case.
- **Exact CWD matching breaks worktrees**: Always use subdirectory matching. A worktree agent's CWD is a subdirectory of the project.
- **Audit pattern**: When fixing a helper function bug, grep for ALL call sites of the old pattern. Don't assume you found them all — `session_source_dir` appeared 13+ times.
- **Wrong session file ≠ empty file**: A wrong session file can appear to work (has messages), just from a different session. Validate session IDs match, not just file existence.

### 2026-02-26 | Task: Notification + Streaming Investigation | Status: success

### What was done
- Audited all 6 `send_push_notification` call sites — **all are properly guarded** with `_is_agent_in_use()` check
- `_is_agent_in_use()` checks both WebSocket viewing state and tmux `session_attached`
- `_refresh_pane_attached()` runs tmux query and caches results in `_pane_attached` dict
- Verified tmux shows `session_attached=1` for active panes

### Still investigating
- Notification suppression may have race condition: `_refresh_pane_attached()` is called at start of dispatcher loop, but notification decisions happen later — if tmux state changes between calls, stale data could cause false notifications
- Streaming visibility may be intermittent due to sync loop timing or WebSocket connection state

### 2026-03-03 | Task: Task System v2 + Subagent Tracking + Multi-bugfix | Status: success

### What was done

**Task system v2 improvements**
- Added `GET /api/v2/tasks/counts` endpoint — perspective-based counts (queue/executing/review/done) + weekly completion stats
- Added `_get_session_slug()` for detecting `/clear` transitions via slug matching (increased search depth from 5→20 lines)
- Fixed `_get_session_pid()` to fall through on dead PIDs instead of early return
- Integrated task stats into MonitorContext (30s polling) + wired into PageHeader
- State machine: added `InvalidTransitionError`, expanded valid transitions (EXECUTING→COMPLETE, etc.)
- WebSocket reconnect: seed `generating_agents` on reconnect
- Legacy dispatcher: skip v2 tasks in legacy dispatcher loop
- New UI components: EffortSelector, ModelSelector, PromptInputBar, DoneView DONE_COMPLETED count

**Subagent detection and tracking (2a26146)**
- Claude Code spawns subagents (Explore, Plan, etc.) — now detected and tracked
- Scans `{session_dir}/subagents/agent-*.jsonl` for subagent metadata
- Creates lightweight Agent records with `parent_id` and `is_subagent=True`
- Imports subagent conversation turns into Messages
- API: subagents filtered from main list, attached to parent detail view, cascade stop

**Successor detection after ExitPlanMode /clear (56614ed)**
- `_get_session_pid()` only matched `.claude.json.tmp.{PID}` pattern
- After `/clear`, new sessions may only write source code tmp files (e.g. `main.py.tmp.{PID}.{ts}`)
- Added broader fallback matching any `{file}.tmp.{PID}.{timestamp}` pattern
- Fixed agents stuck in SYNCING forever after "clear context & bypass"

**Invalid model name fix (90e7ec1)**
- `registry.yaml` loader used hardcoded fallback `claude-sonnet-4-5-20250514` — not a valid model ID
- Added `VALID_MODELS` set in config.py, validation in create_agent/launch/load_registry
- Startup migration to fix 10 projects + 4 agents with invalid models in live DB

**Other bug fixes (via worktree agents)**
- Fix project task counts: use Task table instead of Message counts (ca303be)
- Fix back button unclickable when toast overlaps (2104949) — z-index issue
- Fix voice auto-start broken by React StrictMode double-mount (93cd06d)
- Auto-stop agent after merge task completes (ae5b16e) — was left in IDLE state

### Problems encountered
1. Session slug search only scanned first 5 lines — insufficient for some sessions
2. Dead PID in `_get_session_pid()` caused early return → successor never found
3. Hardcoded invalid model name propagated to 10 projects silently
4. Merge task completion left agents in IDLE without cleanup

### Lessons learned
- **Model validation at boundaries**: Always validate model names on input (create/launch/load), not just output. Add a `VALID_MODELS` set and check against it.
- **Slug-based session matching**: After `/clear`, session IDs change but the slug (human-readable session name) persists. Slug matching is more robust than PID matching for detecting session continuity.
- **Subagent lifecycle**: Claude Code subagents write to `{session_dir}/subagents/agent-{uuid}.jsonl`. They have their own session IDs and conversation turns. Must parse these separately from the parent session.
- **Worktree agent delegation works**: 6 bug fixes were completed by worktree agents in parallel — the merge-and-stop lifecycle is now reliable enough for routine fixes.
