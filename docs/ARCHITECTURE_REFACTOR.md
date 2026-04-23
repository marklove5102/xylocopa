# Xylocopa Architecture Refactor: Queued Partition in Display File

> Status: **Phase 0 blueprint — awaiting user review before Phase 1 implementation.**
> Companion doc: `/tmp/xy-refactor-0a-interaction-map.md` (interaction map snapshot, referenced as "0a §X" below).

## 1. Goals

- **Single read source for in-scope paths**: The web UI reads only the display file for the queued block, interactive metadata, and soft-cancel state. No DB→WebUI bypass remains in these surfaces.
- **Preserve `display_seq` semantics**: `display_seq` remains a strict, gap-free monotonic conversation position. Pre-delivery messages get no `display_seq` until promotion.
- **Single-file invariant**: Queued entries live in the *same* JSONL file, distinguished by a `_queued: true` marker. No sibling files, no new on-disk artifacts.
- **Do not disrupt sync**: `flush_agent`, `update_last`, `rebuild_agent`, stop-hook wake, UserPromptSubmit, and streaming keep current semantics. New APIs are additive.
- **Idempotent, tombstone-based transitions**: All state changes (edit, cancel, promote) are represented by appended JSONL lines; readers dedup by id, last-occurrence-wins.

## 2. In-scope vs Out-of-scope

**In scope**
- Queued block endpoints at `routers/agents.py:2511` and `routers/agents.py:2568` (currently queries `Message.display_seq.is_(None)` directly, per 0a §5).
- Interactive card metadata writes at `routers/hooks.py:980+`, `routers/agents.py:2998`, `routers/agents.py:3050` (0a §1 update_last rows).
- Soft-cancel display surface (pathway G, currently unmapped — 0a §2.G).

**Out of scope (intentional)**
- **Message search / paginated `/messages` endpoint**: needs cross-agent SQL filters; display file is per-agent append-only.
- **`tool_activity` WS events**: ephemeral, sub-second; journaling to JSONL would bloat the file without reader benefit.
- **`agent_stream` WS events**: streaming pathway F already flows through `update_last` (0a §2.F); WS emit is the live channel. No change.

## 3. Display File Format: New Entry Types

JSONL, one record per line, order preserved. Reader contract: **dedup by `id`, last-occurrence-wins across all types**; partition winner into `{displayed, queued}` by presence of `_queued: true` on the winning line; drop entries whose winner has `_deleted: true`.

- **Regular** (existing): `{id, seq, role, content, status, timestamps, ...}`. `seq` present ⇒ delivered, belongs to main partition.
- **Replace** (existing): `{id, seq, _replace: true, ...}`. Same `seq`, updated fields. Used by `update_last`.
- **Queued** (new): `{id, _queued: true, status, content, created_at, source, meta_json?, ...}`. **No `seq` field.** Belongs to queued partition.
- **Queued-replace** (new): `{id, _queued: true, _replace: true, status?, content?, meta_json?, ...}`. Updates a queued entry in-place (content edits, PENDING→QUEUED transition).
- **Tombstone** (new): `{id, _deleted: true}`. Removes entry from whichever partition last held it. Used by cancel and by promotion's queued-side removal.

Rationale for markers-not-sections: appending remains the only write pattern; rebuild still produces deterministic output; `fcntl.flock` atomicity (0a §3 Race 4) continues to work unchanged.

## 4. display_writer New API

All functions follow the existing contract (0a §3 Race 4): caller commits DB first, then calls display_writer; each function opens its own `SessionLocal`, no cross-call transaction.

- **`flush_queued_entry(agent_id, message_id)`**
  Writes initial `_queued` line. Called after DB commit of a new PENDING or QUEUED web/task/plan_continue message. Precondition: row exists with `delivered_at IS NULL` and `display_seq IS NULL`. Does **not** allocate `display_seq`. Does not interact with `flush_agent`'s max-seq logic.

- **`update_queued_entry(agent_id, message_id)`**
  Appends `_queued + _replace` line. Called on: modify-message edits, PENDING→QUEUED status transitions, interactive-card metadata changes *before* delivery. Precondition: a prior `_queued` line exists for `message_id`; `display_seq IS NULL`.

- **`mark_deleted(agent_id, message_id)`**
  Appends `{id, _deleted: true}`. Used by (a) cancel of a queued message, (b) the first step of promotion. No DB precondition enforced (caller decides semantics).

