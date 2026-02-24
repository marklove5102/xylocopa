# PROGRESS.md — Lessons Learned

> Each CC worker should append here after completing a task. Never make the same mistake twice.

---

## General Lessons

### Docker
- (to be filled)

### CC Instance Scheduling
- (to be filled)

### Frontend
- (to be filled)

---

## Task Log

(CC workers append below after each task, using this format)

## [2026-02-23] Task 0.1: Docker Environment Validation + Init Script | Project: cc-orchestrator

### What was done
- Verified existing scripts/init.sh covers all Task 0.1 requirements
- Added Docker version 24.0+ enforcement check (was only printing version, not validating)
- Made all scripts executable (chmod +x)
- Committed project scaffolding: .gitignore, .env.example, CLAUDE.md, TASKS.md, PROGRESS.md, QUICKSTART.md, scripts/

### Problems encountered
- init.sh existed but didn't enforce Docker 24.0+ minimum version — just printed version number

### Solutions
- Added `docker_major` extraction and numeric comparison to fail if < 24

### Lessons learned
- Always check that "version display" also means "version enforcement" — printing isn't validating

---

## [2026-02-23] Task 0.2: Worker Docker Image | Project: cc-orchestrator

### What was done
- Created worker/Dockerfile (Ubuntu 24.04, git, python3, nodejs, claude CLI, non-root user)
- Created worker/entrypoint.sh (accepts prompt + project dir, runs claude with --dangerously-skip-permissions)
- Created worker/.dockerignore
- COPY entrypoint.sh into image with correct ownership

### Problems encountered
- None

### Lessons learned
- entrypoint.sh needs to be COPY'd in Dockerfile with --chown for non-root user to execute it

---

## [2026-02-23] Task 0.3: Orchestrator Docker Image | Project: cc-orchestrator

### What was done
- Created orchestrator/Dockerfile (python:3.11-slim, git, curl, pip deps)
- Created orchestrator/requirements.txt (fastapi, uvicorn, sqlalchemy, docker SDK, etc.)
- Created orchestrator/main.py (minimal FastAPI app with /api/health endpoint, CORS, lifespan hooks)
- Created orchestrator/.dockerignore

### Problems encountered
- None

### Lessons learned
- Keep main.py minimal for Phase 0 — just health endpoint. Phase 1 adds CRUD and dispatcher.

---

## [2026-02-23] Task 0.4: Docker Compose Orchestration | Project: cc-orchestrator

