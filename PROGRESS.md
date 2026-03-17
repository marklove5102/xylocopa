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


## 2026-03-14 — Daily Insights

1. `UserPromptSubmit` hook fires BEFORE Claude writes to JSONL — the sync loop wakes but sees no new data, so `delivered_at` was only set on the next 30s poll cycle, causing 20+ second delivery delays; fix: mark `delivered_at` directly in the hook handler (`main.py:hook_agent_user_prompt`).
2. "Thinking" was a synthetic `tool_activity("start")` emitted by the backend with no matching `"end"` event — caused permanent double "Thinking" bubbles; fix: removed the fake event entirely since the frontend's existing `TypingIndicator` already handles the pre-tool state naturally.
3. `useStreamingAgents` had a `useEffect` that polled `agents` and overwrote WebSocket-driven `tool_activity` signals based on `is_generating` — agents visibly executing tools showed "syncing" on the list page; fix: simplified to pure hook-driven logic (any hook → active, Stop hook → inactive), removed `agents` parameter entirely.
4. Stale JSONL auto-kill (`agent_dispatcher.py:5731`) used `kill_tmux=False`, but `_auto_detect_cli_sessions` revived any stopped agent with an alive tmux pane — creating an infinite stop/revive loop every ~60 seconds; fix: removed all three auto-kill paths entirely.
5. `_patch_interactive_answer` iterated messages DESC and early-returned on the first match (a dismiss answer), leaving a duplicate message with `answer=null` that permanently blocked the chat input; fix: changed to `continue` past dismiss answers and patch all copies.
6. `parser_interactive_by_id` was reset to `{}` at 3 sites (sync loop start, compact handler, turn-count-decrease fallback) after every full parse, so incremental parses couldn't link `tool_result` entries back to interactive cards — plan approvals submitted in tmux were silently lost; fix: seed from parsed turns' metadata at all 3 reset points.
7. `PreCompact` hook was setting `compact_notified = True` before JSONL rewrite completed, causing `sync_handle_compact` to re-parse the old file; fix: `PreCompact` now only sets `compact_in_progress` (pauses sync), `SessionStart(source="compact")` sets `compact_notified` after rewrite is done.
8. Content-based dedup in `_parse_session_turns` (line 1564) drops legitimate repeated user prompts with different UUIDs but identical text — repeated "continue" commands, identical follow-ups silently collapse into one turn.
9. Hook-created interactive cards use `tool_use_id` as `jsonl_uuid` while sync import uses JSONL entry UUID — different namespaces cause duplicate messages for the same interactive card, and empty `content=""` makes prefix dedup checks degenerate.
10. CLI-triggered `UserPromptSubmit` hook can falsely mark an unrelated pending web message as delivered — the FIFO query (`source="web"`, `delivered_at IS NULL`, `order_by(created_at.asc())`) has no way to verify which prompt actually triggered the hook.
11. `delivered_at` is used as both transport acknowledgement and conversation sort key (`COALESCE(delivered_at, far_future)`) — makes message ordering unstable and can temporarily place an assistant reply above the user message that caused it.
12. Assistant turn import in `sync_import_new_turns` has no UUID/content dedup — only user turns are deduplicated, so hook-created and sync-imported assistant messages can create duplicates.
13. Frontend placeholder priority `tmuxMode > disabled` masks the real input-blocking reason — user sees "Send via tmux..." instead of "Answer the question above first" when an unanswered interactive card exists.
14. Signal-based interactive blocking proposed as replacement for message-scanning approach: `PreToolUse` hook → emit `interactive_block`, answer endpoint or Stop hook → emit `interactive_unblock`, with API fallback for page refresh.
15. There are no Claude Code hooks for thinking/extended thinking — only tool execution (`PreToolUse`/`PostToolUse`), session lifecycle, and permissions; any "thinking" indicator must be synthetic.
16. Claude Code model IDs (`claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`) in `constants.js` are already current; the 1M context window is inherent to the Opus 4.6 model with no CLI flag needed; the L/M/H toggle controls `--effort` (reasoning effort), not context size.
17. Orphan tmux sessions (e.g., `cc-test` alongside `ah-c3cb9ec3`) result from auto-kill + manual resume — the orchestrator rotates to a new `ah-*` session but the original shell persists; the UI correctly shows only managed agents.
18. `main.py` at 7600 lines and `agent_dispatcher.py` at 6400 lines are the biggest maintainability risks — splitting into route modules is the highest-ROI refactor.
19. The project's architecture maturity comes from a convergence pattern visible in git history: complex solution → real bugs expose fragility → simplify to minimal reliable approach (session detection: 5 paths → 2, sync: incremental → full+hook, delivery: matching → direct marking).
20. Inbox UI redesigned: "Tasks" renamed to "Inbox", filter tabs (Planning/Executing/Review/Done) removed to show only inbox perspective, nav reordered to Inbox→Projects→New→Agents→Git, collapsed card tags removed.
21. Send button and AI batch button on inbox cards were using different flows from standard task dispatch (`_build_task_prompt` + `_build_agent_prompt`); unified to use the `/api/v2/tasks/{task_id}/dispatch` endpoint.
22. Drag-to-reorder on inbox cards was too easily triggered during scrolling — increased hold threshold to 350ms and disabled horizontal movement animation during vertical reordering.
23. `_update_stale_interactive_metadata` only backfills answers found in JSONL — if a conversation moves past an interactive card without a parseable `tool_result`, the card stays `answer=null` forever with no correction mechanism.
24. Stress tests confirmed: 10 rapid-fire messages and messages up to 5000 chars are accepted, but agents under load only process 1-2 of 5 queued messages before session stops — the queue dispatch pipeline doesn't reliably drain under concurrent load.
25. Direct tmux send is non-atomic: text is sent to tmux first, then the `Message` row is created — a server crash between those steps means Claude received the prompt but the DB never records it.

### 2026-03-17 | Task: Switch license from MIT to Apache 2.0 | Status: success
- What: Created root LICENSE file with Apache 2.0 text, updated README.md reference from MIT to Apache 2.0
- Lesson: Straightforward — no issues
