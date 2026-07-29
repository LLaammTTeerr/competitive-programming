"""Authenticated HTTP session against the Codeforces website.

Codeforces has no API for reading statements or submitting code, so those go
through the regular web UI.  Three things make that non-trivial and are handled
here:

* the ``RCPC`` anti-bot challenge served as a 403 with an inline AES puzzle,
* the ``csrf_token`` that every state-changing form requires,
* the ``ftaa``/``bfaa``/``_tta`` browser-fingerprint fields the login and submit
  forms carry along.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import string
import time
from typing import Any

import httpx

from .aes import decrypt_cbc
from .config import BASE_URL, USER_AGENT, Config


class CodeforcesError(RuntimeError):
    """Any Codeforces-level failure worth showing to the user verbatim."""


_TO_NUMBERS = re.compile(r'toNumbers\("([0-9a-fA-F]+)"\)')
_CSRF_INPUT = re.compile(r"name=['\"]csrf_token['\"]\s+value=['\"]([0-9a-f]+)['\"]")
_CSRF_META = re.compile(r"name=['\"]X-Csrf-Token['\"]\s+content=['\"]([0-9a-f]+)['\"]")
_HANDLE_HEADER = re.compile(
    r'<a[^>]+href="/profile/([^"]+)"[^>]*>.*?</a>\s*\|\s*<a[^>]+href="/settings',
    re.DOTALL,
)
# Codeforces serves the logout link with a per-session token prefix
# (href="/<32-hex>/logout"); older pages used a bare href="/logout".
_LOGOUT_LINK = re.compile(r'href="(?:/[0-9a-f]{16,})?/logout(?:[?#][^"]*)?"')


def _random_ftaa() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(18))


def _random_bfaa() -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(32))


def compute_tta(ftaa: str) -> int:
    """Port of the ``_tta`` value the login page computes in JavaScript."""
    tta = 0
    for i, char in enumerate(ftaa):
        tta = (tta + (i + 1) * (i + 2) * ord(char)) % 1009
        if i % 3 == 0:
            tta += 1
        if i % 2 == 0:
            tta *= 2
        if i > 0:
            tta -= (ord(ftaa[i // 2]) // 2) * (tta % 5)
        tta = ((tta % 1009) + 1009) % 1009
    return tta


class CodeforcesSession:
    """A lazily-authenticated httpx session with cookie persistence."""

    def __init__(self, config: Config):
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._logged_in_handle: str | None = None
        self._last_failure: str | None = None
        self.ftaa = _random_ftaa()
        self.bfaa = _random_bfaa()

    # ---------------------------------------------------------------- client

    async def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                timeout=self.config.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,"
                        "image/avif,image/webp,*/*;q=0.8"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            self._load_cookies()
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            self._save_cookies()
            await self._client.aclose()
            self._client = None

    def _load_cookies(self) -> None:
        path = self.config.cookie_file()
        if not path.exists() or self._client is None:
            return
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return
        for name, value in data.get("cookies", {}).items():
            self._client.cookies.set(name, value, domain="codeforces.com")

    def _save_cookies(self) -> None:
        if self._client is None:
            return
        try:
            path = self.config.cookie_file()
            path.write_text(
                json.dumps(
                    {"saved": int(time.time()), "cookies": dict(self._client.cookies)}
                )
            )
            path.chmod(0o600)
        except OSError:
            pass  # A non-writable cache only costs us a re-login next time.

    # ------------------------------------------------------------- transport

    def _solve_rcpc(self, body: str) -> str | None:
        """Return the RCPC cookie value for an anti-bot challenge page."""
        # Challenge pages are tiny; bail early so a real page that happens to
        # mention toNumbers cannot trigger a bogus cookie and a re-request.
        if len(body) > 20000 or "toNumbers" not in body:
            return None
        parts = _TO_NUMBERS.findall(body)
        if len(parts) < 3:
            return None
        key, iv, ciphertext = (bytes.fromhex(p) for p in parts[:3])
        try:
            return decrypt_cbc(key, iv, ciphertext).hex()
        except ValueError:
            return None

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Issue a request, transparently answering the RCPC challenge."""
        client = await self.client()
        response = await client.request(method, url, **kwargs)

        rcpc = self._solve_rcpc(response.text)
        if rcpc is not None:
            client.cookies.set("RCPC", rcpc, domain="codeforces.com")
            # The challenge page reloads itself with a cache-busting param.
            await client.request("GET", url, params={"f0a28": 1})
            response = await client.request(method, url, **kwargs)

        if response.status_code == 403:
            raise CodeforcesError(
                f"Codeforces returned 403 for {url}. The anti-bot challenge could "
                "not be solved automatically; the page may also require login."
            )
        return response

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def get_text(self, url: str, **kwargs: Any) -> str:
        response = await self.get(url, **kwargs)
        if response.status_code == 404:
            raise CodeforcesError(f"Not found: {url}")
        response.raise_for_status()
        return response.text

    # ------------------------------------------------------------------ auth

    @staticmethod
    def extract_csrf(html: str) -> str | None:
        match = _CSRF_INPUT.search(html) or _CSRF_META.search(html)
        return match.group(1) if match else None

    @staticmethod
    def logged_in_handle(html: str) -> str | None:
        """Return the signed-in handle, ``""`` if signed in but unidentified.

        ``None`` means the page was served to a logged-out visitor.
        """
        if not _LOGOUT_LINK.search(html):
            return None
        match = _HANDLE_HEADER.search(html)
        if match:
            return match.group(1)
        # Fall back to the first profile link in the header block.
        start = html.find('class="lang-chooser"')
        if start != -1:
            block = html[start : start + 2000]
            fallback = re.search(r'href="/profile/([^"]+)"', block)
            if fallback:
                return fallback.group(1)
        return ""

    async def _verify_session(self) -> str | None:
        """Check whether the current cookies authenticate us."""
        # "/" is not behind the Cloudflare challenge that guards "/enter".
        html = await self.get_text("/")
        handle = self.logged_in_handle(html)
        if handle is None:
            # Distinguish "Codeforces says we're logged out" from "we never
            # reached Codeforces" — the two need very different fixes.
            self._last_failure = (
                "Codeforces served a sign-in page, so the cookie is expired "
                "or invalid."
                if 'href="/enter' in html
                else "The response was not a recognisable Codeforces page "
                "(a Cloudflare challenge, or the page markup changed and this "
                "server's parser is out of date)."
            )
        return handle

    async def ensure_login(self) -> str:
        """Authenticate if needed and return the signed-in handle."""
        if not self.config.has_credentials:
            raise CodeforcesError(
                "No Codeforces credentials configured. Set CODEFORCES_COOKIE to "
                "your browser's Codeforces JSESSIONID cookie (see the README) to "
                "enable submitting and reading your own submissions."
            )
        async with self._lock:
            if self._logged_in_handle:
                return self._logged_in_handle

            client = await self.client()

            # 1. An explicitly supplied browser cookie always wins.
            for name, value in self.config.cookies().items():
                client.cookies.set(name, value, domain="codeforces.com")

            # 2. Either that cookie or the cached jar may already be valid.
            handle = await self._verify_session()
            if handle is not None:
                self._logged_in_handle = handle or self.config.handle or "unknown"
                self._save_cookies()
                return self._logged_in_handle

            # 3. Last resort: the password form. Codeforces puts /enter behind a
            #    Cloudflare JS challenge, so this usually cannot succeed from a
            #    plain HTTP client — but it costs one request to find out.
            if self.config.has_password:
                handle = await self._password_login()
                if handle:
                    self._logged_in_handle = handle
                    self._save_cookies()
                    return handle

            raise CodeforcesError(
                "Not signed in to Codeforces. "
                + (
                    f"{self._last_failure} "
                    if self.config.has_cookie and self._last_failure
                    else ""
                )
                + "Codeforces protects its login page with a Cloudflare browser "
                "challenge, so scripted password login does not work. Sign in at "
                "https://codeforces.com in a browser, copy the JSESSIONID cookie "
                "value, and set CODEFORCES_COOKIE=JSESSIONID=<value> for this "
                "server. See the README for step-by-step instructions."
            )

    async def _password_login(self) -> str | None:
        """Best-effort form login; returns None if Codeforces blocks it."""
        try:
            html = await self.get_text("/enter")
        except CodeforcesError:
            return None  # Cloudflare challenge; caller reports the cookie route.

        csrf = self.extract_csrf(html)
        if not csrf:
            return None

        try:
            response = await self.post(
                "/enter",
                data={
                    "csrf_token": csrf,
                    "action": "enter",
                    "ftaa": self.ftaa,
                    "bfaa": self.bfaa,
                    "handleOrEmail": self.config.handle,
                    "password": self.config.password,
                    "_tta": compute_tta(self.ftaa),
                    "remember": "on",
                },
                headers={"Referer": f"{BASE_URL}/enter"},
            )
        except CodeforcesError:
            return None

        if "Invalid handle or password" in response.text:
            raise CodeforcesError(
                "Codeforces rejected the credentials: invalid handle or password."
            )
        handle = self.logged_in_handle(response.text)
        if handle is None:
            return None
        return handle or self.config.handle

    async def csrf_for(self, url: str) -> tuple[str, str]:
        """Fetch a page and return ``(html, csrf_token)``."""
        html = await self.get_text(url)
        csrf = self.extract_csrf(html)
        if not csrf:
            raise CodeforcesError(f"No csrf_token found on {url}")
        return html, csrf
