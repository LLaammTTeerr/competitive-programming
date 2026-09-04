"""Clone or refresh the testlib checkout the pipeline compiles against, and
print its path.

Portable core for `tools/bootstrap_testlib.sh`, which is now a thin `cd` +
`exec` wrapper around ``python3 -m tools.bootstrap_testlib`` (see that file).
Split out because the shell version's `mv -T` and reliance on `bash` do not
exist on Windows, where this module is reachable as a plain Python call.

Pinned to qhhoj/testlib, not the more commonly linked MikeMirzayanov/testlib:
qhhoj's checkout bundles ``docs/usage-guide.md`` and ``plan.md``, which match
the header this repo actually compiles checkers and validators against, and
`skills/preparing-tests/SKILL.md` sends the model to read both files straight
out of the cache rather than a paraphrase baked into a skill. Swapping the
remote would leave that instruction pointing at a doc tree that no longer
matches the compiled header.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NoReturn

DEFAULT_REPO = "https://github.com/qhhoj/testlib"

# Env var names, pulled out as constants (rather than string literals
# scattered through the functions below) so doc pins in
# `tools/tests/test_skill_docs.py` can assert against `bootstrap_testlib.
# CP_TESTLIB_ENV` etc. the same way `TestParallelSafetyDocs` pins README
# prose to `box_pool.POOL_ENV` instead of a copy of the string.
CP_TESTLIB_ENV = "CP_TESTLIB"
CP_TESTLIB_REPO_ENV = "CP_TESTLIB_REPO"
XDG_CACHE_HOME_ENV = "XDG_CACHE_HOME"


def _fail(message: str) -> NoReturn:
    print(f"bootstrap_testlib: {message}", file=sys.stderr)
    raise SystemExit(1)


def _warn(message: str) -> None:
    print(f"bootstrap_testlib: {message}", file=sys.stderr)


def _repo() -> str:
    return os.environ.get(CP_TESTLIB_REPO_ENV) or DEFAULT_REPO


def _default_cache_dir() -> Path:
    cache_home = os.environ.get(XDG_CACHE_HOME_ENV)
    base = Path(cache_home) if cache_home else Path.home() / ".cache"
    return base / "testlib"


def _has_testlib_h(directory: Path) -> bool:
    return (directory / "testlib.h").is_file()


def _run_git(args: list[str], *, required: bool) -> subprocess.CompletedProcess:
    """Run a git subcommand with no shell involved (Windows-safe).

    `required=True` turns a missing `git` binary or a non-zero exit into a
    fatal `_fail`; `required=False` (the best-effort `git pull` path) turns
    both into a warning on stderr and lets the caller carry on.
    """
    try:
        done = subprocess.run(
            args, capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        if required:
            _fail("git not found on PATH; install git or set CP_TESTLIB")
        _warn("git not found on PATH; skipping refresh")
        # returncode 0: the caller (the best-effort `git pull` path) only
        # warns again on a nonzero code, and this one was already warned
        # about above.
        return subprocess.CompletedProcess(args, 0, "", "")
    if done.returncode != 0 and required:
        detail = done.stderr.strip() or done.stdout.strip() or "unknown error"
        _fail(f"`{' '.join(args)}` failed: {detail}")
    return done


def _clone_into(target: Path, repo: str) -> None:
    """Clone `repo` aside, then move it into `target`.

    Several problems can be prepared at once, so a bare
    ``target.is_dir() or clone`` lets a second caller find a directory that
    exists but is still half-populated and build against it. Cloning into a
    uniquely-named sibling directory first and moving only the finished
    checkout into place means every reader either sees no `target` at all or
    a fully-populated one.
    """
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{target.name}.", dir=parent))
    try:
        cloned = staging / "testlib"
        _run_git(
            ["git", "clone", "--depth", "1", "-q", repo, str(cloned)],
            required=True,
        )
        if target.exists():
            # Another process won the race while we were cloning; our copy
            # is redundant. Discard it rather than fight over the name.
            return
        try:
            shutil.move(str(cloned), str(target))
        except OSError:
            # Lost the race between the check above and the move itself.
            if not target.exists():
                raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def bootstrap() -> Path:
    override = os.environ.get(CP_TESTLIB_ENV)
    if override:
        target = Path(override).resolve()
        if not target.is_dir():
            _fail(f"CP_TESTLIB={target} is not a directory")
        if not _has_testlib_h(target):
            _fail(f"CP_TESTLIB={target} exists but has no testlib.h")
        return target

    target = _default_cache_dir().resolve()

    if not _has_testlib_h(target):
        _clone_into(target, _repo())
        if not _has_testlib_h(target):
            _fail(f"{target} exists but has no testlib.h")
    else:
        # Offline, or a lost race with a sibling `git pull` — either way the
        # cache we already have is fine to build against.
        done = _run_git(
            ["git", "-C", str(target), "pull", "--ff-only", "-q"],
            required=False,
        )
        if done.returncode != 0:
            detail = done.stderr.strip() or done.stdout.strip()
            if detail:
                _warn(f"refresh of {target} failed, using cached copy: {detail}")

    return target


def main(argv: list[str] | None = None) -> int:
    del argv  # no options: matches the `.sh` this wraps, which takes none
    print(bootstrap())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
