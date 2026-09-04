#!/usr/bin/env bash
# Thin wrapper around `python3 -m tools.bootstrap_testlib` — the portable
# entry point, reachable as a plain Python call anywhere `mv -T` and `bash`
# itself are not guaranteed (e.g. Windows). Clones or refreshes the
# qhhoj/testlib checkout the pipeline compiles against, and prints its path.
#
# Pinned to qhhoj/testlib, not the more commonly linked MikeMirzayanov/testlib:
# qhhoj's checkout bundles docs/usage-guide.md and plan.md, which match the
# header this repo actually compiles checkers and validators against, and
# skills/preparing-tests/SKILL.md sends the model to read both files straight
# out of the cache rather than a paraphrase baked into a skill.
set -euo pipefail

# `cd` to the plugin root before invoking `-m tools.bootstrap_testlib`: that
# module is only importable with the plugin root as the working directory,
# and callers of this script run it from every directory imaginable.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

exec python3 -m tools.bootstrap_testlib "$@"
