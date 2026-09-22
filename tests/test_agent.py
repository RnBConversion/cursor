import io

import pytest
from conftest import ApiError, FakeClient, message, search_events, text_delta, thinking_delta, tool_use

from asistentas.agent import MAX_STEPS, Assistant
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
    tool = assistant(cfg, None).tools()[0]  # paieška — pirma sąraše
    assert tool["type"] == "web_search_20260209"
    assert tool["name"] == "web_search"
    assert tool["max_uses"] == 5
    assert tool["user_location"] == {
        "type": "approximate",
        "city": "Telšiai",
        "region": "Telšių apskritis",
        "country": "LT",
        "timezone": "Europe/Vilnius",
    }


def test_israiska_be_irankiu(cfg):
    """Išjungus viską, įrankių sąrašo iš viso nesiunčiame."""
    plikas = cfg.with_(search=False, memory=False, files_roots=())
    assert "tools" not in assistant(plikas, None).request_kwargs()


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
    turns = [([], message(stop_reason="pause_turn")) for _ in range(MAX_STEPS)]
    client = FakeClient(*turns)
    turn = assistant(cfg, client, Session()).ask("klausimas", renderer()[0])
    assert len(client.calls) == MAX_STEPS
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


# ---- įrankiai mano kompiuteryje ----------------------------------------


def _cfg_with_files(cfg, tmp_path):
    katalogas = tmp_path / "uzrasai"
    katalogas.mkdir(parents=True, exist_ok=True)
    (katalogas / "planas.md").write_text("Terminas: spalio 1 d.\n", encoding="utf-8")
    return cfg.with_(files_roots=(str(katalogas),))


def test_atminties_irankis_ijungtas(cfg):
    vardai = [t.get("name") for t in assistant(cfg, None).tools()]
    assert "memory" in vardai
    assert "Atmintis" in assistant(cfg, None).system_blocks()[0]["text"]


def test_atminti_galima_isjungti(cfg):
    be = cfg.with_(memory=False)
    assert "memory" not in [t.get("name") for t in assistant(be, None).tools()]
    assert "Atmintis" not in assistant(be, None).system_blocks()[0]["text"]


def test_failu_irankiai_tik_nurodzius_katalogus(cfg, tmp_path):
    assert [t.get("name") for t in assistant(cfg, None).tools() if t.get("name", "").endswith("_file")] == []
    su = _cfg_with_files(cfg, tmp_path)
    vardai = [t.get("name") for t in assistant(su, None).tools()]
    assert {"list_files", "search_files", "read_file"} <= set(vardai)


def test_atminties_irankis_ivykdomas(cfg):
    """Modelis paprašo įsiminti — įvykdome ir grąžiname rezultatą."""
    prasymas = message(
        stop_reason="tool_use",
        content=[tool_use("memory", {"command": "create", "path": "/memories/apie.md", "file_text": "Vardas: R"})],
    )
    client = FakeClient((([], prasymas)), ([text_delta("Įsiminiau.")], message(text="Įsiminiau.")))
    s = Session()
    r, _ = renderer()
    turn = assistant(cfg, client, s).ask("įsimink mano vardą", r)

    assert turn.text == "Įsiminiau." and turn.tool_calls == 1
    rezultatas = s.messages[-2]                       # po tool_use eina tool_result
    assert rezultatas["role"] == "user"
    assert rezultatas["content"][0]["type"] == "tool_result"
    assert "įrašyta" in rezultatas["content"][0]["content"]
    assert (cfg.memory_dir / "apie.md").read_text(encoding="utf-8") == "Vardas: R"
    assert "🧠 įsimenu" in r.err.getvalue()


def test_failo_skaitymas_ivykdomas(cfg, tmp_path):
    su = _cfg_with_files(cfg, tmp_path)
    prasymas = message(stop_reason="tool_use", content=[tool_use("read_file", {"path": "planas.md"})])
    client = FakeClient(([], prasymas), ([text_delta("Spalio 1 d.")], message(text="Spalio 1 d.")))
    s = Session()
    r, _ = renderer()
    assistant(su, client, s).ask("kada terminas?", r)
    assert "Terminas: spalio 1 d." in s.messages[-2]["content"][0]["content"]
    assert "📄 skaitau: planas.md" in r.err.getvalue()


