# Architecture

A contributor's map of the Xylocopa codebase. The goal is not to re-document
what the code already says, it's to surface the non-obvious invariants that
you need to know before making changes.

## Overview

Xylocopa is a web UI that orchestrates Claude Code processes running inside
tmux sessions. A FastAPI backend (`orchestrator/`) tracks agent state in
SQLite, wires hooks into each agent's `settings.local.json`, and serves a
React frontend (`frontend/`). Agents run in isolated git worktrees. Users
interact through the web UI; `tmux attach` still works in parallel on the
same session.

**Tech stack:** Python 3.11+ (FastAPI, SQLAlchemy), React 19 (Vite, TanStack
Query, Tailwind), SQLite, tmux.

## Backend layout (`orchestrator/`)

| File | Role |
|---|---|
| `main.py` | FastAPI entrypoint + lifespan (startup/shutdown, background tasks) |
| `agent_dispatcher.py` | Per-agent lifecycle: spawn tmux, sync loop, notifications, queued messages |
| `sync_engine.py` | JSONL → DB message sync (pointer-based, incremental) |
| `display_writer.py` | DB → per-agent display JSONL (what the frontend actually reads) |
| `routers/` | FastAPI routers, `agents.py`, `hooks.py`, `projects.py`, `tasks.py`, … |
| `hooks/pretooluse-safety.py` | Local safety hook, hard-blocks `rm -rf`, `git push --force`, `DROP TABLE`, etc. |
| `hooks/session-start.sh` | Global SessionStart hook installed into `~/.claude/settings.json` |
| `models.py` | SQLAlchemy ORM (Agent, Message, Project, Task, …) |
| `schemas.py` | Pydantic request/response models |
| `permissions.py` | In-memory permission manager for supervised (non-Auto) agents |
| `notify.py` / `push.py` | Web Push (VAPID) notifications |
| `mcp_server.py` | MCP server exposing cross-session reference tool |

## Message sync pipeline

Content flows through **four distinct layers**. Understanding this pipeline
is the single most important thing before touching anything in
`sync_engine.py`, `display_writer.py`, or `routers/hooks.py`.

```
┌──────────┐   hook calls     ┌────────────┐   flush_agent    ┌──────────────┐   HTTP fetch    ┌─────────┐
│  JSONL   │───wake_sync─────▶│     DB     │─────────────────▶│ display file │────────────────▶│  WebUI  │
│ (source) │                  │ (messages) │                  │ (per-agent)  │                 │         │
└──────────┘                  └────────────┘                  └──────────────┘                 └─────────┘
 ~/.claude/projects/           SQLite                           data/display/                    AgentChatPage
  <proj>/<session>.jsonl                                        {agent_id}.jsonl
```

### Layer 1, JSONL (source of truth)

Claude Code writes a session log at
`~/.claude/projects/<project>/<session>.jsonl`. **Never edit this directly.**
For worktree sessions, always use
`AgentDispatcher._resolve_session_jsonl()` (`agent_dispatcher.py:915`), bare
`session_source_dir()` misses worktree-specific paths.

### Layer 2, DB (parsed messages)

`orchestrator/sync_engine.py` imports JSONL turns into the DB **incrementally**,
tracking position with `Agent.last_turn_count`. Three public entry points:

- **`sync_import_new_turns`** (line 396), the **sole** JSONL→message creation
  path. Produces USER / AGENT / SYSTEM messages via internal helpers
  `_promote_or_create_user_msg`, `_create_agent_msg`, `_create_system_msg`.
- **`sync_full_scan`** (line 677), **read-only** audit. Never creates or
  updates regular messages; only deletes orphaned messages on compact.
- **`trigger_sync`** (line 829), public wake-up that calls
  `AgentDispatcher.wake_sync(agent_id)`.

> **Exception to the "sole path" rule:** permission request/grant cards at
> `routers/hooks.py:708–722` and `908–922` create `Message(role=AGENT)`
> directly. These are synthetic UI widgets, not JSONL-sourced content, and
> are flushed immediately after insertion. **Don't extend this pattern for
> regular content, if it came from Claude, it goes through `sync_engine`.**

### Layer 3, display file (frontend-readable)

`orchestrator/display_writer.py` writes per-agent JSONL files to
`data/display/{agent_id}.jsonl`. Append-only, ordered by
`Message.display_seq`. **The file write happens before the DB commit**: if
the DB fails, `display_seq` stays NULL and the next flush retries (frontend
deduplicates by message id). Public API:

- `flush_agent` (line 162), append undisplayed messages
- `update_last` (line 249), append replacement line for streaming updates
  (dedup via `_replace`)
