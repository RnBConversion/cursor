import io

import pytest
from conftest import ApiError, FakeClient, message, search_events, text_delta, thinking_delta

from asistentas.agent import MAX_CONTINUATIONS, Assistant
from asistentas.render import Colors, MarkdownStream
from asistentas.session import Session


def renderer():
    out = io.StringIO()
    return MarkdownStream(Colors(False), out=out, err=io.StringIO()), out


def assistant(cfg, client, session=None):
    return Assistant(cfg, session or Session(), client=client)


# ---- užklausos sudėliojimas ---------------------------------------------


def test_uzklausoje_yra_visa_ko_reikia(cfg):
    kw = assistant(cfg, None).request_kwargs()
    assert kw["model"] == "claude-opus-5"
    assert kw["thinking"] == {"type": "adaptive"}
    assert kw["output_config"] == {"effort": "high"}
    assert kw["max_tokens"] == 64000
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert cfg.persona.splitlines()[0] in kw["system"][0]["text"]


def test_atsarginis_modelis_ijungtas(cfg):
    """Opus 5 gali atsisakyti atsakyti — tada serveris perleidžia kitam modeliui."""
    kw = assistant(cfg, None).request_kwargs()
    assert kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]


def test_paieskos_irankis(cfg):
    tool = assistant(cfg, None).tools()[0]
    assert tool["type"] == "web_search_20260209"
    assert tool["name"] == "web_search"
    assert tool["max_uses"] == 5
    assert tool["user_location"] == {
        "type": "approximate",
        "country": "LT",
        "timezone": "Europe/Vilnius",
    }


def test_israiska_be_paieskos(cfg):
    kw = assistant(cfg.with_(search=False), None).request_kwargs()
    assert "tools" not in kw


def test_domenu_ribojimas(cfg):
    tik = assistant(cfg.with_(allowed_domains=("lrt.lt",)), None).tools()[0]
    assert tik["allowed_domains"] == ["lrt.lt"]
    be = assistant(cfg.with_(blocked_domains=("pinterest.com",)), None).tools()[0]
    assert be["blocked_domains"] == ["pinterest.com"]
    assert "allowed_domains" not in be


def test_mastymo_rodymas(cfg):
    kw = assistant(cfg.with_(show_thinking=True), None).request_kwargs()
    assert kw["thinking"] == {"type": "adaptive", "display": "summarized"}


# ---- šiandienos data ----------------------------------------------------


def test_data_pridedama_atskira_zinute(cfg):
    client = FakeClient(([text_delta("gerai")], message(text="gerai")))
    s = Session()
    a = assistant(cfg, client, s)
    a.ask("labas", renderer()[0])
    roles = [m["role"] for m in s.messages]
    assert roles == ["user", "system", "assistant"]
    assert "Šiandien" in s.messages[1]["content"]


def test_data_nekartojama_ta_pacia_diena(cfg):
    client = FakeClient(
        ([text_delta("a")], message(text="a")),
        ([text_delta("b")], message(text="b")),
    )
    s = Session()
    a = assistant(cfg, client, s)
    a.ask("pirmas", renderer()[0])
    a.ask("antras", renderer()[0])
    assert sum(1 for m in s.messages if m["role"] == "system") == 1


def test_senesniam_modeliui_data_keliauja_prompte(cfg):
    """Ne visi modeliai priima `system` žinutes pokalbio viduryje."""
    sonnet = cfg.with_(model="claude-sonnet-5")
    client = FakeClient(([text_delta("a")], message(text="a")))
    s = Session()
    a = assistant(sonnet, client, s)
    a.ask("labas", renderer()[0])
    assert all(m["role"] != "system" for m in s.messages)
    assert "Šiandien" in client.calls[0]["system"][0]["text"]


# ---- atsakymo srautas ---------------------------------------------------


def test_atsakymas_rasomas_ir_issaugomas(cfg):
    client = FakeClient(([text_delta("La"), text_delta("bas")], message(text="Labas")))
    s = Session()
    r, out = renderer()
    turn = assistant(cfg, client, s).ask("sveiki", r)
    assert out.getvalue().strip() == "Labas"
    assert turn.text == "Labas"
    assert s.messages[-1] == {"role": "assistant", "content": [{"type": "text", "text": "Labas"}]}
    assert s.usage.output_tokens == 5


def test_paieska_parodoma_vartotojui(cfg):
    events = [*search_events("elektros kaina"), text_delta("Atsakymas")]
    client = FakeClient((events, message(text="Atsakymas")))
    r, out = renderer()
    assistant(cfg, client, Session()).ask("kiek?", r)
    assert "🔎 ieškau: elektros kaina" in r.err.getvalue()


def test_mastymas_rodomas_tik_ijungus(cfg):
    events = [thinking_delta("svarstau"), text_delta("Atsakymas")]
    client = FakeClient((events, message(text="Atsakymas")))
    r, out = renderer()
    assistant(cfg.with_(show_thinking=True), client, Session()).ask("kodėl?", r)
    assert "svarstau" in r.err.getvalue()

    client = FakeClient((events, message(text="Atsakymas")))
    r2, _ = renderer()
    assistant(cfg, client, Session()).ask("kodėl?", r2)
    assert "svarstau" not in r2.err.getvalue()


