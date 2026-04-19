#!/bin/bash
# Install git hooks from tools/git-hooks/ into .git/hooks/ as symlinks.
# Run once after cloning, or after pulling a hook update.

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

echo "Done. Hooks active for this clone only (not tracked by git)."
