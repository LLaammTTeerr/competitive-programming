"""Configuration, read from the environment the MCP client launches us with."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_URL = "https://codeforces.com"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def contest_base(contest_id: int, gym: bool = False, group_id: str = "") -> str:
    """Return the site-relative base path for a contest.

    Private group contests live under ``/group/<groupId>/contest/<id>`` and are
    not served by the public API at all, so they are reachable only by scraping
    those pages while signed in. ``group_id`` wins over ``gym`` when both given.
    """
    if group_id:
        return f"/group/{group_id}/contest/{contest_id}"
    return f"/{'gym' if gym else 'contest'}/{contest_id}"


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return default


def parse_cookie_string(raw: str) -> dict[str, str]:
    """Parse a browser-copied cookie header into a name→value mapping.

    Accepts a full ``a=1; b=2`` header, a single ``JSESSIONID=...`` pair, or a
    bare session id (which is assumed to be the JSESSIONID).
    """
    raw = (raw or "").strip().strip(";")
    if not raw:
        return {}
    if "=" not in raw:
        return {"JSESSIONID": raw}
    cookies = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        cookies[name.strip()] = value.strip().strip('"')
    return cookies


@dataclass
class Config:
    handle: str = ""
    password: str = ""
    cookie: str = ""
    api_key: str = ""
    api_secret: str = ""
    state_dir: Path = Path.home() / ".cache" / "cf-mcp"
    default_language: str = "GNU G++23"
    timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "Config":
        state = _env("CF_MCP_STATE_DIR")
        return cls(
            handle=_env("CODEFORCES_HANDLE", "CF_HANDLE"),
            password=_env("CODEFORCES_PASSWORD", "CF_PASSWORD"),
            cookie=_env(
                "CODEFORCES_COOKIE", "CODEFORCES_JSESSIONID", "CF_COOKIE"
            ),
            api_key=_env("CODEFORCES_API_KEY", "CF_API_KEY"),
            api_secret=_env("CODEFORCES_API_SECRET", "CF_API_SECRET"),
            state_dir=Path(state) if state else cls.state_dir,
            default_language=_env(
                "CF_MCP_DEFAULT_LANGUAGE", default="GNU G++23"
            ),
            timeout=float(_env("CF_MCP_TIMEOUT", default="30")),
        )

    @property
    def has_cookie(self) -> bool:
        return bool(self.cookie)

    @property
    def has_password(self) -> bool:
        return bool(self.handle and self.password)

    @property
    def has_credentials(self) -> bool:
        """Whether any form of authentication is available."""
        return self.has_cookie or self.has_password

    def cookies(self) -> dict[str, str]:
        return parse_cookie_string(self.cookie)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def cookie_file(self) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # Keyed by handle so switching accounts doesn't reuse a stale session.
        name = self.handle.lower() or "anonymous"
        return self.state_dir / f"cookies-{name}.json"