# ---- šaltiniai ----------------------------------------------------------


def _search_result_block(results):
    return {
        "type": "web_search_tool_result",
        "tool_use_id": "srvtoolu_1",
        "content": [
            {"type": "web_search_result", "title": t, "url": u, "encrypted_content": "x"}
            for t, u in results
        ],
    }


def test_saltiniai_surenkami_ir_nesikartoja(cfg):
    blocks = [
        _search_result_block([("LRT", "https://lrt.lt/a"), ("Delfi", "https://delfi.lt/b")]),
        _search_result_block([("LRT vėl", "https://lrt.lt/a")]),
        {"type": "text", "text": "Atsakymas"},
    ]
    client = FakeClient(([], message(content=blocks)))
    turn = assistant(cfg, client, Session()).ask("kas naujo?", renderer()[0])
    assert turn.sources == [("LRT", "https://lrt.lt/a"), ("Delfi", "https://delfi.lt/b")]


def test_paieskos_klaida_nepaslepiama(cfg):
    """Serverinio įrankio klaida grįžta objektu, ne sąrašu."""
    blocks = [
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_1",
            "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"},
        }
    ]
    client = FakeClient(([], message(content=blocks)))
    turn = assistant(cfg, client, Session()).ask("kas naujo?", renderer()[0])
    assert turn.sources == []
    assert any("limitas" in n for n in turn.notes)


# ---- sustojimo priežastys -----------------------------------------------


def test_pause_turn_tesiamas(cfg):
    """Ilga paieška sustoja ties serverio ciklo riba — reikia tęsti."""
    client = FakeClient(
        ([text_delta("Pradžia")], message(text="Pradžia", stop_reason="pause_turn")),
        ([text_delta(" ir pabaiga")], message(text=" ir pabaiga")),
    )
    s = Session()
    turn = assistant(cfg, client, s).ask("ilgas klausimas", renderer()[0])
    assert len(client.calls) == 2
    assert turn.text == "Pradžia ir pabaiga"
    assert turn.stop_reason == "end_turn"
    # antra užklausa turi atsinešti visą istoriją, kad serveris tęstų
    assert len(client.calls[1]["messages"]) > len(client.calls[0]["messages"])
    assert turn.usage.output_tokens == 10  # susumuota iš abiejų
    # istorijoje lieka viena atsakymo eilė, o ne dvi iš eilės
    assert [m["role"] for m in s.messages] == ["user", "system", "assistant"]
    assert len(s.messages[-1]["content"]) == 2


def test_pause_turn_neamzinas(cfg):
    turns = [([], message(stop_reason="pause_turn")) for _ in range(MAX_CONTINUATIONS)]
    client = FakeClient(*turns)
    turn = assistant(cfg, client, Session()).ask("klausimas", renderer()[0])
    assert len(client.calls) == MAX_CONTINUATIONS
    assert any("nutraukiau" in n for n in turn.notes)


def test_atsisakymas_paaiskinamas(cfg):
    final = message(
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": "negaliu padėti"},
    )
    client = FakeClient(([], final))
    turn = assistant(cfg, client, Session()).ask("kaip įsilaužti", renderer()[0])
    assert turn.refusal == "negaliu padėti"


def test_nutrukes_ilgis_pazymimas(cfg):
    client = FakeClient(([text_delta("pusė")], message(text="pusė", stop_reason="max_tokens")))
    turn = assistant(cfg, client, Session()).ask("labai ilgai", renderer()[0])
    assert any("ilgio riba" in n for n in turn.notes)


# ---- klaidos ------------------------------------------------------------


def test_be_atsarginio_modelio_bandoma_dar_karta(cfg):
    """Jei API dar nemoka `fallbacks`, tęsiame be jo, o ne nutraukiame pokalbį."""
    client = FakeClient(
        ApiError("fallbacks: unsupported beta"),
        ([text_delta("veikia")], message(text="veikia")),
    )
    turn = assistant(cfg, client, Session()).ask("labas", renderer()[0])
    assert turn.text == "veikia"
    assert "fallbacks" in client.calls[0]
    assert "fallbacks" not in client.calls[1]


def test_kitos_klaidos_perduodamos(cfg):
    client = FakeClient(ApiError("overloaded", status_code=529))
    with pytest.raises(ApiError):
        assistant(cfg, client, Session()).ask("labas", renderer()[0])


def test_nutraukus_issaugomas_pradetas_atsakymas(cfg):
    def events():
        yield text_delta("pusė atsakymo")
        raise KeyboardInterrupt

    client = FakeClient((events(), message(text="nesvarbu")))
    s = Session()
    with pytest.raises(KeyboardInterrupt):
        assistant(cfg, client, s).ask("klausimas", renderer()[0])
    assert s.messages[-1]["content"] == [{"type": "text", "text": "pusė atsakymo"}]


def test_nutraukus_be_teksto_klausimas_pasalinamas(cfg):
    def events():
        raise KeyboardInterrupt
        yield  # pragma: no cover

    client = FakeClient((events(), message()))
    s = Session()
    with pytest.raises(KeyboardInterrupt):
        assistant(cfg, s and client, s).ask("klausimas", renderer()[0])
    assert s.messages == []
    assert s.last_date == ""  # kitą kartą datą pasakysime iš naujo
