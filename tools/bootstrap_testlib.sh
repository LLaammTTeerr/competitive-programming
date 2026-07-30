#!/usr/bin/env bash
# Clone or refresh the qhhoj/testlib checkout the pipeline compiles against, and
# print its path. Reads docs/usage-guide.md and plan.md from here rather than
# paraphrasing the API into a skill file, so the guidance always matches the
# header actually being compiled.
set -euo pipefail

TESTLIB="${XDG_CACHE_HOME:-$HOME/.cache}/testlib"
REPO=https://github.com/qhhoj/testlib.git

if [ ! -d "$TESTLIB" ]; then
    # Clone aside and move into place. Several problems can be prepared at once,
    # and a bare `[ -d ] || git clone` lets the second caller find a directory
    # that exists but is still half-populated, then build against it.
    staging="$(mktemp -d "$TESTLIB.XXXXXX")"
    git clone --depth 1 -q "$REPO" "$staging/testlib"
    mv -T "$staging/testlib" "$TESTLIB" 2>/dev/null || true   # first writer wins
    rm -rf "$staging"
fi
git -C "$TESTLIB" pull --ff-only -q 2>/dev/null || true       # offline, or lost a race

if [ ! -f "$TESTLIB/testlib.h" ]; then
    echo "bootstrap_testlib: $TESTLIB exists but has no testlib.h" >&2
    exit 1
fi

echo "$TESTLIB"
