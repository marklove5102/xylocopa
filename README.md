# Xylocopa

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![React 19](https://img.shields.io/badge/react-19-61dafb.svg)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)

> [**The Loop**](#the-loop) · [**Getting Started**](#getting-started) · [**Features**](#features) · [**Known Issues**](#known-issues) · [**Roadmap**](#roadmap) · [**Contributing**](CONTRIBUTING.md) · [**Host Setup**](#host-setup) · [**Client Setup**](#client-setup)
>
> **New here?** [**Getting Started**](docs/getting-started.md) · [**新手入门（中文）**](docs/getting-started-zh.md)
>
> **Going deeper?** [**A Day with Xylocopa**](docs/workflow.md) (5-minute worked example) · [**Architecture**](docs/ARCHITECTURE.md) · [**Contributing**](CONTRIBUTING.md)

**Xylocopa: capture tasks, dispatch to agents, keep the context.** 🐝

_Named after [Xylocopa caerulea](https://en.wikipedia.org/wiki/Xylocopa_caerulea): the blue carpenter bee._

Xylocopa aims to reduce the friction of navigating multiple [Claude Code](https://docs.anthropic.com/en/docs/claude-code) projects, keeping track of what you asked, what got done, and what to try next. Capture tasks into an inbox, group them by project, and dispatch to agents running in parallel on isolated worktrees. When an attempt misses the mark, retry with a summary of what was tried, so the project carries forward what was learned instead of starting over each session.

Tasks in. Agents out. Lessons kept.

If you run `claude` across several projects and want the sessions to feel like one workflow instead of a pile of terminal tabs, this is for you.

If you find Xylocopa useful, a star helps others discover it :)

## The Loop

Classic [GTD](https://gettingthingsdone.com/what-is-gtd/) moves ideas through a five-step loop (capture, clarify, organize, reflect, engage), all performed by one human. Xylocopa keeps the loop but rewires the executor: **you capture and decide, your agents execute, and the system reflects and remembers.** The five steps below are GTD for an era where the work itself can be delegated to AI.

Traditional task management tracks what **you** plan to do. Xylocopa tracks the tasks **and** the agents executing them, so each project remembers what was tried, not just what's pending.

### 1. Capture

Get ideas out of your head and into the system, fast, from anywhere.

- **Inbox**: a persistent queue for tasks across all your projects. Tasks wait here until you're ready to dispatch them.
- **Voice input**: dictate tasks using speech-to-text. Great for quick ideas on your phone while walking the dog.
- **Lightning input**: rapid task creation with minimal friction. Title, project, go.
- **Draft persistence**: edits are cached locally as you type. Close the app, lose connection, or switch tasks, your unsaved work is still there when you come back.

### 2. Dispatch

Assign tasks to AI agents and let them work.

- **Task → Agent**: turn any task into an autonomous agent with one click. Pick a model (Opus/Sonnet/Haiku), toggle **Auto mode** (runs Claude Code with `--dangerously-skip-permissions`, bypasses per-tool confirmation prompts; destructive commands are still hard-blocked by the [safety hook](#safety-guardrails)), and let the agent do the work while you move on.
- **Parallel execution**: run 5, 10, or more agents in parallel across different projects. Each agent gets its own isolated git worktree so they never step on each other's code.
- **AI batch processing**: got a pile of tasks in your inbox? One click to let AI triage and dispatch them in bulk, instead of handling each one manually.
- **RAG-powered context**: when dispatching a task, Xylocopa automatically retrieves relevant history from past agent sessions. Your new agent starts with the lessons learned, not from scratch.
- **Cross-session reference**: tell an agent "check xy session `<session_id>`" and it can read another agent's full conversation via a built-in [MCP server](orchestrator/mcp_server.py). Reads the curated display file instead of raw session JSONL, same complete message history, but ~54× fewer tokens into the agent's context window (thinking blocks and tool I/O stripped, tool calls compressed to one-line summaries).

### 3. Monitor

Watch everything happen in real time, from your desk or your phone.

- **Mobile-first web UI**: a full PWA you can add to your Home Screen. Works on any device, any screen size.
- **Split screen**: monitor 2, 3, or 4 agents side by side (2-column, 3-column, 2x2 grid on desktop; stacked on mobile). Each pane navigates independently.
- **Attention button**: a draggable FAB that turns into a cyan unread badge when any agent has new messages. Tap to jump to the oldest unread conversation (FIFO); long-press always opens split screen.
- **Rich chat interface**: markdown rendering, inline image and media preview, interactive cards for tool approvals and plan review. Approve, deny, or respond to agents directly in the conversation.
- **Dual-directional CLI sync**: CLI sessions appear in the web app, web app sessions are resumable from the CLI. Attach to any agent's terminal with `tmux attach -t xy-<agent-id prefix>` (legacy `ah-` sessions still attach for back-compat) and keep working from your keyboard. One conversation history, two interfaces.

  ![CLI sync demo](docs/cli-sync.gif)
- **Smart notifications**: Web Push and Telegram with dual-channel in-use detection: if you're viewing an agent in the browser (WebSocket presence) or attached to its tmux pane, notifications are suppressed. Permission requests always cut through.
- **System & usage monitoring**: disk, memory, GPU status, and token usage at a glance.

### 4. Review

Check results, give feedback, and keep the knowledge growing.

- **Mark done**: review agent output, approve the work, mark the task complete.
- **Try → Summarize → Retry**: agent didn't nail it? Stop the agent, add your feedback, and Xylocopa auto-generates a summary of what was tried. Re-dispatch with full context, the next agent picks up where the last one left off. Iterate until it's right.
- **Git operations**: view diffs, commit history, and branch status per project. One-click cleanup and push when you're satisfied.
- **Growing intelligence**: each project carries a PROGRESS.md where lessons accumulate across sessions. You control which agent conversations generate summaries, review and cherry-pick which insights to keep, and relevant lessons are automatically retrieved (top-k) when dispatching new agents, more control over project memory than Claude Code's native auto-memory.

### 5. Remember

Knowledge accumulates, across sessions, across projects, across time.

- **Project memory**: per-project PROGRESS.md managed through the UI. Choose which sessions to summarize, accept or reject individual insights, and edit the file directly. Future agents start with what's already been learned.
- **Session archive**: every agent conversation is persisted and searchable. Star important sessions for quick access. Browse history across projects.
- **Resume anytime**: pick up any agent conversation right where it left off, whether it finished yesterday or last month.
- **Full-text search**: find any task, message, or agent session across your entire history.
- **Progress tracking**: weekly completion stats show how much your agents are getting done. See the trend, not just the backlog.
- **Automatic backups**: database, session history, and project configs are backed up on a configurable schedule. Crash recovery salvages partial output.

## Why Xylocopa?

### Why not just use `claude`?

Vanilla `claude` CLI works fine for one-off sessions. It starts to fray once you run more than one in parallel, across more than one project, over more than a few days.

**Attention across agents and projects.** Three `claude` sessions in three terminal tabs, which one is waiting for your approval? Which is still thinking? Xylocopa has a single **Attention button** that morphs into a blue count badge for unread or waiting agents across all projects; tap to jump to the oldest, long-press to open 2/3/4-pane split-screen. Each project has its own dashboard with an emoji, an LLM-generated resume hint of what the agents did recently, weekly success rate, and an in-project search bar across agents, messages, and files. Push notifications fire when an agent stops, muted if you're already looking at that session.

**Idea capture on the go.** You can't start a `claude` session on your phone in a meeting. Xylocopa is a PWA: dictate by voice (Whisper-transcribed), ⚡ quick-save to inbox, triage later at the desk. Every keystroke auto-drafts to localStorage across 13+ input surfaces; close the app mid-thought, reopen, it's still there.

**Finding and resuming old work.** `claude --resume <uuid>` works if you remember the UUID. Xylocopa has full-text search across every session you've ever run, per-project or global, with star-to-pin. One-click resume brings STOPPED or ERROR agents back, either re-syncing to the existing tmux pane or relaunching via `claude --resume` in a fresh one.

**Retry instead of rewrite.** When an agent misses the mark, vanilla setup means retyping the prompt and re-explaining what went wrong. Xylocopa's Try → Summarize → Retry auto-generates a summary of what was tried from the session itself; you edit, the next agent picks up with it in context. Durable lessons roll into per-project `PROGRESS.md`, automatically surfaced to future agents via RAG.

**Rich content and token-efficient cross-agent references.** `claude` dumps image paths as text. Xylocopa renders images, PDFs, and media inline with thumbnails, plus LaTeX math (KaTeX) and a per-session file browser. Tell one agent "check xy session `<id>`" and it reads another agent's curated display file via a built-in MCP server, about **54× fewer tokens** than raw JSONL (thinking blocks stripped, tool calls compressed to one-line summaries).

The chat is still there; `claude` still runs the show. Xylocopa is the task, attention, and memory layer around it.

### Lessons Compound

Most agent tools assume the agent gets it right. Xylocopa assumes it won't. When an agent misses the mark, one click summarizes what was tried, and the next agent picks up from there. Iterate until done, and the lessons accumulate per project (in `PROGRESS.md`), not per session, so future agents start with what you've already learned.

### Zero Migration Cost

Already using Claude Code? Xylocopa plugs right in. It wraps the same `claude` CLI you already know, launched inside tmux sessions on your machine, managed through a web UI. Your existing CLAUDE.md files, project setup, and workflow all carry over. The only new dependencies are **tmux** and optionally **Tailscale** for remote access. No new APIs, no vendor lock-in, no relearning.

### Built for Reliability

Xylocopa hooks into Claude Code's native event system, not polling, not heuristics. Notifications, message delivery, and session sync are all event-driven. Messages reach agents through stop-hook dispatch with guaranteed ordering. Session lifecycle is tracked via SessionStart/SessionEnd hooks. Each agent runs in its own tmux session with a dedicated git worktree, with configurable timeouts and automatic crash recovery. A deterministic `PreToolUse` [safety hook](#safety-guardrails) hard-blocks destructive operations (`rm -rf`, `git push --force`, `DROP TABLE`, out-of-project writes, …), active even when agents run in Auto mode with `--dangerously-skip-permissions`.

### Durable by Default

Nothing you run through Xylocopa is ephemeral, not your conversations, not your in-flight work, not your unsaved drafts. Every layer is designed to survive restarts, crashes, and process kills:

- **30-second incremental session cache**: active session JSONL files are append-only-cached every 30s ([`session_cache.py`](orchestrator/session_cache.py)), just like git packfiles. Truncated lines from process kills are auto-repaired on restore.
- **Unlimited session retention**: Xylocopa writes `cleanupPeriodDays=36500` to `~/.claude/settings.json` on boot ([`session_cache.py:183`](orchestrator/session_cache.py)), so Claude Code never auto-deletes your history. Conversations from a year ago are still resumable.
- **Crash-recovery with partial output salvage**: when the orchestrator restarts with agents mid-flight, `_recover_agents()` ([`agent_dispatcher.py:4776`](orchestrator/agent_dispatcher.py)) reads each crashed message's stdout from `/tmp/claude-output-{msg_id}.log`, extracts the partial result, and persists it as a `(partial — interrupted by restart)` message before re-queueing the original prompt. No output is silently lost.
- **Tmux-anchored session recovery**: every agent is launched as a deterministically-named tmux session (`xy-{id[:8]}`). On orchestrator restart, agents whose tmux is still alive are **re-linked without interrupting them**: including agents that were previously STOPPED but whose CLI kept running. Your agents survive the web app.
- **One-click resume of stopped agents**: `POST /api/agents/{id}/resume` ([`routers/agents.py:2111`](orchestrator/routers/agents.py)) brings a STOPPED/ERROR agent back. Two modes: re-sync to existing tmux pane (default), or relaunch via `claude --resume <session_id>` in a fresh tmux (`mode: "tmux"`).
- **Automatic periodic backups**: DB + project configs + session history snapshotted every 24h (configurable) with rolling retention ([`backup.py`](orchestrator/backup.py)). Runtime-adjustable via `PUT /api/system/backup/config`.
- **Local draft persistence**: every text input caches to `localStorage` as you type ([`frontend/src/hooks/useDraft.js`](frontend/src/hooks/useDraft.js), used in 13+ surfaces). Close the browser, switch tabs, kill your phone, your unsaved work is still there.
- **Session directory migration**: move a project folder (e.g. `~/Work/foo` → `~/xylocopa-projects/foo`) and Xylocopa auto-migrates Claude's old encoded session directory so nothing reindexes from scratch.
- **Orphan cleanup**: stale worktrees, zombie tmux sessions, and tempfiles from crashed processes are periodically swept ([`orphan_cleanup.py`](orchestrator/orphan_cleanup.py)).

> Every bullet above is open source and linked to its implementation. Audit it, don't trust it.

## Features

### Highlights

- **Try → Summarize → Retry**: when an agent misses the mark, one click captures what was tried; the next dispatch picks up from there instead of starting cold.
- **RAG-powered context**: new agents are seeded with relevant lessons from past sessions in the same project, retrieved automatically at dispatch time.
- **Dual-directional CLI sync**: every agent runs in a tmux session you can attach to from your terminal; sessions you start in the CLI also appear in the web UI.
- **Crash-proof by design**: 30s incremental session cache, partial output salvage on restart, unlimited session retention, and one-click resume of stopped agents. Your work survives the app. See [Durable by Default](#durable-by-default).
- **Deterministic [safety hook](#safety-guardrails)**: `PreToolUse` hard-blocks destructive commands (`rm -rf`, force-pushes, `DROP TABLE`, out-of-project writes), even when agents run with `--dangerously-skip-permissions`.

### Full feature list

| Category | What you get |
|---|---|
| **Smart Notifications** | Hook-based notification system with dual-channel in-use detection, automatically notifies when you're away and stays quiet when you're present. Web Push (VAPID) and Telegram. Per-agent mute, global toggles. |
| **Task Management** | Inbox with drag-to-reorder. Voice input. Lightning capture. Draft persistence. Per-project organization. Retry with auto-summarization. |
| **Agent Control** | Start, stop, **one-click resume** of STOPPED/ERROR agents (re-sync to existing tmux or relaunch via `claude --resume`). Per-agent model selection (Opus/Sonnet/Haiku). Configurable timeouts and permission modes. AI batch dispatch. RAG-powered context from past sessions. Cross-session reference via MCP, agents read each other's curated display files (~54× fewer tokens than raw JSONL), keeping cross-references fast and context-window-friendly. |
| **Chat Interface** | Rich markdown rendering (code blocks, tables, images). Inline media preview. Plan mode with approve/reject. Interactive tool confirmation cards. |
| **Monitoring** | Split screen (up to 4 panes). Real-time WebSocket streaming. System monitor (disk, memory, GPU, tokens). Weekly progress stats. |
| **Mobile PWA** | Add to Home Screen on iOS/Android. Full functionality, voice input, push notifications, task management. |
| **CLI Session Sync** | Dual-directional: CLI sessions in the web app, web app sessions resumable from CLI. |
| **Git Integration** | Commit history, diffs, branch status per project. Agents work in isolated worktrees. One-click cleanup and push. |
| **Session History** | Every conversation persisted and searchable. Star sessions. Resume any agent anytime. Full-text search. |
| **Security** | Password auth with exponential-backoff rate limiting. Inactivity lock. HTTPS encryption. |
| <a id="safety-guardrails"></a>**Safety Guardrails** | Deterministic `PreToolUse` hook hard-blocks destructive operations, `rm -rf`, `git push --force`, `git reset --hard` outside worktrees, `git clean -f`, `git checkout -- .` / `git restore .`, `DROP TABLE` / `TRUNCATE`, and any `Write`/`Edit` to paths outside the project directory. Enforced even when **Auto mode** (`--dangerously-skip-permissions`) is on. |
| **Reliability & Recovery** | 30s incremental session JSONL cache (append-only, like git packfiles). **Unlimited retention**: `cleanupPeriodDays=36500` prevents Claude from deleting your history. Orchestrator-restart recovery re-links live tmux agents without interrupting them. Partial output salvaged from killed processes. Automatic periodic DB + config + session backups (runtime-configurable interval & retention). Truncated JSONL auto-repaired. Orphan worktree/tmux cleanup. See [Durable by Default](#durable-by-default) for source pointers. |

## Before You Install

A few things worth knowing before running this on your dev machine.

### Where does my data live?

- **SQLite DB**: `data/orchestrator.db` in the install directory (tasks, projects, agent metadata, configs)
- **Agent sessions**: `~/.claude/projects/<encoded-path>/*.jsonl` (Claude Code's native session JSONL; Xylocopa doesn't duplicate these)
- **Per-project memory**: `<project>/PROGRESS.md` inside each project's git repo
- **Backups**: `backups/` (rolling DB + session snapshots, see [Durable by Default](#durable-by-default))
- **Uploaded files**: `~/.xylocopa/uploads/`

To capture everything in one snapshot, back up the install directory and `~/.claude/projects/` together.

### How do I uninstall it?

```bash
# Stop the services
pm2 delete xylocopa-backend xylocopa-frontend && pm2 save

# Remove the install
rm -rf ~/xylocopa-main          # or wherever you cloned it
rm -rf ~/.xylocopa              # uploaded files

# Optional: remove your project directories too
rm -rf ~/xylocopa-projects

# Optional: restore Claude Code's default session-cleanup window
# (Xylocopa sets cleanupPeriodDays=36500 in ~/.claude/settings.json)
```

Project code, git history, and Claude Code session JSONL files in `~/.claude/projects/` are untouched by the uninstall.

## Getting Started

### Host Setup

#### Prerequisites

- **Linux** or **macOS** host (Ubuntu 22.04+ / macOS 13+ recommended)
- **Node.js** 18+ and npm
- **Python** 3.11+
- **tmux** (usually pre-installed; `sudo apt install tmux` if not)
- **Claude Code CLI**: `npm install -g @anthropic-ai/claude-code`, then run `claude` once interactively to log in (Xylocopa reuses the credentials in `~/.claude/`). On a headless server with no browser, use `claude setup-token` instead.
- **Claude subscription**: Claude Max or Pro (uses your existing subscription, no separate API billing)
- **OpenAI API key** _(optional, for voice input)_

#### Installation

Fastest path (clones + runs the interactive installer):

```bash
curl -fsSL https://raw.githubusercontent.com/jyao97/xylocopa/master/setup.sh | bash
```

This installs into `~/xylocopa-main` and prompts for your projects directory, default Claude model, OpenAI API key (optional), and ports. It writes `.env`, generates SSL certs, installs Python and Node dependencies, and launches the services. No manual `.env` editing required.

If you prefer to clone manually:

```bash
git clone https://github.com/jyao97/xylocopa.git ~/xylocopa-main
cd ~/xylocopa-main
./setup.sh        # same interactive prompts as above
./run.sh start
```

Verify by opening `https://<machine-ip>:3000` on the host. Find your machine's LAN IP with `hostname -I` on Linux or `ipconfig getifaddr en0` on macOS.

> **Tip:** You can also run `claude` in an empty directory and tell it to set up Xylocopa for you :)

> **Tip:** Symlink the Xylocopa repo into `~/xylocopa-projects/` to personalize your experience, let agents improve the tool while you use it.

#### Auto-Start on Reboot (PM2)

Strongly recommended, not just for reboot survival: this step also moves the pm2 daemon out of the terminal session that spawned it. On Linux that matters because systemd-oomd can SIGKILL an entire terminal cgroup (e.g. GNOME Terminal's `vte-spawn-*.scope`) under memory pressure, taking backend+frontend with it. On macOS the equivalent benefit is that pm2 no longer dies if you close Terminal.app.

```bash
./run.sh startup
```

This runs `pm2 save` + `pm2 startup` with auto-detection (systemd on Linux, launchd on macOS). On Linux it will print a `sudo env PATH=... pm2 startup systemd ...` line, copy and run it exactly as shown. On macOS no sudo is needed.

To disable later: `pm2 unstartup` (same auto-detection).

#### Set Up Your Projects

Add projects in the app: **long-press the + button → New Project**: paste any GitHub URL or point to an empty folder. You can also manually create or symlink folders in the projects directory (`~/xylocopa-projects/` by default, configured via `HOST_PROJECTS_DIR` in `.env`).

### Client Setup

After setting up the host, visit `https://<machine-ip>:3000` from any device with network access, that's it. Set a password on first visit.

#### Remote Access

For access outside your LAN, Xylocopa works with any tunneling or VPN solution, [Tailscale](https://tailscale.com), [ZeroTier](https://www.zerotier.com), [WireGuard](https://www.wireguard.com), [frp](https://github.com/fatedier/frp), Cloudflare Tunnel, etc. The author uses Tailscale:

1. Install [Tailscale](https://tailscale.com) on your server and phone
2. `tailscale up` on both devices
3. Access Xylocopa at `https://<tailscale-ip>:3000`

No port forwarding, no public exposure, traffic stays in an encrypted tunnel between your devices.

#### iPhone PWA

If you want the full app experience on iPhone (home screen icon, fullscreen, push notifications):

1. Open `https://<machine-ip>:3000` in Safari (bypass the certificate warning via **Advanced → Visit Website**, then refresh).
2. Follow the on-screen guide on the login page to install the CA certificate and the Xylocopa app.

#### Installing the CA Certificate

Xylocopa uses a self-signed SSL certificate. The host trusts it after setup, but other client devices will show a browser warning until you install the cert. iPhone/iPad users can skip this, the [iPhone PWA](#iphone-pwa) guide above already covers it.

For Android, macOS, Windows, and Linux, see [detailed instructions](docs/install-cert.md).

## Gestures & Shortcuts

- **Short-press the + button** to quickly add a task. **Long-press** it to choose between adding a project, agent, or task.
- **Double-tap an agent's session ID** to quickly copy it to the clipboard.
- **Double-tap a message** in the chat view to quickly copy its content.

## Troubleshooting

- **Conversation appears stuck or not updating?**: Try clicking the **refresh button** at the top of the chat view. This manually re-syncs the agent's session data from the CLI and often resolves display issues without restarting the agent.
- **Agent shows IDLE after server restart but is still running?**: When the backend restarts while agents are executing, their status may temporarily show as IDLE even though the underlying Claude CLI process is still active. This is normal, the status will automatically restore to EXECUTING the next time the agent makes a tool call (which triggers a heartbeat via the `agent-tool-activity` hook). If the agent is in a long thinking phase with no tool calls, you can wait or send it a message to trigger activity.
- **Don't name tmux sessions with the `xy-` or `ah-` prefix**, Xylocopa uses `xy-{id}` as its internal naming convention for managed agent sessions (legacy `ah-{id}` is also still recognized for back-compat). User-created tmux sessions starting with either prefix will not be detected or synced by the orchestrator.
- **PWA stuck on a perpetual loading screen (iPhone or other device)?**: The Service Worker on the device is likely holding a stale precache from a previous deploy. From the host, run `.venv/bin/python tools/push_reset.py` (no args) to open an interactive picker that lists every subscription with its detected device label (e.g. `iPhone iOS 18.7`, `macOS Safari`) and how long ago it last acked a push, pick a number to reset that one device, `a` to reset all, or `q` to quit. The SW will clear its caches, unregister itself, and show a "Reset done" notification. After that, fully close the PWA on the device (e.g. swipe up from the iOS app switcher) and reopen it for a clean fetch. Direct invocations (`list`, `<sub_id>`, `all`) are also supported for scripting. (Use the project venv, `pywebpush` is only installed there.)

## Known Issues

- **iPad & mobile browser layout**: layout needs further optimization for iPad and non-PWA mobile browsers. There are minor visual quirks on iPad standalone mode. Tested and working correctly on iPhone (Add to Home Screen) and desktop browsers.
- **CLI sessions started while backend is offline are silently missed**: adoption of externally-created `claude` CLI sessions relies on the `SessionStart` hook reaching the backend over HTTP. If the backend happens to be down at that moment (e.g. a crash, oomd kill, or manual restart window), the hook's offline fallback only persists managed-agent signal files, unmanaged session markers are dropped, and there is no startup rescan. The session will run normally but never appear in the "unlinked sessions" adoption UI. Workaround: after the backend is back, exit and re-launch `claude` in the same tmux pane so the hook fires again. Tracked in `TODO.md`.

## Roadmap

- [x] **macOS support**: basic compatibility merged (cross-platform process detection, path normalization, iOS cert/Web Clip setup). Some edge cases may remain, please report issues.
- [ ] **Backup & restore**: automatic backups run on schedule, but the restore flow has not been fully validated. Use with caution.
- [ ] **UI & icon refresh**: improve visuals, iconography, and layout polish across the web interface.
- [ ] **Better HTTPS certificates**: replace the self-signed certificate with a more seamless solution (e.g. Let's Encrypt, Tailscale HTTPS, or mDNS) to eliminate manual cert installation on client devices.

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:

- Reporting bugs and suggesting features
- Setting up a development environment
- Running tests and submitting pull requests

## Migration from AgentHive

Xylocopa was previously named **AgentHive**. Existing installs continue to work without manual migration, the upgrade path is backward compatible:

- **CLI**: the `agenthive` command remains as a symlink to the new `xylocopa` command. Both work identically.
- **Install dir**: `XYLOCOPA_DIR` is the new env var; `AGENTHIVE_DIR` is still honored as a fallback. Existing `~/agenthive-main` checkouts keep working.
- **Process names**: `pm2` processes are now `xylocopa-backend` / `xylocopa-frontend`. The upgrade script removes the legacy `agenthive-*` processes automatically.
- **MCP server**: the entry in `.mcp.json` is renamed from `agenthive` to `xylocopa` on first agent start. Cross-session references (`check ah session <id>` style) keep working.
- **tmux sessions**: new agents use the `xy-{id}` prefix; legacy `ah-{id}` sessions are still recognized so in-flight agents survive the upgrade.
- **User data dir**: `~/.agenthive/uploads` is renamed to `~/.xylocopa/uploads` automatically on first backend start (only if the new dir doesn't already exist).
- **Env vars**: `XYLOCOPA_MANAGED` is the new flag; `AGENTHIVE_MANAGED` is still set in parallel for any external scripts that read it.
- **Browser storage**: theme/notification preferences in `localStorage` are auto-migrated to the new `xylocopa-*` keys on first page load.
- **Certificates**: newly issued certs use `xylocopa-ca.crt` / `xylocopa.crt` filenames. Already-installed certs continue to work, no reinstall needed.
- **Apple Web Clip**: the bundle ID changes from `com.agenthive.*` to `com.xylocopa.*`. Re-download the `Xylocopa.mobileconfig` profile from the login page if you want the renamed Home Screen entry.

If you'd like to rename your install dir to match: `mv ~/agenthive-main ~/xylocopa-main && cd ~/xylocopa-main && ./run.sh restart`.

## License

Apache 2.0, see [LICENSE](LICENSE) for details.
