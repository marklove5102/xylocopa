# Refactor: Pre-Delivery Messages Out of the DB

> Status: **Plan — ready for dispatch.** Replaces the earlier draft of this
> document. Extends `docs/ARCHITECTURE_REFACTOR.md` (single-file queued
> partition, idempotent promote, hook-wakes-sync-writes). Does **not**
> address the agent-runtime status drift (EXECUTING↔IDLE) — that is owned
> by a separate task (agent session `3944f4ba`).

## 0. Headline

Pre-delivery messages (queued, scheduled, cancelled) live **exclusively in
the per-agent display file**; they never enter the DB `messages` table. The
moment a message is actually sent to the tmux pane, a DB row is created and
ownership transfers. Cancel stays a file-only operation (two-stage: soft
cancel → hard tombstone). No sidecar file. No shadow DB row. Same flock
discipline. Rebuild preserves pre-delivery via read-before-truncate.

## 1. Final state machine

Five user-facing states, mapped to today's `MessageStatus` values:

| State        | Today's enum | Lives in        | UI bubble position | Check icon                | Bottom label          | Edit? | Cancel? |
|--------------|--------------|-----------------|--------------------|---------------------------|-----------------------|-------|---------|
| queued       | PENDING      | file only       | bottom queue list  | —                         | "queued"              | ✓     | ✓       |
| scheduled    | PENDING      | file only       | bottom queue list  | —                         | clock + scheduled_at  | ✓     | ✓       |
| cancelled    | CANCELLED    | file only       | bottom queue list (grey) | —                   | "cancelled"           | ✗     | ✗ (hard-deletable) |
| sent         | QUEUED       | **DB** + file   | main chat flow     | faded grey single check   | "sent"                | ✗     | ✗       |
| delivered    | COMPLETED    | **DB** + file   | main chat flow     | green single check        | "delivered"           | ✗     | ✗       |
| executed     | COMPLETED + completed_at on slash | **DB** + file | main chat flow | green double check | "executed"     | ✗     | ✗       |

Transitions:

```
          POST /messages (agent busy or scheduled)
                   │
                   ▼
        ┌──────────────────┐       Modify (edit)
        │ queued / scheduled │ ◄──────────────────┐
        └──────────────────┘                     │
                   │                              │
          user Delete │     ┌────────────────────┘
                   ▼
          ┌──────────────┐   user Delete (hard)
          │   cancelled  │ ───────────────────────► tombstone (gone)
          └──────────────┘
                   │
                   ◆ (terminal; cannot transition to sent)

          POST /messages (agent IDLE) OR dispatcher picks up queued/scheduled
                   │
                   ▼  send_tmux_message succeeds
             ┌────────┐
             │  sent  │  ← DB row INSERT, seq allocated, file gets regular line
             └────────┘
                   │
                   ▼  UserPromptSubmit + sync ContentMatcher match
          ┌─────────────┐
          │  delivered  │  ← DB row UPDATE (status, jsonl_uuid, delivered_at)
          └─────────────┘
                   │
                   ▼  (slash only) PostCompact hook / SessionStart source=clear
          ┌─────────────┐
          │  executed   │  ← DB row UPDATE (status, completed_at)
          └─────────────┘
```

## 2. Storage model

### 2.1 Display file line shapes

Per-agent file: `data/display/{agent_id}.jsonl`. Append-only JSONL, flock-protected, last-occurrence-wins by `id`.

**Pre-delivery entry** (no DB row):

```json
{
  "id": "<12-hex>",
  "_queued": true,
  "_pre": true,
  "role": "USER",
  "content": "...",
  "source": "web|task|plan_continue",
  "status": "queued" | "scheduled" | "cancelled",
  "created_at": "<ISO8601>",
  "scheduled_at": "<ISO8601>" | null,
  "metadata": {...} | null
}
```

