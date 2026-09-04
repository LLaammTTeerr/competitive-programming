"""Configuration, read from the environment the MCP client launches us with.

The credentials live only here. Nothing in this package writes them to disk,
puts them in a log line, or lets them out through a tool's return value —
`PolygonError` messages are composed by hand rather than stringified from an
exception, because the signed query string carries `apiKey` and httpx embeds
the request URL in the text of every error it raises.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_URL = "https://polygon.codeforces.com/api/"

# Polygon rejects a request whose `time` is more than five minutes off its own
# clock, so a slow retry has to be re-signed rather than replayed.
MAX_CLOCK_SKEW_SECONDS = 300


class PolygonError(Exception):
    """Anything a tool should report as `{"ok": false, "error": ...}`.

    Carries the API method so a failure names what was being attempted, which
    matters when a tool call is one step of a long upload flow.
    """

    def __init__(self, message: str, method: str = ""):
        super().__init__(message)
        self.method = method


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value else default


@dataclass
class Config:
    api_key: str = ""
    api_secret: str = ""
    base_url: str = BASE_URL
    timeout: float = 30.0
    # The only directory a `path=` argument may point into. Unset means paths
    # are refused outright and content must be passed inline.
    root: Path | None = None
    # Floor on the gap between two requests, so a scripted upload of a few
    # hundred tests does not hammer Polygon.
    min_interval: float = 0.5

    @classmethod
    def from_env(cls) -> "Config":
        root = _env("POLYGON_MCP_ROOT")
        return cls(
            api_key=_env("POLYGON_API_KEY"),
            api_secret=_env("POLYGON_API_SECRET"),
            base_url=_env("POLYGON_BASE_URL", default=BASE_URL),
            timeout=float(_env("POLYGON_TIMEOUT", default="30")),
            root=Path(root).expanduser() if root else None,
            min_interval=float(_env("POLYGON_MIN_INTERVAL", default="0.5")),
        )

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)


def resolve_local_path(raw: str, root: Path | None) -> Path:
    """Resolve a caller-supplied path, or refuse it.

    A tool that accepts `path=` is a file-read primitive handed to a model, so
    it is confined to one directory the operator names with `POLYGON_MCP_ROOT`.
    Both sides are fully resolved before the comparison, so a symlink pointing
    out of the root is caught the same way `../..` is. With no root configured
    there is nothing to confine the read to, so every path is refused and the
    caller has to pass the content inline instead.
    """
    if root is None:
        raise PolygonError(
            "Reading from a path is disabled: POLYGON_MCP_ROOT is not set. "
            "Set it to the problem directory this server may read, or pass the "
            "content inline instead."
        )
    resolved = Path(raw).expanduser()
    try:
        base = root.resolve(strict=True)
    except OSError:
        raise PolygonError(
            f"POLYGON_MCP_ROOT does not exist: {root}"
        ) from None
    try:
        resolved = resolved.resolve(strict=True)
    except OSError:
        raise PolygonError(f"File not found: {raw}") from None
    if resolved != base and base not in resolved.parents:
        raise PolygonError(
            f"Refusing to read {resolved}: it is outside POLYGON_MCP_ROOT "
            f"({base})."
        )
    if not resolved.is_file():
        raise PolygonError(f"Not a regular file: {resolved}")
    return resolved
