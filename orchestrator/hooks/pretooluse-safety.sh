#!/bin/bash
# PreToolUse safety hook: deterministic guardrails for AgentHive agents.
# Blocks dangerous shell commands and out-of-project file modifications
# BEFORE they execute — replaces prompt-based safety rules with hard blocks.
#
# Exit 0 with permissionDecision:"deny" → block the tool call
# Exit 0 with no output → allow the tool call

INPUT=$(cat)

# Parse tool_name, command, file_path, cwd via python3 (jq not guaranteed)
eval "$(echo "$INPUT" | python3 -c "
import sys, json, shlex
d = json.load(sys.stdin)
ti = d.get('tool_input', {})
print(f'TOOL={shlex.quote(d.get(\"tool_name\", \"\"))}')
print(f'CMD={shlex.quote(ti.get(\"command\", \"\"))}')
print(f'FILE_PATH={shlex.quote(ti.get(\"file_path\", \"\"))}')
print(f'CWD={shlex.quote(d.get(\"cwd\", \"\"))}')
" 2>/dev/null)" || exit 0

[ -z "$TOOL" ] && exit 0

deny() {
  local reason="$1"
  cat <<EOJSON
{"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"$reason"}}
EOJSON
  exit 0
}

case "$TOOL" in
  Bash)
    [ -z "$CMD" ] && exit 0

    # --- git reset --hard (allowed only inside worktrees) ---
    if echo "$CMD" | grep -qP 'git\s+reset\s+--hard'; then
      if [[ "$CWD" != *"/.claude/worktrees/"* ]]; then
        deny "BLOCKED: git reset --hard is prohibited outside worktrees. Use a worktree for destructive resets."
      fi
    fi

    # --- git clean -f (any flag combo containing f) ---
    if echo "$CMD" | grep -qP 'git\s+clean\s+.*-[a-zA-Z]*f'; then
      deny "BLOCKED: git clean -f permanently deletes untracked files."
    fi

    # --- git checkout -- . / git restore . ---
    if echo "$CMD" | grep -qP 'git\s+(checkout\s+--\s+\.|restore\s+\.)'; then
      deny "BLOCKED: git checkout -- . / git restore . discards all uncommitted changes."
    fi

    # --- git push --force / -f ---
    if echo "$CMD" | grep -qP 'git\s+push\s+.*(-f\b|--force)'; then
      deny "BLOCKED: git push --force can overwrite remote history."
    fi

    # --- rm -rf (any flag combo with both r and f) ---
    if echo "$CMD" | grep -qP '\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)\b'; then
      deny "BLOCKED: rm -rf is prohibited. Remove specific files instead."
    fi

    # --- DROP TABLE / TRUNCATE ---
    if echo "$CMD" | grep -qiP '\b(DROP\s+TABLE|TRUNCATE)\b'; then
      deny "BLOCKED: Destructive DB operations (DROP TABLE / TRUNCATE) are prohibited."
    fi
    ;;

  Write|Edit)
    [ -z "$FILE_PATH" ] || [ -z "$CWD" ] && exit 0

    # Block writes outside the project directory
    REAL_FILE=$(realpath -m "$FILE_PATH" 2>/dev/null || echo "$FILE_PATH")
    REAL_CWD=$(realpath -m "$CWD" 2>/dev/null || echo "$CWD")

    if [[ "$REAL_FILE" != "$REAL_CWD"/* && "$REAL_FILE" != "$REAL_CWD" ]]; then
      deny "BLOCKED: Cannot modify files outside the project directory ($CWD)."
    fi
    ;;
esac

exit 0
