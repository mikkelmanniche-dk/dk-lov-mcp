"""dk-lov-mcp: Retsinformation (dansk lov) som MCP-værktøjer.

Bygget på matematicsolutions/dk-eli-mcp (Apache-2.0), men uden runtime-manifest og
revisionslog, og med søgning, lovnavne, paragrafopslag og senere ændringer.

Kør: ``uv run --directory <sti> dk-lov-mcp`` (stdio).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import lexdania
from .klient import BASE_URL, Klient

INSTRUCTIONS = """\
Opslag i Retsinformation (retsinformation.dk), den officielle kilde til dansk lov.

Rækkefølge:
1. Kender du loven ved navn (offentlighedsloven, miljøoplysningsloven, forvaltningsloven eller
   en forkortelse som OFL/MOL/FVL), så brug `lov` direkte. `lov_register` viser de faste navne.
   En dansk henvisning ("LBK nr. 145 af 24/02/2020", "lov nr. 655 af 11. juni 2024") eller et
   ELI-link virker også i `lov`.
2. Ellers: `lov_soeg` med fritekst, og brug `aar` + `nr` fra et træf.
3. `lov_paragraf` for én paragraf (og evt. ét stykke). Brug den frem for `lov_tekst`, som er stor.
4. `lov_hent` for status og senere ændringer.

Regler:
- Citér altid `citat` og `eli` fra svaret. Find aldrig selv på et nummer, en dato eller et link.
- `gaeldende: false` betyder, at dokumentet er historisk. Sig det tydeligt.
- `senere_aendringer` er ændringslove, som endnu ikke er indarbejdet i den samlede tekst. Er
  listen ikke tom, kan paragrafteksten være forældet. Nævn det, og slå ændringsloven op
  (`lov_tekst` med dens `accessionsnummer`), før du siger, hvad der gælder i dag.
