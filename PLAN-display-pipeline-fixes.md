# Display Pipeline — Remaining Fixes

> Feed this plan to an agent. Read CLAUDE.md first, then this file.
> Read the memory file at `~/.claude/projects/-home-jyao073-cc-orchestrator/memory/project_message_sync_redesign.md` for full architecture context.

## Architecture (DO NOT deviate)

```
JSONL (Claude CLI) → hooks → sync_engine → DB (display_seq=NULL) → display_writer → display file → frontend
```

The **display file** (`data/display/{agent_id}.jsonl`) is the SOLE source for chat rendering. `seq` is the render order. No fallbacks. No re-sorting with fallback keys.

"Queued" means `display_seq IS NULL` — nothing else.

---

## Task 1: Fix stale `delivered_at` in display file

**Problem:** When sync promotes a web message (sets `delivered_at` in DB), the display file entry still has `delivered_at: null` because nobody calls `update_last` after promotion.

**Where:** `orchestrator/sync_engine.py`, in the user-turn processing inside `sync_import_new_turns`.

**What to do:** Find every place where a web/task message gets promoted (i.e., `delivered_at` is set on an existing message). After `db.commit()`, call:
```python
from display_writer import update_last as _update_display
_update_display(ctx.agent_id, _web_msg.id)
```

Search for all sites where `delivered_at` is set on an existing message (grep for `delivered_at =` in sync_engine.py). There are multiple promotion paths:
- UUID dedup path (message already exists, might update delivered_at)
- Content-match promotion path
- FIFO fallback promotion path

Each one that sets `delivered_at` on a message that already has `display_seq` needs an `update_last` call after commit.

**Verify:** Send a message from web UI while agent is idle. After sync picks it up, check:
```bash
# DB should have delivered_at set
python3 -c "from database import *; from models import *; init_db(); db=SessionLocal(); m=db.query(Message).filter(Message.agent_id=='AGENT_ID', Message.source=='web').order_by(Message.created_at.desc()).first(); print(m.delivered_at)"

# Display file should also have delivered_at set (check last line)
tail -1 data/display/AGENT_ID.jsonl | python3 -m json.tool | grep delivered
```

---

## Task 2: Verify `/compact` and slash commands work correctly

**Problem:** `/compact` has `jsonl_uuid=None` because slash commands don't appear in the JSONL. Previously this caused it to appear in the "queued" list. The fix (using `display_seq IS NULL` instead) is committed but needs verification.

**What to do:**
1. Open agent de544a19f25a in the web UI
2. Verify `/compact` appears exactly ONCE (not duplicated)
3. Verify "say hi to me" (the mid-generation message) appears exactly ONCE
4. Send a new `/compact` to a test agent and verify no duplication

---

## Task 3: Verify display file rebuild is truly append-only

**Problem:** `rebuild_agent` resets `display_seq` to NULL and calls `flush_agent` which re-appends all messages. The file should grow, never shrink.

**What to do:**
1. Check current `rebuild_agent` in `orchestrator/display_writer.py`
2. Verify it does NOT call `os.unlink()` on the display file (it was fixed to not do this)
3. If it still deletes the file, remove that — only reset display_seq in DB and re-flush
4. Test: trigger a session rotation on a test agent, verify the display file only grew (wc -l before and after)

---

## Task 4: End-to-end smoke test

Create a fresh agent and walk through the full pipeline:

1. **Send message from web** → verify it appears as queued (dimmed) bubble
2. **Wait for hook + sync** → verify bubble becomes delivered (normal color), `delivered_at` set in both DB and display file
3. **Agent responds** → verify response appears in correct order (after user message)
4. **Send `/compact`** → verify it appears once, agent compacts, post-compact messages render correctly
5. **Send message during agent tool use** → verify it appears once, not duplicated
6. **Scroll up** → verify older messages load from display file (offset pagination)
7. **Restart server** → verify `startup_rebuild_all` runs, display files rebuilt, chat renders correctly

---

## Task 5: Clean up dead code

After verifying everything works:

1. Check if `fetchMessages` is still imported anywhere in `AgentChatPage.jsx` — it shouldn't be
2. Check if the legacy `refreshMessages` with `syncHint` parameter is referenced anywhere — clean up callers
3. Check if any WebSocket event handler still calls `fetchMessages` as a fallback — should use `refreshMessages` (which is now `refreshDisplay`)

---

## Do NOT

- Do not add fallbacks to the legacy messages API
- Do not sort by anything other than `seq` for display file messages
- Do not use `jsonl_uuid IS NULL` to detect queued messages — use `display_seq IS NULL`
- Do not delete display file contents (append-only)
- Do not make the poll safety net write to DB — it's audit-only