- `rebuild_agent` (line 286), reset `display_seq`, truncate, re-flush all
  (used after compact)
- `delete_agent` (line 319), remove the file
- `startup_rebuild_all` (line 330), rebuild for all active agents on server
  start

### Layer 4, WebUI

`GET /api/agents/{agent_id}/display` (`routers/agents.py:2379`) streams the
display file with `offset` / `tailBytes` params for incremental fetch. The
frontend `fetchDisplay(agentId, ...)` (`frontend/src/lib/api.js:290`) is
called from `AgentChatPage.jsx` for initial load and refresh. WebSocket is
used for **signaling only** ("something changed for agent X"); chat content
is always re-fetched from the display file, **never pushed as WS payload**.

### Sync pipeline invariants (critical)

1. **`wake_sync` is the single content-sync entry point.** All hooks funnel
   through `AgentDispatcher.wake_sync(agent_id)` (`agent_dispatcher.py:2452`),
   which wakes the per-agent sync loop (or restarts it via
   `_ensure_sync_running` if it died). Hook handlers never create JSONL-sourced
   messages directly.
2. **Incremental, pointer-based.** `Agent.last_turn_count` tracks where the
   sync left off. Only compact/clear/new-conversation events trigger
   `sync_full_scan`, which resets the pointer.
3. **Display file is downstream of DB, and the frontend is downstream of the
   display file.** Don't short-circuit either edge. New message kinds need
   to flush through `display_writer` before they're visible in the UI.

## MCP server, cross-session reference

`orchestrator/mcp_server.py` runs as a stdio MCP server per-agent (spawned
via `.mcp.json`). It exposes three tools: `list_sessions`, `read_session`,
`create_task`.

### Which layer does the MCP server read?

The MCP `read_session` tool reads **Layer 1 (raw JSONL)**: it locates the
Claude Code session file directly, parses turns via `jsonl_parser.py`, and
returns formatted markdown. It does **not** read the display file or DB.

### Reading chat history, which layer to use

External consumers (MCP tools, analysis scripts, other agents) that need
chat history should pick the right layer based on use case:

| Layer | Size | Access | Best for |
|---|---|---|---|
| **L3, display file** | ~6–12% of L1 | File read (`data/display/{agent_id}.jsonl`) | **Recommended default.** Complete, curated, self-contained. No DB access needed. Already stripped of thinking blocks and tool noise. |
| **L2, DB** | ~1–4% of L1 | SQLite query (`data/orchestrator.db`, table `messages`) | Structured queries, filter by role, time range, status. Smallest, but requires SQLite access. |
| **L1, JSONL** | 100% (baseline) | File read (`~/.claude/projects/<encoded>/<session>.jsonl`) | Full fidelity, includes thinking, tool I/O, raw API payloads. What `read_session` currently uses. Too large and noisy for most consumers. |
| **L4, WebUI** | last ~50 KB | HTTP (`/api/agents/{id}/display?tail_bytes=50000`) | Live UI only. Truncated by default, **do not use for complete history.** |

**Rule of thumb:** if you need the full conversation in a readable form,
**read the display file**: it's one self-contained JSONL file per agent,
typically 6–12% of the raw JSONL size, with role/timestamp/metadata on
every line. The WebUI endpoint tails the same file with a 50 KB byte
window; don't rely on it for completeness.

### Display file format

Each line in `data/display/{agent_id}.jsonl` is a JSON object:

```json
{"id": "...", "seq": 42, "role": "agent", "kind": "text", "content": "...",
 "source": "jsonl", "status": "completed", "metadata": {...},
 "created_at": "...", "completed_at": "...", "delivered_at": "..."}
```

Last-occurrence-wins by `id`, streaming updates and delivery-status
changes append replacement lines with `_replace: true`. Consumers should
dedup by `id` (keep last).

## Hooks

Each agent's `settings.local.json` is written by
`routers/agents.py:_write_agent_hooks_config` (line 160) on agent start.
Most hooks are HTTP calls into `routers/hooks.py`; one is a local script.

