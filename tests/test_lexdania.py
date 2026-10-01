from pathlib import Path

import pytest

from dk_lov_mcp import lexdania

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def ofl():
    return lexdania.rod((FIX / "lbk_2020_145.xml").read_text("utf-8"))


def test_metadata(ofl):
    m = lexdania.metadata(ofl)
    assert (m["aar"], m["nr"], m["dokumenttype"]) == (2020, 145, "LBK")
    assert m["accessionsnummer"] == "A20200014529"
    assert m["gaeldende"] is True
    assert m["betegnelse"] == "LBK nr. 145 af 24/02/2020"
    assert m["citat"] == "Offentlighedsloven (LBK nr. 145 af 24/02/2020)"
    assert m["eli"] == "https://www.retsinformation.dk/eli/lta/2020/145"


def test_senere_aendringer(ofl):
    ae = lexdania.metadata(ofl)["senere_aendringer"]
    assert [a["accessionsnummer"] for a in ae] == ["A20240065530"]
    assert ae[0]["dato"] == "2024-06-11"
    assert ae[0]["eli"].endswith("/eli/accn/A20240065530")


def test_paragraf_36_stk_2(ofl):
    t = lexdania.paragraf_tekst(ofl, "36", 2)
    assert t.startswith("§ 36, stk. 2.")
    assert "7 arbejdsdage" in t


def test_hel_paragraf_har_stykker(ofl):
    t = lexdania.paragraf_tekst(ofl, "§ 36")
    assert t.startswith("§ 36.")
    assert "Stk. 2." in t


def test_paragraf_9_punkter(ofl):
    t = lexdania.paragraf_tekst(ofl, "9", 1)
    assert "1)" in t and "2)" in t


def test_ukendt_paragraf_og_stk(ofl):
    assert lexdania.paragraf_tekst(ofl, "999") is None
    assert lexdania.paragraf_tekst(ofl, "36", 99) is None


def test_paragraf_liste_og_fuld_tekst(ofl):
    liste = lexdania.paragraf_liste(ofl)
    assert "1" in liste and "36" in liste and "39" in liste
    fuld = lexdania.fuld_tekst(ofl)
    assert "## Kapitel 1" in fuld
    assert "<" not in fuld


def test_aendringslov():
    r = lexdania.rod((FIX / "lov_2024_655.xml").read_text("utf-8"))
    m = lexdania.metadata(r)
    assert (m["aar"], m["nr"], m["dokumenttype"]) == (2024, 655, "LOV")
    assert "chikanøst" in lexdania.fuld_tekst(r)


@pytest.mark.parametrize("tekst,forventet", [
    ("LBK nr. 145 af 24/02/2020", (2020, 145)),
    ("lovbekendtgørelse nr. 145 af 24. februar 2020", (2020, 145)),
    ("lov nr. 655 af 11. juni 2024", (2024, 655)),
    ("BEK nr 1080 af 03/10/2024", (2024, 1080)),
    ("https://www.retsinformation.dk/eli/lta/2017/980", (2017, 980)),
    ("offentlighedsloven", None),
])
def test_laes_henvisning(tekst, forventet):
    assert lexdania.laes_henvisning(tekst) == forventet


def test_ugyldig_xml():
    with pytest.raises(lexdania.LexDaniaFejl):
        lexdania.rod("<ikke xml")


def test_xml_bombe_afvises():
    bombe = '<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "xx"><!ENTITY y "&x;&x;">]><a>&y;</a>'
    with pytest.raises(lexdania.LexDaniaFejl):
        lexdania.rod(bombe)


def test_tegnsaetning_uden_mellemrum():
    r = lexdania.rod("<Linea><Char>jf. § 37</Char><Char>, stk. 2</Char></Linea>")
    assert lexdania._linjer(r) == "jf. § 37, stk. 2"
