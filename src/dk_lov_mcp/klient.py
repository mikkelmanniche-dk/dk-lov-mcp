"""Async-klient til Retsinformation med cache og genforsøg.

Bygget videre på client.py fra matematicsolutions/dk-eli-mcp (Apache-2.0). Adresserne er
faste i koden: intet hentes udefra, der kan pege klienten et andet sted hen.

- ``www.retsinformation.dk/eli/...``: dokumenter som LexDania-XML.
- ``www.retsinformation.dk/api/documentsearch``: fritekstsøgning (JSON). Det er det API,
  Retsinformations egen søgeside bruger; det er ikke dokumenteret som Open Data.
- ``api.retsinformation.dk/v1/Documents``: ændringer på en dato (03:00–23:45 dansk tid).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anyio
import httpx

from .cache import HttpCache
from .lexdania import rod

BASE_URL = "https://www.retsinformation.dk"
API_URL = "https://api.retsinformation.dk"
USER_AGENT = "dk-lov-mcp/1.0 (+https://github.com/mikkelmanniche-dk/dk-lov-mcp)"  # headere skal være ASCII
TIMEOUT = httpx.Timeout(60.0, connect=10.0)

_GENFORSOEG_STATUS = frozenset({429, 500, 502, 503, 504})
_MAKS_FORSOEG = 3
_MAKS_BYTES = 20 * 1024 * 1024  # OFL er ca. 200 KB; alt over 20 MB er en fejl.


class Klient:
    """Brug som ``async with Klient() as k: ...``."""

    def __init__(self, cache: HttpCache | None = None) -> None:
        self._cache = cache or HttpCache()
        self._http = httpx.AsyncClient(
            timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=False
        )

    async def __aenter__(self) -> Klient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        try:
            await self._http.aclose()
        finally:
            self._cache.close()

    async def _get(
        self, url: str, *, accept: str, kategori: str, params: dict[str, str] | None = None,
        valider: Callable[[str], object] | None = None,
    ) -> str:
        """Hent med cache. ``valider`` kaster på et ugyldigt svar, så det aldrig bliver cachet."""
        noegle = url + ("?" + "&".join(f"{k}={v}" for k, v in sorted(params.items())) if params else "")
        cached = self._cache.get(noegle)
        if isinstance(cached, str):
            return cached
        sidste: Exception | None = None
        for forsoeg in range(_MAKS_FORSOEG):
            try:
                resp = await self._http.get(url, params=params, headers={"Accept": accept})
                resp.raise_for_status()
                if len(resp.content) > _MAKS_BYTES:
                    raise ValueError(f"Svaret fra {url} er over {_MAKS_BYTES} bytes.")
                if valider:
                    valider(resp.text)
                self._cache.set(noegle, resp.text, ttl=HttpCache.ttl_for(kategori))
                return resp.text
            except httpx.HTTPStatusError as exc:
                sidste = exc
                if exc.response.status_code not in _GENFORSOEG_STATUS or forsoeg == _MAKS_FORSOEG - 1:
                    raise
            except httpx.TransportError as exc:
                sidste = exc
                if forsoeg == _MAKS_FORSOEG - 1:
                    raise
            await anyio.sleep(0.5 * (2**forsoeg))
        assert sidste is not None
        raise sidste

    async def xml(self, aar: int, nr: int) -> str:
        return await self._get(f"{BASE_URL}/eli/lta/{aar}/{nr}/xml", accept="application/xml", kategori="act", valider=rod)

    async def xml_accn(self, accn: str) -> str:
        return await self._get(f"{BASE_URL}/eli/accn/{accn}/xml", accept="application/xml", kategori="act", valider=rod)

    async def soeg(self, tekst: str) -> dict[str, Any]:
        raw = await self._get(
            f"{BASE_URL}/api/documentsearch", accept="application/json", kategori="search",
            params={"t": tekst}, valider=_soegesvar,
        )
        return _soegesvar(raw)

    async def aendringer(self, dato: str) -> list[dict[str, Any]]:
        raw = await self._get(
            f"{API_URL}/v1/Documents", accept="application/json", kategori="changes",
            params={"date": dato}, valider=_aendringssvar,
        )
        return _aendringssvar(raw)


def _soegesvar(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("documents", []), list):
        raise ValueError("Uventet svar fra søgningen.")
    data["documents"] = [d for d in data.get("documents", []) if isinstance(d, dict)]
    return data


def _aendringssvar(raw: str) -> list[dict[str, Any]]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Uventet svar fra ændrings-API'et.")
    return [d for d in data if isinstance(d, dict)]
