#!/bin/bash
# Install git hooks from tools/git-hooks/ into .git/hooks/ as symlinks.
#
# Why this exists:
#   Git does not — and by design cannot — track files under .git/hooks/.
#   If it did, `git clone` would let anyone execute arbitrary code on
#   your machine. So hooks have to be installed per clone, manually.
#
#   We keep the hook sources under tools/git-hooks/ (tracked, shared via
#   git), and this script symlinks them into .git/hooks/ (local only).
#   Symlinks mean future edits to the source files take effect immediately
#   without reinstalling.
#
# When to run:
#   • After first cloning the repo
#   • After moving the repo directory (symlinks are relative but .git/hooks
#     may have stale entries)
#   • After adding a new hook under tools/git-hooks/
#   (Editing an existing hook does NOT require rerunning — the symlink
#    already points at the live source.)
#
# Installed hooks:
#   post-commit — auto-rebuilds frontend/dist/ when a commit touches
#                 frontend/ sources. Closes the "commit → forgot to
#                 restart → serving stale dist" gap.

set -e

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

for src in tools/git-hooks/*; do
    [ -f "$src" ] || continue
    name=$(basename "$src")
    dest=".git/hooks/$name"

    if [ -e "$dest" ] && [ ! -L "$dest" ]; then
        backup="$dest.backup-$(date +%s)"
        mv "$dest" "$backup"
        echo "Backed up existing $dest → $backup"
    fi

    chmod +x "$src"
    ln -sfn "../../$src" "$dest"
    echo "Installed $name → $dest"
done

cat <<'NOTE'

Done. The hooks are now active for THIS clone only.

The symlinks in .git/hooks/ are NOT tracked by git (git refuses to
track anything under .git/ for security reasons). If you clone this
repo elsewhere or on another machine, rerun this script there too.
NOTE
