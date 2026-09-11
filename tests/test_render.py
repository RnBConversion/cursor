import io

import pytest

from asistentas.render import Colors, MarkdownStream

TEXT = (
    "# Antraste\n\nTai **stora** ir `kodas`, 2 * 2 = 4.\n\n"
    "- pirmas\n- antras\n\n1. vienas\n\n> citata\n\n"
    "```python\nx = 2 ** 3  # **ne** paryskinimas\n```\nGalas."
)


def render(text, *, color=True, chunk=None):
    out, err = io.StringIO(), io.StringIO()
    ms = MarkdownStream(Colors(color), out=out, err=err)
    if chunk is None:
        ms.feed(text)
    else:
        for i in range(0, len(text), chunk):
            ms.feed(text[i : i + chunk])
    ms.close()
    return out.getvalue(), err.getvalue()


def strip_ansi(s: str) -> str:
    import re

    return re.sub(r"\033\[[0-9;]*m", "", s)


@pytest.mark.parametrize("chunk", [1, 2, 3, 5, 7, 13, 64, None])
def test_gabaliuku_dydis_nekeicia_rezultato(chunk):
    """Srautas ateina atsitiktiniais gabalais — rezultatas turi nesikeisti."""
    assert render(TEXT, chunk=chunk)[0] == render(TEXT)[0]


def test_zymes_pakeiciamos_spalvomis():
    plain = strip_ansi(render(TEXT)[0])
    assert "**stora**" not in plain and "stora" in plain
    assert "`kodas`" not in plain and "kodas" in plain
    assert "# Antraste" not in plain and "Antraste" in plain
    assert "• pirmas" in plain  # sąrašo ženkliukas
    assert "1. vienas" in plain


def test_kodo_blokas_lieka_toks_koks_yra():
    plain = strip_ansi(render(TEXT)[0])
    assert "x = 2 ** 3  # **ne** paryskinimas" in plain
    assert "```" not in plain  # tvorelės nerodomos
    assert "│ " in plain       # bet blokas paženklintas


def test_pavienes_zvaigzdutes_islieka():
    assert "2 * 2 = 4" in strip_ansi(render(TEXT)[0])


def test_be_spalvu_tekstas_nekeiciamas():
    """Nukreipiant į failą turi likti švarus markdown."""
    out, _ = render(TEXT, color=False)
    assert out.rstrip("\n") == TEXT.rstrip("\n")


def test_pastabos_atskiriamos_nuo_atsakymo():
    out = io.StringIO()
    err = io.StringIO()
    ms = MarkdownStream(Colors(True), out=out, err=err)
    ms.feed("Pradžia")
    ms.note("🔎 ieškau")
    ms.feed("tęsinys")
    ms.close()
    plain = strip_ansi(out.getvalue())
    assert plain.startswith("Pradžia\n")  # pastaba nepriklijuota prie teksto
    assert "🔎 ieškau" in plain


def test_pastabos_i_stderr_kai_nera_spalvu():
    out = io.StringIO()
    err = io.StringIO()
    ms = MarkdownStream(Colors(False), out=out, err=err)
    ms.feed("atsakymas")
    ms.note("🔎 ieškau")
    ms.close()
    assert "🔎" not in out.getvalue()   # išvestis lieka švari
    assert "🔎 ieškau" in err.getvalue()


def test_mastymas_baigiasi_nauja_eilute():
    out = io.StringIO()
    ms = MarkdownStream(Colors(True), out=out)
    ms.thinking("svarstau")
    ms.feed("Atsakymas")
    ms.close()
    plain = strip_ansi(out.getvalue())
    assert plain == "svarstau\nAtsakymas\n"


def test_uzdarymas_palieka_svaria_eilute():
    out, _ = render("be naujos eilutes gale")
    assert out.endswith("\n")


def test_nebaigta_zvaigzdute_neprarandama():
    out = io.StringIO()
    ms = MarkdownStream(Colors(True), out=out)
    ms.feed("galas *")
    ms.close()
    assert "*" in strip_ansi(out.getvalue())