- `_pre: true` is the NEW required marker distinguishing pre-delivery from legacy `_queued` lines.
- Edits append `_pre + _replace: true` with full re-serialization.
- Soft-cancel transitions `status` to `"cancelled"` (same line shape, new append).
- Hard-delete appends plain tombstone `{"id": "...", "_deleted": true}`.

**Post-send entry** (has DB row):

```json
{
  "id": "<same id as pre-delivery>",
  "seq": 42,
  "role": "USER",
  "kind": "text",
  "content": "...",
  "source": "web|task|plan_continue",
  "status": "sent" | "delivered" | "executed",
  "metadata": {...} | null,
  "tool_use_id": null,
  "created_at": "...",
  "completed_at": "..." | null,
  "delivered_at": "..." | null
}
```

- `seq` is allocated at the moment of tmux send (the `_pre → sent` transition).
- delivery status update appends `_replace: true` (same id, same seq) with new `status` and `delivered_at`/`completed_at`.

**Critical invariant**: file `id` equals DB `messages.id` after the `_pre → sent` transition. Reader dedup works correctly because the last occurrence for a given id is always authoritative.

### 2.2 DB rows

`messages` table reflects sent/delivered/executed state only. Pre-delivery columns `status IN ('PENDING', 'QUEUED', 'CANCELLED')` with `source IN ('web', 'task', 'plan_continue')` do **not** exist in steady state. Enum values stay in the codebase (used by other paths / history).

### 2.3 In-memory index

`display_writer` maintains a per-agent index:

```python
_predelivery_index: dict[str, dict[str, dict]]
    # agent_id -> {msg_id -> entry_dict}
```

- Rebuilt at startup by one pass over each active agent's display file (piggy-back on `startup_rebuild_all`).
- Writer API mutates it on every `predelivery_*` call.
- Reader API (`predelivery_list`) returns values without touching disk.
- Reader endpoint `GET /display` uses it to populate `data.queued` on initial (tail_bytes) loads.
- On incremental (`offset`) polls, `data.queued = null` (frontend ignores).

### 2.4 Rebuild (read-before-truncate)

`rebuild_agent(agent_id)`:

```
1. open file, read all lines into memory
2. parse, dedup by id (last-wins), collect:
     - delivered entries (have seq)
     - pre-delivery entries (_pre: true, not tombstoned, not 'cancelled' if we choose not to preserve cancelled — see §6 open question)
3. reset display_seq=NULL in DB for this agent
4. truncate file
5. flush_agent(agent_id) — walk DB rows, re-append with fresh seq
6. append the preserved pre-delivery entries back to the file
7. rebuild in-memory predelivery_index from the preserved entries
```

Entire operation under one flock.

## 3. Writer API (additions to `display_writer.py`)

```python
def predelivery_create(agent_id: str, entry: dict) -> str:
    """Append _queued + _pre line. Update index. Return entry id.
    Caller populates id (or omits — we allocate uuid4-12hex).
    """

def predelivery_update(agent_id: str, msg_id: str, patch: dict) -> None:
    """Merge patch into existing entry (content, scheduled_at, metadata, status).
    Append _queued + _pre + _replace line. Update index.
    Raises KeyError if msg_id not in index or already has sent-state DB row.
    """

def predelivery_cancel(agent_id: str, msg_id: str) -> None:
    """Soft-cancel: set status='cancelled' via predelivery_update.
    Keeps the entry visible as a grey bubble. Fail if not in queued/scheduled.
    """

def predelivery_tombstone(agent_id: str, msg_id: str) -> None:
    """Hard-delete: append {id, _deleted: true}. Remove from index.
    Fail if status is NOT 'cancelled' (must soft-cancel first).
    """

def predelivery_list(agent_id: str) -> list[dict]:
    """Return all current pre-delivery entries for the agent. Cheap — in-memory."""

def predelivery_get(agent_id: str, msg_id: str) -> dict | None:
    """Return the current entry or None."""

def predelivery_promote_to_sent(
    agent_id: str,
    msg_id: str,
    seq: int,
    sent_line: dict,
) -> None:
    """Atomic _pre → sent transition. Under one flock:
       1. append tombstone for msg_id (evicts _pre line from reader partition)
       2. append sent_line (regular entry with seq, status='sent')
    Remove msg_id from predelivery_index.
    The caller already INSERTed the DB row; this function only writes file.
    """
```