| Event | Type | Target | Purpose |
|---|---|---|---|
| `PreToolUse` (`Bash\|Write\|Edit`) | command | `hooks/pretooluse-safety.py` | Hard-block destructive ops |
| `PreToolUse` (all) | http | `/api/hooks/agent-tool-activity` | Broadcast tool activity → UI |
| `PreToolUse` (all) | http | `/api/hooks/agent-permission` | Supervised-mode permission gate (24h timeout) |
| `PostToolUse` / `PostToolUseFailure` | http | `/api/hooks/agent-tool-activity` | Tool completion / failure |
| `SubagentStart` / `SubagentStop` | http | `/api/hooks/agent-tool-activity` | Subagent lifecycle |
| `Notification` (`permission_prompt`) | http | `/api/hooks/agent-tool-activity` | Native CC permission prompts |
| `PreCompact` / `PostCompact` | http | `/api/hooks/agent-tool-activity`, `/agent-post-compact` | Compact lifecycle |
| `PermissionRequest` | http | `/api/hooks/agent-permission-request` | Auto-allow native CC prompts (24h timeout) |
| `Stop` | http | `/api/hooks/agent-stop` | Wake sync loop at turn end |
| `SessionEnd` | http | `/api/hooks/agent-session-end` | Mark loop completed, wake sync |
| `UserPromptSubmit` | http | `/api/hooks/agent-user-prompt` | Mark queued message delivered |

**Global `SessionStart` hook** is separate: written to
`~/.claude/settings.json` (not project-level) by `_write_global_session_hook`
(`routers/agents.py:359`), installed during lifespan (`main.py:198`). Fires
for **every** Claude Code process on the host, that's how the orchestrator
discovers sessions it didn't spawn.

**`pretooluse-safety.py`** (local `command` hook, enforced even when an agent
runs with `--dangerously-skip-permissions`) denies:

- `rm -rf` (any flag combination containing both `r` and `f`)
- `git push --force` / `-f`
- `git reset --hard` outside worktrees (allowed inside `.claude/worktrees/`)
- `git clean -f`, `git checkout -- .`, `git restore .`
- `DROP TABLE` / `TRUNCATE` (case-insensitive)
- `Write` / `Edit` to any path outside `cwd`

## Frontend layout (`frontend/src/`)

| Dir | Role |
|---|---|
| `pages/` | Route components (`AgentChatPage`, `ProjectDetailPage`, `NewPage`, `NewTaskPage`, …) |
| `components/` | Shared UI primitives |
| `components/cards/` | Interactive chat cards (plan review, permission request, inbox items) |
| `lib/api.js` | HTTP client. `fetchDisplay` reads the per-agent display JSONL |
| `lib/ws.js` | WebSocket client for agent-state signaling |

Data flow: WebSocket announces "agent X changed"; frontend re-fetches the
display file tail via `offset` / `tailBytes`. Chat content is never pushed
as WS payload.

## Key invariants & gotchas

Things that will bite you if you don't know them (all verified current
against the code as of writing):

1. **Worktree session resolution.** Always use
   `AgentDispatcher._resolve_session_jsonl()` (`agent_dispatcher.py:915`)
   bare `session_source_dir()` misses worktree session files. Grep for
   callers before changing its contract.

2. **tmux pane matching.** `xy-{agent_id[:8]}` is the canonical session
   name. Legacy `ah-{agent_id[:8]}` is still recognized for in-flight
   upgrade compatibility. Constants and matching logic at
   `route_helpers.py:196–210` (`TMUX_SESSION_PREFIX`,
   `TMUX_SESSION_LEGACY_PREFIX`, `tmux_session_candidates()`).

3. **CWD → project matching.** Use
   `cwd == proj or cwd.startswith(proj + "/")` (see
   `agent_dispatcher.py:1348, 1395` and `routers/hooks.py:1298`). Plain `==`
   misses worktree subdirectories.

4. **SQLAlchemy `metadata` is reserved.** If you need a column named
   `metadata`, use an alt Python attribute with an explicit column name.
   Example at `models.py:194`:
   `meta_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)`.

5. **Queued message dispatch.** The dispatcher is **sync_engine**, not the
   stop hook itself. Flow: message enters DB as `PENDING` → Claude's turn
   ends and writes a `stop_hook_summary` entry in JSONL → `sync_engine.py:609–639`
   detects it during the next sync tick → calls
   `AgentDispatcher.dispatch_pending_message()` → `send_tmux_message()`
   pastes into the tmux pane → `UserPromptSubmit` hook
   (`routers/hooks.py:135`) marks the message `DELIVERED`. The stop hook's
   job is just to wake sync; the detection and dispatch live in
   `sync_engine`.

6. **When fixing a shared helper, grep ALL call sites.** Helpers like
   `_resolve_session_jsonl`, `tmux_session_candidates`, and `wake_sync`
   have many callers, a contract change silently breaks half the system.

7. **Don't name tmux sessions with the `xy-` or `ah-` prefix.**
   User-created tmux sessions with either prefix will be incorrectly claimed
   by the orchestrator's sync discovery.