- **`promote_to_delivered(agent_id, message_id)`**
  Atomic from the reader's perspective: under a single `flock`, appends tombstone for `id` then the fully-formed main-partition entry with a freshly allocated `display_seq`. Precondition: DB row has `delivered_at` set and `display_seq IS NULL`. Internally uses the same `max(display_seq)+1` rule `flush_agent` uses (0a §4), so the invariants in §7 of 0a hold. After this call, subsequent `update_last(agent_id, msg.id)` works as today.

`flush_agent` and `update_last` are **unchanged**. `rebuild_agent` must additionally re-emit queued entries from DB (messages with `delivered_at IS NULL` and not CANCELLED), written as `_queued` lines before or after the main block — order does not matter given reader dedup.

## 5. Callsite Migration Table

| # | Current (bypass) | Target | Phase |
|---|---|---|---|
| 1 | `routers/agents.py:2511` — queries `display_seq IS NULL` to build queued block when file absent | Remove. Reader parses file; queued partition is self-describing. | 2A |
| 2 | `routers/agents.py:2568` — same query merged into `/display` response | Remove. File alone is canonical. | 2A |
| 3 | `routers/hooks.py:980+` — permission timeout patches meta_json on possibly-pre-delivery msg | If `display_seq IS NULL`: `update_queued_entry`. Else existing `update_last`. | 2B |
| 4 | `routers/agents.py:2998` — `answer_interactive` | Branch on `display_seq`: pre-delivery ⇒ `update_queued_entry`; post ⇒ `update_last` (today). | 2B |
| 5 | `routers/agents.py:3050` — `_dismiss_pending_interactive_cards` | Same branch. Most dismissals are post-delivery ⇒ `update_last`; rare pre ⇒ `update_queued_entry`. | 2B |
| 6 | Soft-cancel (pathway G, 0a §2.G) — no display write today | `mark_deleted` under queued partition when `display_seq IS NULL`; for delivered messages, `update_last` with new status. | 2A |

**Related existing callsites that change behavior**:
- `routers/agents.py:2739` (web send during IDLE): today `flush_agent` assigns `display_seq` immediately. New behavior: call `flush_queued_entry` first; `display_seq` only assigned at UserPromptSubmit via `promote_to_delivered`. This is the load-bearing change that enforces "no `display_seq` for pre-delivery."
- `routers/hooks.py:187` (UserPromptSubmit): replace `update_last` with `promote_to_delivered`. The message currently transitions from queued-block source to main file via `flush_agent` somewhere upstream; after refactor, promotion is the single transition point.
- `agent_dispatcher.py:2897` (scheduled dispatch): mirrors the web-send change — `flush_queued_entry` on create, `promote_to_delivered` on UserPromptSubmit.
- `sync_engine.py:221` (`_promote_or_create_user_msg` pre-commit `update_last`): see §7.

## 6. Pathway-by-pathway Verification

- **A (web send, `routers/agents.py:2700+`)**: QUEUED/PENDING ⇒ `flush_queued_entry`. No more IDLE-only branch for display writing; WS emit unchanged. Fixes 0a §2.A's "WS client sees message before display file" because the file write is unconditional now.
- **B (stop-hook dispatch)**: PENDING→QUEUED transition uses `update_queued_entry` from the dispatcher. No `display_seq` allocated until delivery. Resolves 0a §2.B's "depends on next sync wake" — the display-file update is synchronous with dispatch.
- **C (UserPromptSubmit)**: `promote_to_delivered` is the sole entry point. Tombstone + main-entry appended under one `flock`. Reader sees either "still queued" or "delivered"; never both (dedup).
- **D (sync_engine wake)**: `flush_agent` operates only on messages with `delivered_at` set (already true — `_promote_or_create_user_msg` sets it during import). Queued partition is untouched. Sync mechanism unchanged.
- **E (PostToolUse metadata)**: branched per §5 row 3. When metadata lands on a still-queued interactive card, we route through `update_queued_entry`; otherwise unchanged.
- **F (streaming)**: purely main-partition; `update_last` unchanged. Out of scope.
- **G (cancel)**: `mark_deleted` for pre-delivery; status-replace via `update_last` for delivered. Fixes 0a §2.G's "orphaned display file entries."
- **H (start/stop/delete)**: `startup_rebuild_all` and `rebuild_agent` extended to emit queued entries (§4). Stop/delete unchanged.

