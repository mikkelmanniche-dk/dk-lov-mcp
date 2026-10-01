import os

import pytest
from fastmcp.exceptions import ToolError

from dk_lov_mcp import server

LIVE = pytest.mark.skipif(not os.environ.get("DK_LOV_LIVE"), reason="sæt DK_LOV_LIVE=1")


@pytest.mark.parametrize("navn,forventet", [
    ("offentlighedsloven", (2020, 145)),
    ("OFL", (2020, 145)),
    ("Miljøoplysningsloven", (2017, 980)),
    ("fvl", (2014, 433)),
    ("ÅRL", (2026, 402)),
    ("CVR-loven", (2026, 246)),
    ("LBK nr. 145 af 24/02/2020", (2020, 145)),
])
def test_koordinater_navn(navn, forventet):
    assert server._koordinater(navn, None, None, None) == forventet


def test_koordinater_andet():
    assert server._koordinater(None, 2024, 655, None) == (2024, 655)
    assert server._koordinater(None, None, None, "A20240065530") == "A20240065530"
    assert server._koordinater("A20240065530", None, None, None) == "A20240065530"


@pytest.mark.parametrize("args", [
    ("ukendt lov", None, None, None),
    (None, None, None, None),
    (None, 1200, 1, None),
    (None, None, None, "../x"),
])
def test_koordinater_fejl(args):
    with pytest.raises(ToolError):
        server._koordinater(*args)


def test_register_har_eli():
    reg = server.lov_register()
    assert {"offentlighedsloven", "miljoeoplysningsloven", "forvaltningsloven"} <= {r["noegle"] for r in reg}
    assert all(r["eli"].startswith("https://www.retsinformation.dk/eli/lta/") for r in reg)


def test_register_aliaser_er_entydige():
    set_ = {}
    for lov in server.lov_register():
        for navn in [lov["noegle"], *lov["aliaser"]]:
            n = navn.lower()
            assert set_.setdefault(n, lov["noegle"]) == lov["noegle"], f"{navn} peger på to love"


async def test_tools_registreret():
    navne = {t.name for t in await server.mcp.list_tools()}
    assert navne == {"lov_register", "lov_soeg", "lov_hent", "lov_paragraf", "lov_tekst", "lov_aendringer"}


@LIVE
async def test_live_paragraf(tmp_path, monkeypatch):
    monkeypatch.setenv("DK_LOV_CACHE_DIR", str(tmp_path))
    r = await server.lov_paragraf("36", 2, lov="offentlighedsloven")
    assert "7 arbejdsdage" in r["tekst"]
    assert r["gaeldende"] is True


@LIVE
async def test_live_soeg(tmp_path, monkeypatch):
    monkeypatch.setenv("DK_LOV_CACHE_DIR", str(tmp_path))
    r = await server.lov_soeg("offentlighedsloven")
    assert any(t["aar"] == 2020 and t["nr"] == 145 for t in r["traef"])


@LIVE
async def test_live_alle_registrerede_gaeldende(tmp_path, monkeypatch):
    monkeypatch.setenv("DK_LOV_CACHE_DIR", str(tmp_path))
    for lov in server.lov_register():
        m = await server.lov_hent(lov=lov["noegle"])
        assert m["gaeldende"], lov["noegle"]


def test_user_agent_er_ascii():
    from dk_lov_mcp.klient import USER_AGENT
    USER_AGENT.encode("ascii")


def test_eli_accn_link():
    assert server._koordinater("https://www.retsinformation.dk/eli/accn/A20240065530", None, None, None) == "A20240065530"


def test_soegesvar_validering():
    from dk_lov_mcp.klient import _aendringssvar, _soegesvar
    assert _soegesvar('{"documents": [1, {"a": 2}]}')["documents"] == [{"a": 2}]
    for daarligt in ('[]', '{"documents": null}', '<html>'):
        with pytest.raises(ValueError):
            _soegesvar(daarligt)
    with pytest.raises(ValueError):
        _aendringssvar('{"fejl": "x"}')


async def test_ugyldigt_svar_caches_ikke(tmp_path):
    import httpx
    from dk_lov_mcp.cache import HttpCache
    from dk_lov_mcp.klient import Klient
    kald = 0

    def handler(req):
        nonlocal kald
        kald += 1
        return httpx.Response(200, text="<html>fejlside")

    async with Klient(HttpCache(tmp_path)) as k:
        k._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        for _ in range(2):
            with pytest.raises(ValueError):
                await k.xml(2020, 145)
    assert kald == 2
