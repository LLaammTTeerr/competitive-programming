"""Client for the official read-only Codeforces API (``/api/...``)."""

from __future__ import annotations

import hashlib
import random
import time
from typing import Any

import httpx

from .config import BASE_URL, USER_AGENT, Config
from .session import CodeforcesError


class CodeforcesApi:
    def __init__(self, config: Config):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                timeout=self.config.timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _sign(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Add apiKey/time/apiSig as described in the Codeforces API docs."""
        params = dict(params)
        params["apiKey"] = self.config.api_key
        params["time"] = int(time.time())
        rand = f"{random.randint(0, 999999):06d}"
        ordered = sorted((str(k), str(v)) for k, v in params.items())
        query = "&".join(f"{k}={v}" for k, v in ordered)
        digest = hashlib.sha512(
            f"{rand}/{method}?{query}#{self.config.api_secret}".encode()
        ).hexdigest()
        params["apiSig"] = rand + digest
        return params

    async def call(
        self, method: str, params: dict[str, Any] | None = None, *, signed: bool = False
    ) -> Any:
        """Invoke an API method and return its ``result`` field.

        ``signed`` requires an API key/secret and is needed for anything that
        touches non-public data (e.g. a running contest's submissions).
        """
        params = {k: v for k, v in (params or {}).items() if v is not None}
        if signed:
            if not self.config.has_api_key:
                raise CodeforcesError(
                    f"{method} needs an API key. Set CODEFORCES_API_KEY and "
                    "CODEFORCES_API_SECRET (create them at "
                    "https://codeforces.com/settings/api)."
                )
            params = self._sign(method, params)

        client = await self.client()
        response = await client.get(f"/api/{method}", params=params)
        try:
            payload = response.json()
        except ValueError:
            raise CodeforcesError(
                f"Codeforces API returned non-JSON for {method} "
                f"(HTTP {response.status_code}). The service may be under "
                "maintenance."
            ) from None

        if payload.get("status") != "OK":
            raise CodeforcesError(
                f"Codeforces API error on {method}: {payload.get('comment', payload)}"
            )
        return payload["result"]

    async def contest_problems(self, contest_id: int) -> dict[str, Any]:
        """Contest metadata plus its problem list.

        Codeforces only serves non-gym standings to anonymous requests that
        carry no extra parameters, so this deliberately sends a bare query.
        """
        result = await self.call("contest.standings", {"contestId": contest_id})
        return {
            "contest": result.get("contest", {}),
            "problems": result.get("problems", []),
        }

    async def user_status(
        self, handle: str, *, start: int = 1, count: int = 10
    ) -> list[dict[str, Any]]:
        return await self.call(
            "user.status", {"handle": handle, "from": start, "count": count}
        )

    async def contest_status(
        self, contest_id: int, handle: str, *, start: int = 1, count: int = 10
    ) -> list[dict[str, Any]]:
        return await self.call(
            "contest.status",
            {
                "contestId": contest_id,
                "handle": handle,
                "from": start,
                "count": count,
            },
        )