### What was done
- Created docker-compose.yml with orchestrator + frontend services
- Defined cc-internal (service comms) and cc-worker-net (worker containers) networks
- cc-worker-net uses `name:` key so dynamically created containers can reference it by name
- 5 named volumes: cc-orch-db, cc-orch-backups, agenthive-projects, cc-git-bare, cc-logs
- Frontend placeholder: nginx with reverse proxy for /api/* and /ws/* to orchestrator
- Static landing page with dark theme and backend connectivity check
- Added projects/registry.yaml and project CLAUDE.md template

### Problems encountered
- logs/.gitkeep rejected by git add because logs/ is in .gitignore — skipped it

### Lessons learned
- Don't try to track directories that are in .gitignore, even with .gitkeep
- Use `name:` on Docker networks that need to be referenced by containers created outside compose
- Docker Compose only creates networks used by at least one service — unused network definitions are silently skipped. Orchestrator must be on cc-worker-net to talk to workers.

---

## [2026-02-23] Task 1.1–1.4: Phase 1 Scheduler Core | Project: cc-orchestrator

### What was done
- **1.1 Database Schema**: models.py (Task, Project, SystemConfig tables), database.py (SQLite WAL mode, session factory), config.py (env vars)
- **1.2 FastAPI CRUD**: Full task lifecycle (create/list/get/cancel/retry), project listing, enhanced health check (DB + Docker), Pydantic schemas, registry.yaml loading on startup
- **1.3 Worker Manager**: Docker SDK integration for container lifecycle — start/stop/logs/status/cleanup, resource limits, network isolation, shell-safe prompt quoting
- **1.4 Task Dispatcher**: Async scheduling loop with harvest/timeout/retry/assign phases, startup crash recovery, concurrency limits (global + per-project)

### Problems encountered
- Worker entrypoint.sh received wrong args when worker_manager passed `command=["bash", "-c", ...]` — Docker concatenates ENTRYPOINT + CMD, so entrypoint.sh got `bash` as `$1` and `-c` as `$2`
- Test tasks kept retrying because .env has placeholder API keys

### Solutions
- Override entrypoint in worker_manager: `entrypoint=["bash", "-c"]` bypasses the Dockerfile's ENTRYPOINT and runs the command string directly
- Cancelled test tasks manually; auto-retry stops at MAX_RETRIES=3

### Lessons learned
- When Dockerfile has ENTRYPOINT and you pass a command via Docker SDK, the command becomes ARGS to the entrypoint — use `entrypoint=` override to bypass
- SQLAlchemy `expire_on_commit=False` is essential for reading task fields after commit in the same session
- SQLite WAL mode + `check_same_thread=False` needed for async dispatcher + sync API sharing the same DB
- `datetime.now(timezone.utc)` instead of `datetime.utcnow()` to avoid naive datetime comparison issues

---

## [2026-02-23] Audit: Docker Authentication & Volume Mounts for CC Workers

### 1. Current Auth Method: OAuth Token Copy (Host → Container)

**Strategy**: Mount host `~/.claude/` read-only into a staging path, then `cp -a` into the container's writable HOME at startup.

**Flow** (`worker_manager.py`):
1. Host `~/.claude/` bind-mounted to `/claude-config-ro/.claude` (read-only)
2. Host `~/.claude.json` bind-mounted to `/claude-config-ro/.claude.json` (read-only)
3. `_SETUP_CMDS` runs at container start:
   ```
   cp -a /claude-config-ro/.claude $HOME/.claude
   cp /claude-config-ro/.claude.json $HOME/.claude.json
   ```
4. Container's `$HOME` = `/worker-home` (a tmpfs mount, UID 1000)
5. Claude CLI reads `$HOME/.claude/.credentials.json` and authenticates via OAuth

**No ANTHROPIC_API_KEY is used** — the `.env` has it commented out. Auth is purely OAuth-based using the host user's `claudeAiOauth` tokens from `.credentials.json`.

### 2. Complete Volume Mount Inventory

| Host Path | Container Path | Mode | Purpose |
|-----------|---------------|------|---------|
| `HOST_PROJECTS_DIR` (/home/jyao073/agenthive-projects) | `/projects` | rw | Project source code |
| `cc-git-bare` (named volume) | `/git-bare` | rw | Git bare repos for sync |
| `HOST_CLAUDE_DIR` (/home/jyao073/.claude) | `/claude-config-ro/.claude` | **ro** | OAuth credentials source |
| `HOST_CLAUDE_JSON` (/home/jyao073/.claude.json) | `/claude-config-ro/.claude.json` | **ro** | Claude config source |
| tmpfs (`/worker-home`) | `/worker-home` ($HOME) | rw | Ephemeral working home |

**Key observations**:
- `~/.claude/` is NOT directly mounted as the worker's home — it's a read-only staging area
- Actual `$HOME` is a **tmpfs** (RAM disk) with uid=1000, gid=1000
- No per-agent persistent volume for session data — all session data lives on tmpfs and is lost on container restart
- `.credentials.json` is **copied** (not symlinked) into tmpfs at startup

### 3. Host Credential Files

```
~/.claude/.credentials.json  — 451 bytes, mode 0600, owner jyao073 (uid=1000)
~/.claude.json               — 35938 bytes, mode 0600, owner jyao073 (uid=1000)
```

**Credential format**: `claudeAiOauth` object containing:
- `accessToken`: `sk-ant-oat01-...` (OAuth access token)
- `refreshToken`: `sk-ant-ort01-...` (OAuth refresh token)
- `expiresAt`: `1771914062243` (2026-02-24 06:21:02 UTC — ~24h lifetime)
- `scopes`: `user:inference`, `user:mcp_servers`, `user:profile`, `user:sessions:claude_code`
- `subscriptionType`: `max`
- `rateLimitTier`: `default_claude_max_5x`

### 4. Inside Running Worker Container (`cc-project-crowd-nav`)

| Check | Result |
|-------|--------|
| `$HOME` | `/worker-home` (tmpfs, 31G) |
| `$HOME/.claude/` exists? | Yes — full copy from host |
| `.credentials.json` exists? | Yes, 451 bytes, owner `ubuntu` (uid=1000) |
| `.claude.json` exists? | Yes, 35938 bytes, owner `ubuntu` (uid=1000) |
| File permissions OK? | Yes — worker runs as uid=1000, files owned by uid=1000 |
| `claude --version` | 2.1.50 (Claude Code) |
| Worker user | `ubuntu` (uid=1000, gid=1000) — matches `HOST_USER_UID` in .env |
| RO mount writable? | No — `/claude-config-ro/` correctly read-only |
| HOME writable? | Yes — `$HOME/.claude/` is on tmpfs, fully writable |

### 5. Known Issue Assessment

#### GitHub #22066: OAuth credentials not persisting across container restarts
**STATUS: AFFECTS US (but mitigated)**
- `/worker-home` is tmpfs → all credentials are lost on container restart
- Mitigated because `_SETUP_CMDS` re-copies from host on every container start
- However: if the **access token expires** during a long-running container session, the Claude CLI will refresh the token in `$HOME/.claude/.credentials.json` (tmpfs), but that refreshed token is **never written back to the host**
- On next container restart, the old (possibly expired) host token is copied again
- If the host token's `refreshToken` is still valid, Claude CLI can re-refresh → **no actual breakage**
- **Risk**: If host goes >24h without running Claude locally, the host token could expire. Workers can still refresh during their session, but the host copy becomes stale.

#### GitHub #7842: Docker sandbox injecting `apiKeyHelper: "echo proxy-managed"` into settings.json
**STATUS: NOT AFFECTED**
- Worker `settings.json` contains only `enabledPlugins` and `skipDangerousModePermissionPrompt`
- No `apiKeyHelper` injection detected in any config files
- The only `apiKeyHelper` mentions are in the CLI's own changelog cache (informational, not config)

#### File permission mismatch: credentials mounted as root:root
**STATUS: NOT AFFECTED — correctly handled**
- `.env` sets `HOST_USER_UID=1000`
- Worker runs as `user=1000:1000` via Docker SDK
- tmpfs mounted with `uid=1000,gid=1000`
- Host files owned by `jyao073` (uid=1000) → bind-mount preserves uid → read-only mount readable
- Copied files on tmpfs inherit worker uid → fully writable
- No permission issues observed

### 6. Auth Strategy Recommendation

**Current strategy (Option A variant) is working correctly.** Here's the comparison:

| | Option A: Mount + Copy | Option B: CLAUDE_CODE_OAUTH_TOKEN env | Option C: ANTHROPIC_API_KEY |
|---|---|---|---|
| **Current** | **In use. Working.** | Not implemented | Not implemented |
| Auth type | OAuth (subscription) | OAuth (subscription) | API key (pay-per-token) |
| Token refresh | CLI auto-refreshes in tmpfs; host copy may go stale | Must manually extract and rotate | Never expires |
| Billing | Included in Max subscription | Included in Max subscription | Separate API billing |
| Setup complexity | Medium (3 env vars + uid matching) | Low (1 env var) | Low (1 env var) |
| Session/history | Full CLI features | Full CLI features | Full CLI features |
| Security risk | Host ~/.claude exposed (ro) | Single token in env (visible in docker inspect) | API key in env (visible in docker inspect) |

**UPDATE: Switched to Option B (`CLAUDE_CODE_OAUTH_TOKEN`) — see task log below.**

---

## [2026-02-24] Session Persistence + Auth Simplification | Project: cc-orchestrator

### What was done
1. **Session persistence**: Replaced tmpfs for `$HOME/.claude/` in agent containers with a named Docker volume (`cc-session-{project}`). Session files and refreshed tokens now survive container restarts. `--resume` works across restarts.
2. **Auth simplification**: Switched from host `~/.claude/` mount+copy to `CLAUDE_CODE_OAUTH_TOKEN` env var (generated via `claude setup-token`, valid ~1 year). Removed 2 host bind mounts, all credential copy logic, and `HOST_CLAUDE_DIR`/`HOST_CLAUDE_JSON` config vars.

### Problems encountered
- Named Docker volumes are created with root ownership — non-root worker (uid 1000) can't write to them
- `plan_manager.py` also imported the old `HOST_CLAUDE_DIR`/`HOST_CLAUDE_JSON` config vars — missed on first pass

### Solutions
- Run a throwaway alpine container to `chown` new volumes before first use
- Updated plan_manager.py imports alongside worker_manager.py

### Lessons learned
- `CLAUDE_CODE_OAUTH_TOKEN` is the officially recommended auth method for Docker/CI — eliminates credential file management entirely
- Docker named volumes are root-owned by default — always init with correct ownership before mounting into non-root containers
- When removing config vars, grep the entire codebase for imports — not just the file you're working on
- Container mounts before: 5 (projects, git-bare, claude-dir RO, claude-json RO, session-vol) → after: 3 (projects, git-bare, session-vol)
