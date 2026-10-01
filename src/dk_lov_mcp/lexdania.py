"""Læsning af Retsinformations LexDania 2.1-XML: metadata, ændringer, paragraffer og ren tekst.

Bygget videre på citations.py fra matematicsolutions/dk-eli-mcp (Apache-2.0).

XML'en har intet namespace. Roden er ``<Dokument>`` med en ``<Meta>``-blok. Paragraffer er
``<Paragraf localId="36">`` med ``<Stk>``-børn; nummererede punkter ligger som
``<Indentatio>`` med ``<Explicatus>1)</Explicatus>``.

``ET.fromstring`` får UTF-8-bytes, fordi XML'en erklærer ``encoding="utf-8"``, og det afviser
ElementTree på en str.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from defusedxml import ElementTree as SikkerET
from defusedxml.common import DefusedXmlException
from typing import Any

BASE_URL = "https://www.retsinformation.dk"

# Dokumenttyper i Retsinformation. Rækkefølgen betyder noget: "LOV" må ikke fange "LBK".
DOC_TYPES = ("LBK", "LOV", "BEK", "CIR", "VEJ", "SKR")


class LexDaniaFejl(ValueError):
    """XML'en kunne ikke læses."""


def rod(xml_text: str) -> ET.Element:
    try:
        return SikkerET.fromstring(xml_text.encode("utf-8"))
    except (ET.ParseError, DefusedXmlException) as exc:
        raise LexDaniaFejl(f"Ugyldig XML fra Retsinformation: {exc}") from exc


def _normaliser_type(raw: str | None) -> str | None:
    """'LBK H#LOKDOK03' -> 'LBK'."""
    if not raw:
        return None
    head = raw.strip().upper().split()[0]
    for code in DOC_TYPES:
        if head.startswith(code):
            return code
    return head or None


def _dk_dato(iso: str | None) -> str | None:
    """'2020-02-24' -> '24/02/2020'."""
    if iso and re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso):
        y, m, d = iso.split("-")
        return f"{d}/{m}/{y}"
    return iso


def _tekst(meta: ET.Element, tag: str) -> str | None:
    el = meta.find(tag)
    if el is not None and el.text and el.text.strip():
        return el.text.strip()
    return None


def metadata(root: ET.Element) -> dict[str, Any]:
    """Metadata, ELI og senere ændringer, der ikke er indarbejdet i dokumentet."""
    meta = root.find("Meta")
    if meta is None:
        raise LexDaniaFejl("Dokumentet har ingen <Meta>-blok.")

    year = _tekst(meta, "Year")
    number = _tekst(meta, "Number")
    aar = int(year) if year and year.isdigit() else None
    nr = int(number) if number and number.isdigit() else None
    accn = _tekst(meta, "AccessionNumber")
    doc_type = _normaliser_type(_tekst(meta, "DocumentType"))
    dato = _tekst(meta, "DiesSigni")

    if aar is not None and nr is not None:
        eli = f"{BASE_URL}/eli/lta/{aar}/{nr}"
    elif accn:
        eli = f"{BASE_URL}/eli/accn/{accn}"
    else:
        eli = None

    betegnelse = " ".join(
        p for p in (doc_type, f"nr. {nr}" if nr is not None else None,
                    f"af {_dk_dato(dato)}" if dato else None) if p
    ) or None
    navn = _tekst(meta, "PopularTitle") or _tekst(meta, "DocumentTitle")

    return {
        "aar": aar,
        "nr": nr,
        "accessionsnummer": accn,
        "dokumenttype": doc_type,
        "titel": _tekst(meta, "DocumentTitle"),
        "populaertitel": _tekst(meta, "PopularTitle"),
        "status": _tekst(meta, "Status"),
        "gaeldende": _tekst(meta, "Status") == "Valid",
        "underskrevet": dato,
        "ministerium": _tekst(meta, "Ministry"),
        "betegnelse": betegnelse,
        "citat": f"{navn} ({betegnelse})" if navn and betegnelse else (navn or betegnelse),
        "eli": eli,
        "senere_aendringer": senere_aendringer(meta),
    }


def senere_aendringer(meta: ET.Element) -> list[dict[str, str | None]]:
    """Ændringslove, som Retsinformation knytter til dokumentet, men som ikke er indarbejdet.

    I <Meta> står de som ``<Change id="change_1"/>`` fulgt af ``<Ref_Accn REFid="change_1">``,
    ``<Ref_Af>`` og ``<Ref_Text>`` med samme REFid.
    """
    ud: dict[str, dict[str, str | None]] = {}
    for change in meta.findall("Change"):
        cid = change.get("id")
        if cid:
            ud[cid] = {"accessionsnummer": None, "dato": None, "titel": None, "eli": None}
    felter = {"Ref_Accn": "accessionsnummer", "Ref_Af": "dato", "Ref_Text": "titel"}
    for el in meta:
        felt = felter.get(el.tag)
        ref = el.get("REFid")
        if felt and ref in ud and el.text:
            ud[ref][felt] = el.text.strip()
    for post in ud.values():
        if post["accessionsnummer"]:
            post["eli"] = f"{BASE_URL}/eli/accn/{post['accessionsnummer']}"
    return list(ud.values())


# ── Tekst ────────────────────────────────────────────────────────────────────────────────