Existing functions:

- `flush_queued_entry`, `update_queued_entry`, `mark_deleted`, `promote_to_delivered` — deprecated in Phase 1 (no more callers after Phase 2), deleted in Phase 3.
- `flush_agent`, `update_last` — unchanged.
- `rebuild_agent`, `startup_rebuild_all` — extended in Phase 1 with read-before-truncate + index build.

## 4. Reader / WS flow

### 4.1 `GET /display`

- `tail_bytes > 0` (initial load): return delivered entries from file tail + **full `predelivery_list(agent_id)` as `data.queued`**.
- `offset > 0` (incremental poll): return delivered delta + **`data.queued = null`**. Frontend does NOT touch queued state.
- Both cases: `data.deleted` (new) returns ids that were tombstoned IN THIS WINDOW (for post-send messages that somehow got tombstoned — shouldn't happen normally but kept for safety).

### 4.2 WS events (new or repurposed)

Backend emits these whenever pre-delivery state changes. Frontend reacts directly, bypassing poll.

| Event               | Emitted by                             | Payload                         | Frontend action                          |
|---------------------|----------------------------------------|---------------------------------|------------------------------------------|
| `predelivery_created` | `predelivery_create`                   | `{entry}`                       | Add to queued state                      |
| `predelivery_updated` | `predelivery_update`, `predelivery_cancel` | `{msg_id, patch}`           | Merge into queued state                  |
| `predelivery_tombstoned` | `predelivery_tombstone`            | `{msg_id}`                      | Remove from queued state                 |
| `message_sent`      | `predelivery_promote_to_sent`          | `{msg_id, seq, entry}`          | Remove from queued; add to delivered with seq |
| `message_delivered` | sync engine at DB UPDATE (status=delivered) | `{msg_id, delivered_at}`   | Update entry's status / delivered_at     |
| `message_executed`  | slash `mark_delivered_and_completed`   | `{msg_id, completed_at}`        | Update entry's status / completed_at     |

Initial load or WS reconnect: frontend calls `fetchDisplay(tail_bytes=50000)` which brings full pre-delivery list — any missed events are backfilled.

### 4.3 Frontend state

- Poll (every 3-10s): only updates `delivered` messages by merging offset delta.
- WS: updates pre-delivery state directly.
- No more `(data.queued || []).filter(...)` — that line is gone.

## 5. Lifecycle walkthroughs

### 5.1 Normal send (agent IDLE)

```
1. User clicks send
2. POST /messages → backend:
   a. predelivery_create(agent, {status: "queued", content, source: "web", ...})
   b. WS emit predelivery_created
   c. Return synthetic MessageOut built from the entry dict
   d. Enqueue dispatcher tick (immediate, since idle)
3. Dispatcher tick (same async cycle or next ms):
   a. send_tmux_message(pane, content)
   b. On success, in one DB transaction + one flock:
      - INSERT Message(id=predelivery_id, status=sent, source=web, content,
                       metadata=..., created_at, ..., seq=next_seq)
      - predelivery_promote_to_sent writes tombstone + sent line
      - commit
   c. WS emit message_sent
4. CC processes → UserPromptSubmit hook → sync wake
5. Sync reads JSONL, ContentMatcher matches the sent row, UPDATE to
   status=delivered + jsonl_uuid + delivered_at
6. display_writer.update_last appends _replace line
7. WS emit message_delivered
```

Total time POST → sent: ~100ms. POST → delivered: 200ms–few seconds.

### 5.2 Busy send (agent EXECUTING)

```
1. POST /messages → predelivery_create(status: "queued"); WS; return
2. Dispatcher tick: skip (agent busy, no send)
3. Agent finishes turn, stop_hook fires, sync processes stop_hook
4. sync schedules dispatch_pending_message
5. dispatch_pending_message:
   a. entries = predelivery_list(agent) filtered status=queued, no scheduled_at
   b. Pick first. send_tmux + promote_to_sent (same atomic step as 5.1.3)
6. ...continues like 5.1.4 onward.
```

### 5.3 Scheduled send

```
1. POST /messages with scheduled_at → predelivery_create(status: "scheduled")
2. Dispatcher scheduled tick, every few seconds:
   a. due = predelivery_list filtered status=scheduled, scheduled_at <= now
   b. For each: send_tmux + promote_to_sent
```

### 5.4 Edit (queued or scheduled)

```
1. PUT /messages/{id} with {content?, scheduled_at?}
2. Backend: predelivery_update(patch) → WS predelivery_updated
3. Frontend: merges patch into bubble
```

Not allowed once state is cancelled/sent/delivered/executed (400).

### 5.5 Two-stage delete

Stage 1: user clicks Delete on a queued/scheduled bubble:
```
DELETE /messages/{id} → backend: predelivery_cancel → WS predelivery_updated
Bubble turns grey, label "cancelled". Still in queued area.
```

Stage 2: user clicks Delete on a cancelled bubble:
```
DELETE /messages/{id} → backend: predelivery_tombstone → WS predelivery_tombstoned
Bubble disappears completely. Cannot be recovered.
```

Backend distinguishes stages by current status (`queued/scheduled` → cancel, `cancelled` → tombstone). `sent` and later return 400.

### 5.6 Cancel after tmux send race

User cancels while dispatcher's send_tmux is in flight. Two orderings:

**Order A** (cancel wins): `predelivery_cancel` completes before `send_tmux_message` returns → dispatcher sees the state change at `promote_to_sent` time (reads from index), **aborts the promote**, does not INSERT DB row. tmux got the text but it's an orphan in the pane; user has a "cancelled" bubble. CC might still UserPromptSubmit; sync's ContentMatcher doesn't find a matching sent DB row (none exists) → creates a fresh CLI-source row as today's fallback (line `sync_engine.py:247-262`).

**Order B** (send wins): `promote_to_sent` completes before `predelivery_cancel` is applied → DB has the sent row; `predelivery_cancel` returns 400 (already sent). Frontend shows an error toast; user sees delivered bubble.

Both orderings are consistent. The atomic flock on promote guarantees one of them wins, never both.

### 5.7 Slash command delivery

```
/compact: sent → delivered → (PostCompact hook) → executed
/clear:   sent → delivered → (SessionStart hook source=clear) → executed
/loop:    sent → delivered → (user stops loop) → executed
other:    sent → delivered (stays there forever; never executed)
```

`slash_commands.mark_delivered_and_completed` writes both delivered_at and completed_at in one transaction → file has status='executed' line.

### 5.8 Startup / restart

```
startup_rebuild_all iterates active agents. For each:
  read_before_truncate rebuilds file.
  predelivery_index rebuilt from preserved _pre entries.
```

If backend crashed between "tmux sent successfully" and "DB commit of sent row", behavior on restart:
- `_pre` entry still in file (we never wrote the tombstone in the aborted promote)
- No DB sent row
- dispatcher on next tick may attempt re-send. CC may receive duplicate input if it already processed the first send.
- Mitigation: `redispatch_stuck_queued` today has a 10s grace window; reuse it. Still not perfect (possible duplicate on CC's side), but rare.

## 6. Call-site inventory

### 6.1 `orchestrator/routers/agents.py`

| Line | Function | Change |
|------|----------|--------|
| 2543-2747 | `send_agent_message` | Replace DB INSERT path with `predelivery_create`. Return synthetic MessageOut. Kick dispatcher. |
| 2762-2788 | `cancel_message` (DELETE) | Branch on predelivery status: queued/scheduled → `predelivery_cancel`; cancelled → `predelivery_tombstone`; else 400. |
| 2791-2828 | `update_message` (PUT) | Replace DB UPDATE with `predelivery_update`. |
| 2411-2509 | `get_agent_display` | Populate `data.queued` from `predelivery_list` only on initial load; null on incremental. |
| 2512-2540 | `wake_agent_sync` | No direct change; transitively OK. |

### 6.2 `orchestrator/agent_dispatcher.py`

| Line | Function | Change |
|------|----------|--------|
| 2456-2535 | `dispatch_pending_message` | Query `predelivery_list` instead of DB. On send success: INSERT DB sent row + `predelivery_promote_to_sent` + WS. |
| 2537-2599 | `redispatch_stuck_queued` | Same pattern; source = `predelivery_list` filtered by age and status=queued but already-send-attempted. Need a flag (new field `_send_attempted_at`) on `_pre` entry so we don't spam send on every tick. |
| 2860-2933 | `_dispatch_tmux_scheduled` | Read scheduled entries from `predelivery_list`; promote same way. |
| 2948-3060 | `_prepare_dispatch` | Factored into `_prepare_predelivery_payload` returning an entry dict for `predelivery_create`. Retain DB-row-creating variant only for the post-send branch (used by `predelivery_promote_to_sent` caller). |
| 1562-1568 | `next_dispatch_seq` | Accept both DB.dispatch_seq and predelivery entries' `dispatch_seq`; return max+1. |
| 2009-2026 | `_fail_pending_messages` | New variant `_fail_all_predelivery` for terminal agent shutdown: walks predelivery_list, tombstones each. |

### 6.3 `orchestrator/sync_engine.py`

| Line | Function | Change |
|------|----------|--------|
| 151-262 | `_promote_or_create_user_msg` | Candidates come from `predelivery_list` only as a **sanity fallback**. Primary match target is sent-state DB rows (today's QUEUED-state rows). On match of a sent row: UPDATE to delivered (same as today's promote path simplified — no `_queued` → `_deliverable` transition, just a status update). |
| 583-597 | post-commit | `update_last` only (drop `promote_to_delivered`). |
| 829-859 | `_compact_msg` reconciliation | Dead code, delete (PostCompact handles via slash_commands). |
| interrupt/stop branches | | Call migrated `dispatch_pending_message` (3.2). |

### 6.4 `orchestrator/display_writer.py`

| Line | Function | Change |
|------|----------|--------|
| 215-299 | `flush_agent` | Unchanged. |
| 302-336 | `update_last` | Unchanged. |
| 339-455 | `flush_queued_entry`, `update_queued_entry`, `mark_deleted` | Delete in Phase 3 (no callers after Phase 2). |
| 458-517 | `promote_to_delivered` | Delete in Phase 3. |
| 520-585 | `rebuild_agent` | Rewrite as read-before-truncate. Build predelivery_index. |
| 599-625 | `startup_rebuild_all` | Call new `rebuild_agent`; no external change. |
| (new) | `predelivery_*`, `_predelivery_index` module state | §3. |

### 6.5 `orchestrator/slash_commands.py`

`mark_delivered`, `mark_completed`, `mark_delivered_and_completed`, `mark_loop_completed` (lines 237-468): since sent-state rows DO exist in DB under the new model (from the moment of tmux send), these functions can still look up the row by content prefix and UPDATE. For /compact and /clear they also set `completed_at` (→ status=executed). Minimal change from today.

### 6.6 `orchestrator/routers/hooks.py`

No direct change. Hooks remain wake-only; sync engine and slash_commands do all the writes.

### 6.7 `orchestrator/websocket.py`

Add event emitters:
- `emit_predelivery_created(agent_id, entry)`
- `emit_predelivery_updated(agent_id, msg_id, patch)`
- `emit_predelivery_tombstoned(agent_id, msg_id)`
- `emit_message_sent(agent_id, msg_id, seq, entry)`

Existing `emit_message_delivered` stays.

### 6.8 `frontend/src/pages/AgentChatPage.jsx`

| Line | Function | Change |
|------|----------|--------|
| 2452-2489 | `applyDisplayData` | Remove the `queued = (data.queued || []).filter(...)` block. For initial loads: merge `data.queued` into state. For incremental: ignore queued entirely. |
| 2684-2690 | `queuedMessages` useMemo | Keep. Filters state by `status IN ('queued', 'scheduled', 'cancelled')`. |
| 1185-1250 | Double-click menu | Gate by status: queued/scheduled → Copy/Modify/Delete; cancelled → Copy/Delete; sent+ → Copy only. |
| 1336-1340 (approximately) | Cancelled bubble styling | Restore the grey styling removed in commit 89e4999: `bg-gray-400 text-white` bubble; grey source badge; "cancelled" label in the meta row. |
| 1439-1469 | Check icon | Three-state: status=sent → faded grey `d="M5 13l4 4L19 7"` opacity 0.5; status=delivered → green `d="M5 13l4 4L19 7"` solid; status=executed → green double stroke (existing slash-cmd SVG pattern with two paths). |
| 3154-3202 | WS handlers | Add handlers for `predelivery_created`, `predelivery_updated`, `predelivery_tombstoned`, `message_sent`. Update `message_delivered` to also set status='delivered'. Add `message_executed` handler. |

### 6.9 `frontend/src/lib/api.js`

Unchanged. URL/JSON contracts are the same.

## 7. Migration (one-shot, startup)

Run once at first startup after Phase 2 deploys:

```python
def migrate_predelivery_to_file():
    for agent_id in active_agents:
        rows = db.query(Message).filter(
            Message.agent_id == agent_id,
            Message.source.in_(('web', 'task', 'plan_continue')),
            Message.status.in_(('PENDING', 'QUEUED')),  # legacy
            Message.delivered_at.is_(None),
        ).all()
        for m in rows:
            entry = build_predelivery_entry_from_row(m)
            predelivery_create(agent_id, entry, skip_ws=True)
            db.delete(m)

        # Cancelled rows: already tombstoned in display, just delete
        db.query(Message).filter(
            Message.agent_id == agent_id,
            Message.source.in_(('web', 'task', 'plan_continue')),
            Message.status == 'CANCELLED',
        ).delete()

        db.commit()
```

Idempotent: subsequent runs find no matching rows.

## 8. Phased ship plan (3 phases, no shadow row)

### Phase 1 — Scaffolding + single bug-fix (low risk, zero behavior change for existing paths)

**Changes**:
- `display_writer.py`: add `predelivery_*` API + `_predelivery_index` + extended `rebuild_agent` (read-before-truncate). Keep all legacy functions. Old callers still work.
- `websocket.py`: add the new event emitters.
- `routers/agents.py:get_agent_display`: on initial load, merge `predelivery_list(agent_id)` into `data.queued`. On incremental poll, return `data.queued = null`. **This alone fixes the "queued bubble disappears" bug** for any caller that starts populating the index.
- `frontend/src/pages/AgentChatPage.jsx:applyDisplayData`: change the incremental-poll path to NOT touch `queued` state (because the backend returns `null`).

**Does not change**: send/cancel/edit endpoints, dispatcher, sync engine, slash commands — they continue to create DB rows as today.

**Net effect**: nothing observable changes; but the index is available and the read path is ready to source from it.

**Verify**: existing integration tests pass. New unit tests for predelivery API + read-before-truncate.

### Phase 2 — Cut over (all 4 surface areas at once)

**Changes**:
- `routers/agents.py`: send/cancel/edit rewritten (§6.1).
- `agent_dispatcher.py`: dispatcher reads predelivery, promotes atomically (§6.2).
- `sync_engine.py`: content-match against sent-state DB rows (unchanged shape, just no pre-delivery DB updates) (§6.3).
- `slash_commands.py`: unchanged in shape, just working against sent-state DB rows (§6.5).
- `websocket.py`: actually emit the new events now that they drive frontend.
- `frontend/src/pages/AgentChatPage.jsx`: WS handlers added; applyDisplayData cleaned up; menu/styling/check icon updated (§6.8).
- `main.py`: register one-shot migration to run before `startup_rebuild_all`.

**Single cutover PR**. Large but coherent — one-way-door with full test coverage.

**Verify**:
- Send (IDLE + BUSY + scheduled): bubble appears → sent (grey single) → delivered (green single).
- /compact: executed double green.
- /clear: executed double green.
- Cancel stage 1: grey bubble.
- Cancel stage 2: bubble gone.
- Edit: bubble content updates.
- Startup with pre-existing pre-delivery DB rows: migration clears them, predelivery file entries take over.
- Frontend regression: queued bubble survives 10 consecutive polls without any new writes.

**Rollback**: git revert. Migration is one-way (DB rows are gone); but the predelivery file is fully self-sufficient, so rolling back before-and-after the migration is straightforward if the legacy code path is still in the previous commit.

### Phase 3 — Delete dead code

**Changes**:
- Remove `flush_queued_entry`, `update_queued_entry`, `mark_deleted`, `promote_to_delivered`.
- Remove DB queries that filter `status IN ('PENDING', 'QUEUED', 'CANCELLED') AND source IN (...)` (should be no live callers).
- Update `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE_REFACTOR.md` (mark partially superseded), this document (change status header).
- Optional: drop `MessageStatus.CANCELLED` from enum (audit first — only if 0 callers).

**Verify**: full suite green.

## 9. Risks / open questions

### 9.1 Cancelled bubble preservation across `rebuild_agent`

Read-before-truncate preserves all `_pre` entries including `status='cancelled'`. If we intend cancelled to survive restarts and rebuilds, keep them. If rebuild is the natural "clear old cancelled messages" moment, drop them. **Recommend keep** — consistency with user expectation that cancelled bubbles are a persistent grey row until the user hard-deletes.

### 9.2 Sent-state orphans

If sync never matches a sent-state DB row (content drift, CC never received, etc.), the row sits as status=sent forever with a faded grey check. Per decision: user can manually delete via a future UI affordance (not in this refactor's scope). This is acceptable because it shouldn't happen in steady state; when it does, it's a signal for the separate 3944f4ba task.

### 9.3 MessageOut shape fidelity

`send_agent_message` returns a synthetic MessageOut built from the predelivery entry dict. Frontend consumers read: `id`, `status`, `scheduled_at`, `content`, `metadata`, `source`, `created_at`, `delivered_at`, `completed_at`. All present in the entry (some are null). Add a Pydantic validation unit test in Phase 1.

### 9.4 WS event ordering

Between `predelivery_created` and `message_sent` (for the IDLE path), the frontend may see them in very quick succession (~ms). Both handlers are idempotent: `predelivery_created` adds to queued state; `message_sent` removes from queued and adds to delivered with seq. Order should not matter materially. Add a Phase 1 unit test.

### 9.5 Re-dispatch on crash / restart

Between tmux send success and DB commit, backend crash leaves the `_pre` entry intact with no DB row. On restart, `redispatch_stuck_queued` will re-send after its 10s grace. CC may then see the message twice. Acceptable; documented. Future mitigation: write a `_sent_at_tmux` marker to the file before DB commit, use as dedup.

### 9.6 `dispatch_seq` ordering

`dispatch_seq` tracks per-agent monotonic send order, used for ordering within a queued window. Under the new model:
- Pre-delivery entries may carry a tentative `dispatch_seq` set at `predelivery_create` time.
- DB rows use the same `dispatch_seq` at `promote_to_sent` time.
- `next_dispatch_seq` computes max over both sources.

No correctness concern, just ensure the code consistently reads from both.

### 9.7 Interactive cards (AGENT role)

Interactive cards (AskUserQuestion, ExitPlanMode, permission modals) are AGENT-role messages with `meta_json.interactive` array. They are **post-delivery** by definition (CC emitted them). They continue to live in DB and flow through `flush_agent` / `update_last`. No change.

## 10. Auditor checklist

After all three phases:

### Data invariants
- [ ] `SELECT count(*) FROM messages WHERE status IN ('PENDING', 'QUEUED', 'CANCELLED') AND source IN ('web', 'task', 'plan_continue')` returns 0.
- [ ] For any display-file entry with `_pre: true`, no row in `messages` exists with that id.
- [ ] For any display-file entry without `_pre` (post-send), a row in `messages` exists with the same id.
- [ ] No display file has a `_queued: true` line without `_pre: true` for any entry dated after Phase 2 deploy.

### Regression tests (should pass)
- [ ] Send-while-idle → bubble visible within 100ms, transitions to sent (grey single), then delivered (green single).
- [ ] Send-while-busy → queued grey-at-bottom bubble; when agent idle, transitions to sent.
- [ ] Scheduled send → scheduled bubble with clock; at due time, transitions to sent.
- [ ] Cancel stage 1 of a queued message → bubble greys, label "cancelled".
- [ ] Cancel stage 2 of a cancelled bubble → bubble disappears.
- [ ] Edit a queued message → content updates in place.
- [ ] Modify button NOT visible on cancelled bubble.
- [ ] Modify/Delete buttons NOT visible on sent+ bubbles (Copy only).
- [ ] /compact → after PostCompact hook, bubble shows green double check.
- [ ] /clear → after SessionStart hook, bubble shows green double check.
- [ ] Bubble visible across 10 consecutive incremental polls with no new writes (primary regression).
- [ ] WS disconnect → reconnect: initial fetch restores full pre-delivery state.
- [ ] Restart server with a pre-delivery entry in file: entry visible immediately on chat page load.
- [ ] New agent with task: first task message visible within 100ms of chat page open (not 1-3s).

### Code audit
- [ ] `flush_queued_entry`, `update_queued_entry`, `mark_deleted`, `promote_to_delivered` no longer exist in `display_writer.py`.
- [ ] `grep -rn flush_queued_entry orchestrator/` is empty.
- [ ] No DB query of the form `Message.status IN (PENDING, QUEUED)` with `source IN (web, task, plan_continue)` anywhere.
- [ ] `rebuild_agent` preserves `_pre` entries across truncate.
- [ ] All new WS events have handlers in frontend.
- [ ] Synthetic MessageOut from send endpoint passes `MessageOut.model_validate`.

### Migration
- [ ] On first startup after deploy, migration moves existing PENDING/QUEUED rows to file and deletes them.
- [ ] Migration is idempotent (second startup finds nothing to migrate).
- [ ] Existing CANCELLED rows are deleted (file already tombstoned).

## 11. Critical files

Backend:
- `orchestrator/display_writer.py`
- `orchestrator/routers/agents.py`
- `orchestrator/agent_dispatcher.py`
- `orchestrator/sync_engine.py`
- `orchestrator/slash_commands.py`
- `orchestrator/websocket.py`
- `orchestrator/main.py` (migration hook)
- `orchestrator/schemas.py` (DisplayEntry extensions for `_pre`)

Frontend:
- `frontend/src/pages/AgentChatPage.jsx`
- `frontend/src/lib/api.js` (no content change; just verify)
