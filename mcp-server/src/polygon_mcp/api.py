"""Client for the Polygon API (``https://polygon.codeforces.com/api/<method>``).

Written from the Polygon API documentation rather than adapted from any
existing client. Two things in here are worth knowing before changing them:

* **Everything is signed, including file contents.** Polygon takes uploads as
  ordinary form fields, not multipart parts, so a solution's whole source text
  is one more ``param=value`` pair inside the string that gets hashed.
* **A retry is a new request, not a replay.** The signature commits to `time`,
  and Polygon refuses anything more than five minutes off its clock, so the
  second attempt is signed again from scratch.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import time
from typing import Any, Awaitable, Callable, Mapping

import httpx

from .config import Config, PolygonError

# Methods that change something. The documentation only says "send a
# HTTP-request", without fixing a verb; reads go as GET and writes as POST,
# which is what Polygon's own clients do and what keeps a statement's legend —
# far too long for a query string — in a request body.
WRITE_METHODS = frozenset(
    {
        "problem.create",
        "problem.updateInfo",
        "problem.updateWorkingCopy",
        "problem.discardWorkingCopy",
        "problem.commitChanges",
        "problem.saveStatement",
        "problem.saveStatementResource",
        "problem.saveValidatorTest",
        "problem.saveCheckerTest",
        "problem.setValidator",
        "problem.setChecker",
        "problem.setInteractor",
        "problem.saveFile",
        "problem.saveSolution",
        "problem.editSolutionExtraTags",
        "problem.saveScript",
        "problem.saveTest",
        "problem.setTestGroup",
        "problem.enableGroups",
        "problem.enablePoints",
        "problem.saveTestGroup",
        "problem.saveTags",
        "problem.saveGeneralDescription",
        "problem.saveGeneralTutorial",
        "problem.buildPackage",
    }
)

# Methods that answer with the file itself rather than a JSON envelope. A
# *failure* on one of these still comes back as JSON, so the parse is tried
# first and the text is the fallback.
PLAIN_TEXT_METHODS = frozenset(
    {
        "problem.viewFile",
        "problem.viewSolution",
        "problem.script",
        "problem.testInput",
        "problem.testAnswer",
    }
)

RETRY_STATUS = frozenset({500, 502, 503, 504})


def wire_value(value: Any) -> str:
    """Render one parameter the way it goes on the wire.

    The signature is computed over these strings, so booleans have to be
    lowercased here and not by whatever the HTTP layer would have done —
    otherwise the hash covers `True` and the request carries `true`.

    A whole-numbered float is rendered as an integer. Tool arguments are
    coerced to their annotated type before they arrive, so `test_points=10`
    reaches this as `10.0`, and `testPoints=10.0` is not obviously what Polygon
    wants when it means ten points.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def sign(
    method: str,
    params: Mapping[str, Any],
    *,
    api_key: str,
    secret: str,
    rand: str,
    now: int,
) -> dict[str, str]:
    """Return `params` plus `apiKey`, `time` and `apiSig`.

    `apiSig` is `rand` followed by the SHA-512 of

        <rand>/<methodName>?param1=value1&...&paramN=valueN#<secret>

    over every parameter *including* `apiKey` and `time` and excluding
    `apiSig`, sorted first by name and then by value. The parameters are
    hashed raw: Polygon percent-decodes before it verifies, so signing the
    encoded form would fail for any value containing `&`, `=` or a newline —
    which is to say for every statement and every source file.
    """
    signed = {k: wire_value(v) for k, v in params.items()}
    signed["apiKey"] = api_key
    signed["time"] = str(now)
    query = "&".join(f"{k}={v}" for k, v in sorted(signed.items()))
    digest = hashlib.sha512(f"{rand}/{method}?{query}#{secret}".encode()).hexdigest()
    signed["apiSig"] = rand + digest
    return signed


class PolygonApi:
    """Signed, paced access to one Polygon account.

    `transport` and `sleep` exist so the whole class can be exercised without a
    network or a wall clock; nothing else in the package injects them.
    """

    def __init__(
        self,
        config: Config,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ):
        self.config = config
        self._transport = transport
        self._sleep = sleep or asyncio.sleep
        self._client: httpx.AsyncClient | None = None
        self._last_request: float = 0.0

    async def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                follow_redirects=True,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _pace(self) -> None:
        gap = self.config.min_interval - (time.monotonic() - self._last_request)
        if gap > 0:
            await self._sleep(gap)
        self._last_request = time.monotonic()

    def _signed(self, method: str, params: Mapping[str, Any]) -> dict[str, str]:
        return sign(
            method,
            params,
            api_key=self.config.api_key,
            secret=self.config.api_secret,
            rand=f"{random.randint(0, 999999):06d}",
            now=int(time.time()),
        )

    async def call(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Invoke one API method and return its `result`.

        `None` parameters are dropped rather than sent: for the several methods
        whose edit mode means "leave every omitted field alone", sending an
        empty value would clear the field instead.
        """
        if not self.config.has_credentials:
            raise PolygonError(
                f"{method} needs Polygon credentials. Set POLYGON_API_KEY and "
                "POLYGON_API_SECRET for this server (Polygon → Settings → "
                "API keys).",
                method,
            )
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        client = await self.client()
        write = method in WRITE_METHODS

        for attempt in (0, 1):
            await self._pace()
            # Re-signed per attempt: the first signature's `time` may already
            # be stale by the time the backoff has elapsed.
            data = self._signed(method, clean)
            try:
                if write:
                    response = await client.post(method, data=data)
                else:
                    response = await client.get(method, params=data)
            except httpx.TimeoutException:
                # Never `str(error)` an httpx exception: its text carries the
                # request URL, and for a GET that URL carries `apiKey`.
                if attempt == 0:
                    await self._sleep(1.0)
                    continue
                raise PolygonError(
                    f"Polygon did not answer {method} within "
                    f"{self.config.timeout:g}s.",
                    method,
                ) from None
            except httpx.HTTPError:
                if attempt == 0:
                    await self._sleep(1.0)
                    continue
                raise PolygonError(
                    f"Could not reach Polygon for {method}. Check the network "
                    "and POLYGON_BASE_URL.",
                    method,
                ) from None

            if response.status_code in RETRY_STATUS and attempt == 0:
                await self._sleep(1.0)
                continue
            return self._unwrap(method, response)

        raise PolygonError(f"Polygon call {method} exhausted its retry.", method)

    def _unwrap(self, method: str, response: httpx.Response) -> Any:
        """Turn one HTTP response into a `result`, or raise `PolygonError`."""
        try:
            payload = response.json()
        except ValueError:
            payload = None

        enveloped = isinstance(payload, dict) and "status" in payload
        if enveloped and payload["status"] == "FAILED":
            raise PolygonError(str(payload.get("comment") or "unknown error"), method)

        if response.status_code >= 400:
            raise PolygonError(
                f"Polygon answered HTTP {response.status_code} for {method}.",
                method,
            )

        if method in PLAIN_TEXT_METHODS and not enveloped:
            # A one-line test input parses as JSON perfectly well, so these
            # methods are decided by the absence of an envelope, not by
            # whether the body happened to be valid JSON.
            return response.text

        if payload is None:
            raise PolygonError(
                f"Polygon returned a non-JSON body for {method} "
                f"(HTTP {response.status_code}).",
                method,
            )
        if enveloped and payload["status"] == "OK":
            return payload.get("result")
        raise PolygonError(
            f"Polygon returned an unrecognised envelope for {method}.", method
        )