def _linjer(el: ET.Element) -> str:
    dele = ("".join(c.itertext()).strip() for c in el.iter("Char"))
    tekst = " ".join(d for d in dele if d)
    return re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"\s+", " ", tekst))


def _render(el: ET.Element, indryk: int, ud: list[str]) -> None:
    """Skriv et element som læsbar tekst: hver <Linea> på sin egen linje, punkter indrykket."""
    for barn in el:
        if barn.tag == "Linea":
            tekst = _linjer(barn)
            if tekst:
                ud.append("  " * indryk + tekst)
        elif barn.tag == "Indentatio":
            label = barn.find("Explicatus")
            start = len(ud)
            _render(barn, indryk + 1, ud)
            if label is not None and label.text and len(ud) > start:
                ud[start] = "  " * (indryk + 1) + f"{label.text.strip()} {ud[start].strip()}"
        elif barn.tag in ("Explicatus", "Rubrica"):
            continue
        else:
            _render(barn, indryk, ud)


def _norm_nr(s: str) -> str:
    """'§ 9 a.' / '9 a' / '9a' -> '9a'."""
    return re.sub(r"[\s§.]", "", s).lower()


def find_paragraf(root: ET.Element, paragraf: str) -> ET.Element | None:
    maal = _norm_nr(paragraf)
    for p in root.iter("Paragraf"):
        lid = p.get("localId")
        if lid is not None and _norm_nr(lid) == maal:
            return p
        label = p.find("Explicatus")
        if label is not None and label.text and _norm_nr(label.text) == maal:
            return p
    return None


def paragraf_tekst(root: ET.Element, paragraf: str, stk: int | None = None) -> str | None:
    """Teksten til én paragraf, eller ét stykke af den. None, hvis den ikke findes."""
    p = find_paragraf(root, paragraf)
    if p is None:
        return None
    return _render_paragraf(p, stk)


def _render_paragraf(p: ET.Element, stk: int | None = None) -> str | None:
    stykker = list(enumerate(p.findall("Stk"), start=1))
    if stk is not None:
        if not 1 <= stk <= len(stykker):
            return None
        stykker = [stykker[stk - 1]]
    paragrafnavn = (p.findtext("Explicatus") or f"§ {p.get('localId', '?')}.").strip()  # "§ 36."
    ud: list[str] = []
    for i, s in stykker:
        if stk is not None:
            hoved = f"{paragrafnavn.rstrip('.')}, stk. {i}."
        else:
            hoved = paragrafnavn if i == 1 else f"Stk. {i}."
        linjer: list[str] = []
        _render(s, 0, linjer)
        ud.append(f"{hoved} " + "\n".join(linjer).lstrip())
    return "\n\n".join(ud)


def paragraf_liste(root: ET.Element) -> list[str]:
    """Alle paragrafnumre i dokumentet, fx ['1', '2', ..., '9 a']."""
    ud: list[str] = []
    for p in root.iter("Paragraf"):
        label = (p.findtext("Explicatus") or "").strip().lstrip("§").strip().rstrip(".")
        ud.append(label or p.get("localId") or "?")
    return ud


def fuld_tekst(root: ET.Element) -> str:
    """Hele dokumentets tekst uden XML, med kapitel- og paragrafoverskrifter."""
    indhold = root.find("DokumentIndhold")
    if indhold is None:
        return ""
    ud: list[str] = []

    def gaa(el: ET.Element) -> None:
        for barn in el:
            if barn.tag == "Paragraf":
                ud.append("")
                ud.append(_render_paragraf(barn) or "")
            elif barn.tag in ("Kapitel", "Afsnit"):
                label = (barn.findtext("Explicatus") or "").strip()
                rubrik = barn.find("Rubrica")
                overskrift = " ".join(x for x in (label, _linjer(rubrik) if rubrik is not None else "") if x)
                if overskrift:
                    ud.append("")
                    ud.append(f"## {overskrift}")
                gaa(barn)
            elif barn.tag == "Rubrica":
                continue
            elif barn.tag == "Linea":
                t = _linjer(barn)
                if t:
                    ud.append(t)
            else:
                gaa(barn)

    gaa(indhold)
    return "\n".join(ud).strip()


# ── Henvisninger ─────────────────────────────────────────────────────────────────────────

_MDR = {
    "januar": 1, "februar": 2, "marts": 3, "april": 4, "maj": 5, "juni": 6, "juli": 7,
    "august": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}


def laes_henvisning(tekst: str) -> tuple[int, int] | None:
    """Find (år, nummer) i en dansk henvisning.

    Forstår fx 'LBK nr. 145 af 24/02/2020', 'lovbekendtgørelse nr. 145 af 24. februar 2020',
    'lov nr. 655 af 11. juni 2024' og 'BEK nr 1080 af 03/10/2024'.
    """
    t = tekst.strip().lower()
    m = re.search(r"(?a)nr\.?\s*(\d+)\s+af\s+(\d{1,2})[./]\s*(\d{1,2})[./]\s*(\d{4})", t)
    if m:
        return int(m.group(4)), int(m.group(1))
    m = re.search(r"(?a)nr\.?\s*(\d+)\s+af\s+(\d{1,2})\.\s*([a-zæøå]+)\s+(\d{4})", t)
    if m and m.group(3) in _MDR:
        return int(m.group(4)), int(m.group(1))
    m = re.search(r"(?a)eli/lta/(\d{4})/(\d+)", t)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None