def test_keli_irankiai_grazinami_viena_zinute(cfg, tmp_path):
    """API reikalauja visų rezultatų vienoje žinutėje — kitaip modelis
    nustoja kviesti įrankius lygiagrečiai."""
    su = _cfg_with_files(cfg, tmp_path)
    prasymas = message(
        stop_reason="tool_use",
        content=[
            tool_use("read_file", {"path": "planas.md"}, "toolu_1"),
            tool_use("memory", {"command": "view", "path": "/memories"}, "toolu_2"),
        ],
    )
    client = FakeClient(([], prasymas), ([text_delta("ok")], message(text="ok")))
    s = Session()
    turn = assistant(su, client, s).ask("ką žinai?", renderer()[0])
    rezultatai = s.messages[-2]["content"]
    assert len(rezultatai) == 2 and turn.tool_calls == 2
    assert [b["tool_use_id"] for b in rezultatai] == ["toolu_1", "toolu_2"]


def test_irankio_klaida_grazinama_modeliui(cfg, tmp_path):
    """Klaida nėra pokalbio pabaiga — modelis turi galimybę pasitaisyti."""
    su = _cfg_with_files(cfg, tmp_path)
    prasymas = message(stop_reason="tool_use", content=[tool_use("read_file", {"path": "/etc/passwd"})])
    client = FakeClient(([], prasymas), ([text_delta("Negaliu to pasiekti.")], message(text="Negaliu to pasiekti.")))
    s = Session()
    turn = assistant(su, client, s).ask("parodyk /etc/passwd", renderer()[0])
    rezultatas = s.messages[-2]["content"][0]
    assert rezultatas["is_error"] is True
    assert "nepasiekiamas" in rezultatas["content"]
    assert turn.text == "Negaliu to pasiekti."


def test_nezinomas_irankis(cfg):
    prasymas = message(stop_reason="tool_use", content=[tool_use("nusiusk_pinigus", {"suma": 100})])
    client = FakeClient(([], prasymas), ([text_delta("ne")], message(text="ne")))
    s = Session()
    assistant(cfg, client, s).ask("x", renderer()[0])
    assert s.messages[-2]["content"][0]["is_error"] is True


def test_irankiu_ciklas_nesisuka_be_galo(cfg):
    prasymai = [
        ([], message(stop_reason="tool_use", content=[tool_use("memory", {"command": "view", "path": "/memories"})]))
        for _ in range(MAX_STEPS)
    ]
    client = FakeClient(*prasymai)
    turn = assistant(cfg, client, Session()).ask("x", renderer()[0])
    assert len(client.calls) == MAX_STEPS
    assert any("žingsnių" in n for n in turn.notes)


def test_nutraukus_irankiu_cikla_istorija_lieka_taisyklinga(cfg):
    """Po `tool_use` privalo eiti `tool_result` — kitaip kita užklausa nulūžta."""
    prasymas = message(stop_reason="tool_use", content=[tool_use("memory", {"command": "view", "path": "/memories"})])

    def nutraukti():
        yield text_delta("pradėjau")
        raise KeyboardInterrupt

    client = FakeClient(([], prasymas), (nutraukti(), message()))
    s = Session()
    with pytest.raises(KeyboardInterrupt):
        assistant(cfg, client, s).ask("x", renderer()[0])

    for i, zinute in enumerate(s.messages):
        for blokas in zinute["content"] if isinstance(zinute["content"], list) else []:
            if isinstance(blokas, dict) and blokas.get("type") == "tool_use":
                kitas = s.messages[i + 1]["content"]
                assert any(b.get("tool_use_id") == blokas["id"] for b in kitas)
    assert s.messages[-1]["role"] == "assistant"


# ---- MCP (Gmail, kalendorius ir kt.) ------------------------------------


def test_mcp_serveriai_perduodami(cfg, monkeypatch):
    su = cfg.with_(
        mcp_servers=({"pavadinimas": "gmail", "url": "https://mcp.pvz.lt/gmail", "token_env": "GMAIL_TOKEN"},)
    )
    monkeypatch.setenv("GMAIL_TOKEN", "slaptas-raktas")
    kw = assistant(su, None).request_kwargs()
    assert kw["mcp_servers"] == [
        {"type": "url", "url": "https://mcp.pvz.lt/gmail", "name": "gmail", "authorization_token": "slaptas-raktas"}
    ]
    assert {"type": "mcp_toolset", "mcp_server_name": "gmail"} in kw["tools"]
    assert "mcp-client-2025-11-20" in kw["betas"]


def test_mcp_be_rakto_vis_tiek_jungiasi(cfg, monkeypatch):
    """Ne kiekvienam serveriui reikia rakto; be jo nieko nelaužome."""
    su = cfg.with_(mcp_servers=({"pavadinimas": "vietinis", "url": "https://mcp.pvz.lt/x", "token_env": None},))
    kw = assistant(su, None).request_kwargs()
    assert "authorization_token" not in kw["mcp_servers"][0]
