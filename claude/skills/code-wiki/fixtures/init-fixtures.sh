#!/usr/bin/env bash
# Initialize each fixture as a git repo with at least 2 commits.
#
# Idempotent: re-running on an already-initialized fixture is a no-op
# (skips fixtures whose .git/ already exists).
#
# The .git/ directories created here are gitignored in the plugin's
# .gitignore so they don't end up tracked in the parent claude-plugins repo.

set -euo pipefail

FIXTURE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

init_one() {
    local dir="$1"
    if [[ -d "$dir/.git" ]]; then
        echo "skip: $dir (already initialized)"
        return
    fi
    echo "init: $dir"
    (
        cd "$dir"
        git init -q -b main
        git config user.email "fixtures@code-wiki.test"
        git config user.name "code-wiki fixtures"
        # Commit 1: initial state.
        git add -A
        git commit -q -m "initial fixture state"
        # Commit 2: a trivial follow-up so diffs have something to walk.
        echo "" >> "$(git ls-files | head -n 1)"
        git add -A
        git commit -q -m "trivial second commit"
    )
}

for name in minimal monorepo mixed; do
    target="$FIXTURE_ROOT/$name"
    if [[ ! -d "$target" ]]; then
        echo "warn: $target does not exist; skipping"
        continue
    fi
    init_one "$target"
done

echo "done"
