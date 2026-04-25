# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.7.1] - 2026-04-25

### Fixed

- Telemetry `daily_heartbeat` was reporting `v0.6.1` after the v0.7.0 release because `_load_version()` read the root `package.json` (the `create-xylocopa` npm installer's own version), which the v0.7.0 release commit didn't bump. Version source switched to `frontend/package.json` — release flow already bumps that on every tag, so heartbeat version stays in sync automatically going forward.

### Changed

- Sent-bubble check icon brightened from `gray-400/50` to `gray-100/80`; sent bubble matches delivered colour while the grey check distinguishes the two states.

### Removed

- Stale refactor plan docs and references to them in source comments.

## [0.7.0] - 2026-04-24

### Added

- Anonymous `daily_heartbeat` telemetry (one event/day, gated to >20h interval) sent to a Cloudflare Worker that writes to a private D1 database. No IPs, no user content. Opt-out via the Monitor page toggle, `XYLOCOPA_TELEMETRY=0`, or `telemetry: false` in `~/.xylocopa/config.yaml`. See `## Telemetry` in README and [`orchestrator/telemetry.py`](orchestrator/telemetry.py).
- Defer agent: hide an agent from the main list and mute its notifications until a chosen time. Collapsible "Deferred" section on the Agents page. Defer chip uses an hourglass icon in both the inbox card and chat header.
- Per-message bubble menu in chat with Copy / Modify / Delete actions.

### Changed

- **Pre-delivery refactor.** Messages now flow PENDING → pre-delivered → sent → delivered. Dispatcher promotes pre-delivery → sent atomically on tmux send; display file uses read-before-truncate rebuild; sync content-matching is restricted to sent-state DB rows. WebSocket emits `predelivery_*` and `message_sent` events; frontend chat bubbles render the new state machine.
- DELETE is now single-step (tombstones queued/scheduled rows immediately) and ESC does soft-cancel through a separate endpoint — they no longer share behavior.
- SessionStart hook is the canonical launch-wake signal. JSONL polling fallback removed from the launch path; orchestrator waits on the hook.
- `/compact` and `/clear` slash-commands emit `message_executed` on completion; web slash-command rows are matched against their `<command-message>` JSONL wrapper instead of creating duplicate CLI rows.
- `datetime-local` inputs in the frontend prefill in the local timezone rather than UTC.
- README hero rewritten ("Many projects. One attention."), install simplified to a curl one-liner, GTD framing added.
- Tmux launch poll tightened to 200 ms; `TUI_SETTLE_DELAY` reduced from 3 s to 0.5 s.

### Fixed

- `cancel_message` is idempotent when the row is already `CANCELLED`.
- Tmux send no longer breaks on messages that begin with `-`.
- DB fallback no longer leaks `CANCELLED` messages back into display output.
- Duplicate pre-delivery bubble and out-of-order Attempts panel in chat.
- First message after orchestrator startup is synced immediately rather than waiting for the next tick.
- Sync engine restores task-launched rows to the match-candidate pool so they don't get orphaned.

### Removed

- Dead `/messages` endpoint and stale `emit_message_update(CANCELLED)` WS event.
- `XY_QUEUED_FALLBACK` scaffolding (Phase 3 cleanup of the predelivery migration).
- Unreachable partial-output salvage path in the dispatcher and the corresponding README claim.
- Telegram notification claims from docs (the integration was never implemented).

## [0.1.0] - 2025-01-01

### Added

- Multi-agent orchestration with tmux-based sessions
- Real-time WebSocket communication for live agent output streaming
- Project management with git integration and isolated worktrees per agent
- Voice input support via OpenAI Whisper for hands-free task creation
- Mobile-responsive PWA interface with Add to Home Screen support
- Task management inbox with drag-to-reorder priorities
- Agent coordination with configurable concurrency limits and timeouts
- Session persistence and JSONL-based history with crash recovery
- Push notifications for agent status changes (finish, error, needs input)
- Password authentication with rate limiting and inactivity-based session lock
- HTTPS with self-signed certificate generation for LAN encryption
- System monitor for disk, memory, and GPU usage
- CLI session sync (read-only import and live-tail of terminal sessions)
- Dark/light theme with system-aware toggle
- Automatic hourly database backups