## 7. Race / Concurrency Analysis

- **Race 1 (UserPromptSubmit vs sync_engine)**: Hook calls `promote_to_delivered`; sync_engine's `_promote_or_create_user_msg` still may set `delivered_at` first. If sync got there first, the hook finds `display_seq` already allocated — `promote_to_delivered` must detect this (non-NULL `display_seq`) and degrade to a no-op or `update_last`. Design: precondition check inside `promote_to_delivered`.
- **Race 2 (stop-hook + sync flush)**: Unchanged. Main partition writes still serialized by `flock`; queued-partition writes interleave harmlessly.
- **Race 3 (modify + delivery)**: `update_queued_entry` and `promote_to_delivered` for different messages both serialize via `flock`; no `display_seq` collision because queued entries have none.
- **Race 4 (DB tx + flush)**: Unchanged pattern.
- **Race 5 (cancel during dispatch)**: `mark_deleted` + `update_queued_entry` both append; last-occurrence-wins resolves. If cancel lands after dispatch promoted the message, cancel uses `update_last` (delivered path) — safe.
- **Race 6 (timeout + user response)**: Both route through `update_queued_entry` (pre-delivery) or `update_last` (post); last-write-wins as today.
- **`sync_engine.py:221` pre-commit `update_last`**: This is the sole 0a violation of the "commit → then flush" rule. The refactor **fixes** it: `_promote_or_create_user_msg` should emit `update_queued_entry` only *after* the enclosing `db.commit()` at line 544, not inline at 221. Requires a deferred-write list gathered during import, flushed post-commit.

## 8. Migration Strategy

**Incremental with fallback** (chosen). Phase 1 adds new writer APIs and reader support without removing the queued-block query. Phase 2A flips the `routers/agents.py:2511/2568` reader to file-only, but the DB query stays gated behind a feature flag (`XY_QUEUED_FALLBACK=1`) for one release. Phase 2B migrates interactive metadata sites. Phase 3 removes the fallback query and the flag after a one-week soak.

**Justification**: The queued block is user-visible; a regression here surfaces as "my message disappeared." Dual-path for one release caps blast radius. Cost is ~40 lines of dead-code-with-flag, deleted in phase 3.

**Rollback**: `git revert` the phase 2A/2B commits; the Phase-1 writer APIs are additive and can stay. If the display file contains new entry types a rolled-back reader doesn't understand, the old reader ignores unknown markers (must be verified in Phase 1 reader compatibility). No data migration needed; display files are regenerable via `rebuild_agent`.

## 9. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Queued partition grows unbounded (tombstones + replaces accumulate) | Med | Med (file bloat, parse latency) | `rebuild_agent` compacts on session rotation (0a §1); add size-threshold trigger for proactive rebuild. |
| 2 | `promote_to_delivered` races concurrent cancel | Low | High (ghost delivered message) | Precondition check: promote aborts if a tombstone for `id` was the most recent line at flock acquisition. |
| 3 | Frontend dedup cost with more lines per message | Med | Low | Dedup is O(n) hashmap; measure at 10× current line count. Acceptable ceiling ~50k lines/agent. |
| 4 | Display file size growth on long-running agents | Med | Med | Existing `rebuild_agent` on rotation addresses most cases; add opportunistic compaction when queued-tombstone ratio > 0.3. |
| 5 | Sync regression (stop-hook timing, PostToolUse visibility) | Low | High | Phase 1 lands writer APIs under no callers; integration tests replay 0a's pathways A–H before Phase 2A. Fallback flag (§8) de-risks. |

## 10. Non-goals / Future Work

- **Streaming via display file**: intentionally kept on WS + `update_last`. Latency requirements (sub-100ms chunk display) are not compatible with JSONL append + re-read.
- **`tool_activity` journaling**: stays on WS. Ephemeral by design.
- **Search / pagination**: remain DB-direct. Display file is per-agent append-only; cross-agent queries are a different problem and are not debt created by this refactor.

---

**Decision locked (2026-04-23)**: User confirmed **Option A** — fix the `sync_engine.py:221` pre-commit violation as part of Phase 2A. `promote_to_delivered` is called post-commit (after line 544) via deferred-write list. Eliminates the stale-display-state bug and the sole pre-commit exception to the display_writer protocol.

**Ready for Phase 1 implementation.**