- Teksten er ordret fra Retsinformation. Omskriv den ikke, som om det var lovteksten.
- Domstolspraksis, Ombudsmandens udtalelser og forarbejder findes ikke her.
"""

LAES = ToolAnnotations(readOnlyHint=True, idempotentHint=True, destructiveHint=False, openWorldHint=True)

mcp: FastMCP = FastMCP(name="dk-lov-mcp", instructions=INSTRUCTIONS)


# ── Lovregister ──────────────────────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _register() -> tuple[dict[str, Any], ...]:
    data = json.loads(resources.files("dk_lov_mcp").joinpath("love.json").read_text("utf-8"))
    return tuple(data["love"])


def _slaa_op_navn(navn: str) -> tuple[int, int] | None:
    n = navn.strip().lower()
    for lov in _register():
        if n == lov["noegle"].lower() or n in (a.lower() for a in lov["aliaser"]):
            return int(lov["aar"]), int(lov["nr"])
    return None


_ACCN = re.compile(r"[A-Za-z][0-9]{6,}")
_ELI_ACCN = re.compile(r"eli/accn/([A-Za-z][0-9]{6,})")


def _koordinater(
    lov: str | None, aar: int | None, nr: int | None, accessionsnummer: str | None
) -> tuple[int, int] | str:
    """(år, nr) eller et accessionsnummer. Fejler med en forklaring, hvis intet passer."""
    if accessionsnummer:
        a = accessionsnummer.strip()
        if not _ACCN.fullmatch(a):
            raise ToolError(f"accessionsnummer={a!r} ligner ikke et accessionsnummer (fx 'A20200014529').")
        return a
    if lov:
        fundet = _slaa_op_navn(lov) or lexdania.laes_henvisning(lov)
        if fundet:
            return fundet
        if _ACCN.fullmatch(lov.strip()):
            return lov.strip()
        if m := _ELI_ACCN.search(lov):
            return m.group(1)
        raise ToolError(
            f"Kender ikke loven {lov!r}. Brug lov_soeg for at finde år og nummer, "
            "eller skriv en henvisning som 'LBK nr. 145 af 24/02/2020'."
        )
    if aar is not None and nr is not None:
        if not 1600 <= aar <= 2100 or not 0 < nr < 100_000:
            raise ToolError(f"aar={aar}, nr={nr} er uden for gyldigt område.")
        return aar, nr
    raise ToolError("Angiv `lov`, eller `aar` og `nr`, eller `accessionsnummer`.")


async def _hent_rod(koord: tuple[int, int] | str) -> Any:
    try:
        async with Klient() as k:
            xml = await (k.xml_accn(koord) if isinstance(koord, str) else k.xml(*koord))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise ToolError("Retsinformation har intet dokument med de koordinater.") from exc
        raise ToolError(f"Retsinformation svarede {exc.response.status_code}. Prøv igen.") from exc
    except httpx.TransportError as exc:
        raise ToolError(f"Kunne ikke nå Retsinformation: {type(exc).__name__}. Prøv igen.") from exc
    except ValueError as exc:  # inkl. LexDaniaFejl fra valideringen før cachen
        raise ToolError(str(exc)) from exc
    try:
        return lexdania.rod(xml)
    except lexdania.LexDaniaFejl as exc:
        raise ToolError(str(exc)) from exc


def _advarsel(meta: dict[str, Any]) -> str | None:
    dele = []
    if not meta["gaeldende"]:
        dele.append(f"Dokumentet er ikke gældende (status: {meta['status']}).")
    if meta["senere_aendringer"]:
        dele.append(
            f"{len(meta['senere_aendringer'])} senere ændringslov(e) er ikke indarbejdet i teksten; "
            "tjek dem, før du siger, hvad der gælder i dag."
        )
    return " ".join(dele) or None


# ── Værktøjer ────────────────────────────────────────────────────────────────────────────


@mcp.tool(annotations=LAES)
def lov_register() -> list[dict[str, Any]]:
    """Ofte brugte love med faste navne, forkortelser og ELI."""
    return [
        {**lov, "eli": f"{BASE_URL}/eli/lta/{lov['aar']}/{lov['nr']}"} for lov in _register()
    ]


@mcp.tool(annotations=LAES)
async def lov_soeg(tekst: str, kun_gaeldende: bool = True, maks: int = 10) -> dict[str, Any]:
    """Fritekstsøgning i Retsinformation (samme søgning som på retsinformation.dk).

    Args:
        tekst: fx "offentlighedsloven" eller "aktindsigt i miljøoplysninger".
        kun_gaeldende: udelad historiske dokumenter.
        maks: højst så mange træf (1–50).
    """
    tekst = tekst.strip()
    if not tekst:
        raise ToolError("Søgeteksten er tom.")
    maks = max(1, min(maks, 50))
    try:
        async with Klient() as k:
            data = await k.soeg(tekst)
    except (httpx.HTTPError, ValueError) as exc:
        raise ToolError(f"Søgningen fejlede: {type(exc).__name__}. Prøv igen.") from exc

    traef = []
    for d in data["documents"]:
        if kun_gaeldende and d.get("isHistoryFlag"):
            continue
        link = d.get("retsinfoLink") or ""
        m = re.fullmatch(r"/eli/lta/(\d{4})/(\d+)", link)
        traef.append({
            "betegnelse": d.get("shortName"),
            "titel": d.get("title"),
            "populaertitel": d.get("popularTitle") or None,
            "type": d.get("documentType"),
            "ministerium": d.get("ressortName"),
            "gaeldende": not d.get("isHistoryFlag"),
            "aar": int(m.group(1)) if m else None,
            "nr": int(m.group(2)) if m else None,
            "eli": f"{BASE_URL}{link}" if link else None,
        })
        if len(traef) >= maks:
            break
    return {
        "tekst": tekst,
        "antal_i_alt": data.get("resultCount"),
        "traef": traef,
        "note": "Kun første side af Retsinformations søgning. Træf uden aar/nr ligger uden for "
                "Lovtidende A; brug deres eli-link.",
    }


@mcp.tool(annotations=LAES)
async def lov_hent(
    lov: str | None = None, aar: int | None = None, nr: int | None = None,
    accessionsnummer: str | None = None,
) -> dict[str, Any]:
    """Metadata for et dokument: titel, status, ELI, citat og senere ændringer.

    Args:
        lov: navn ("offentlighedsloven", "OFL"), dansk henvisning eller ELI-link.
        aar: år, sammen med ``nr``.
        nr: nummer, sammen med ``aar``.
        accessionsnummer: fx "A20200014529".
    """
    rod = await _hent_rod(_koordinater(lov, aar, nr, accessionsnummer))
    meta = lexdania.metadata(rod)
    return {**meta, "antal_paragraffer": len(lexdania.paragraf_liste(rod)), "advarsel": _advarsel(meta)}


@mcp.tool(annotations=LAES)
async def lov_paragraf(
    paragraf: str, stk: int | None = None, lov: str | None = None, aar: int | None = None,
    nr: int | None = None, accessionsnummer: str | None = None,
) -> dict[str, Any]:
    """Ordret tekst for én paragraf, eller ét stykke af den.

    Args:
        paragraf: fx "36" eller "9 a".
        stk: fx 2 for § 36, stk. 2. Udelad for hele paragraffen.
        lov: navn, henvisning eller ELI-link (se ``lov_hent``).
        aar: år, sammen med ``nr``.
        nr: nummer, sammen med ``aar``.
        accessionsnummer: alternativ til de andre.
    """
    rod = await _hent_rod(_koordinater(lov, aar, nr, accessionsnummer))
    meta = lexdania.metadata(rod)
    tekst = lexdania.paragraf_tekst(rod, paragraf, stk)
    if tekst is None:
        hvad = f"§ {paragraf}" + (f", stk. {stk}" if stk else "")
        raise ToolError(
            f"{hvad} findes ikke i {meta['citat']}. Paragraffer: "
            + ", ".join(lexdania.paragraf_liste(rod))
        )
    henvisning = f"§ {paragraf.strip().lstrip('§').strip()}" + (f", stk. {stk}" if stk else "")
    return {
        "henvisning": f"{meta['populaertitel'] or meta['titel']} {henvisning}",
        "tekst": tekst,
        "citat": meta["citat"],
        "eli": meta["eli"],
        "gaeldende": meta["gaeldende"],
        "senere_aendringer": meta["senere_aendringer"],
        "advarsel": _advarsel(meta),
    }


@mcp.tool(annotations=LAES)
async def lov_tekst(
    lov: str | None = None, aar: int | None = None, nr: int | None = None,
    accessionsnummer: str | None = None,
) -> dict[str, Any]:
    """Hele dokumentets tekst som ren tekst (uden XML). Kan være stor; brug helst lov_paragraf.

    Args:
        lov: navn, henvisning eller ELI-link (se ``lov_hent``).
        aar: år, sammen med ``nr``.
        nr: nummer, sammen med ``aar``.
        accessionsnummer: alternativ til de andre.
    """
    rod = await _hent_rod(_koordinater(lov, aar, nr, accessionsnummer))
    meta = lexdania.metadata(rod)
    return {
        "citat": meta["citat"],
        "eli": meta["eli"],
        "gaeldende": meta["gaeldende"],
        "senere_aendringer": meta["senere_aendringer"],
        "advarsel": _advarsel(meta),
        "tekst": lexdania.fuld_tekst(rod),
    }


@mcp.tool(annotations=LAES)
async def lov_aendringer(dato: str) -> dict[str, Any]:
    """Dokumenter, Retsinformation har ændret på en dato. Virker kun 03:00–23:45 dansk tid.

    Args:
        dato: "ÅÅÅÅ-MM-DD".
    """
    dato = dato.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dato):
        raise ToolError(f"dato={dato!r} skal være ÅÅÅÅ-MM-DD.")
    try:
        async with Klient() as k:
            raw = await k.aendringer(dato)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            raise ToolError("Ændrings-API'et svarer kun 03:00–23:45 dansk tid, eller datoen er ugyldig.") from exc
        raise ToolError(f"Retsinformation svarede {exc.response.status_code}.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ToolError(f"Kunne ikke hente ændringer: {type(exc).__name__}.") from exc

    poster = []
    for e in raw:
        accn = e.get("accessionsnummer") or None
        dt = e.get("documentType")
        poster.append({
            "accessionsnummer": accn,
            "type": dt.get("shortName") if isinstance(dt, dict) else None,
            "aendret": e.get("changeDate"),
            "aarsag": e.get("reasonForChange"),
            "eli": f"{BASE_URL}/eli/accn/{accn}" if accn else None,
        })
    return {"dato": dato, "antal": len(poster), "dokumenter": poster,
            "note": "En tom liste betyder, at intet blev ændret den dag. Titler kræver lov_hent."}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
