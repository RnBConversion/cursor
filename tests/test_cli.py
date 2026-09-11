import pytest
from conftest import ApiError, FakeClient, message, text_delta

from asistentas import cli
from asistentas.render import Colors
from asistentas.session import Session


def app(cfg, *, color=False, footer=False):
    a = cli.App(cfg, Colors(color), show_footer=footer)
    return a


def test_vienkartinis_klausimas(cfg, capsys):
    a = app(cfg)
    a._client = FakeClient(([text_delta("Atsakymas")], message(text="Atsakymas")))
    assert a.ask("klausimas") == 0
    assert capsys.readouterr().out.strip() == "Atsakymas"
    # pokalbis nusėda diske iš karto
    assert a.store.load(a.session.id).messages[-1]["content"][0]["text"] == "Atsakymas"


def test_footer_rodo_saltinius_ir_kaina(cfg, capsys):
    a = app(cfg, footer=True)
    blocks = [
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_1",
            "content": [
                {
                    "type": "web_search_result",
                    "title": "LRT",
                    "url": "https://lrt.lt/a",
                    "encrypted_content": "x",
                }
            ],
        },
        {"type": "text", "text": "Atsakymas"},
    ]
    a._client = FakeClient(([], message(content=blocks, usage={"server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 0}})))
    a.ask("kas naujo?")
    out = capsys.readouterr().out
    assert "https://lrt.lt/a" in out
    assert "$" in out and "žet." in out


def test_klaida_paaiskinama_zmogui(cfg, capsys):
    a = app(cfg)
    a._client = FakeClient(ApiError("no key", status_code=401))
    assert a.ask("labas") == 1
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err
    assert "Traceback" not in err


def test_nutraukimas_grazina_130(cfg, capsys):
    def events():
        yield text_delta("dalis")
        raise KeyboardInterrupt

    a = app(cfg)
    a._client = FakeClient((events(), message()))
    assert a.ask("labas") == 130
    assert "nutraukta" in capsys.readouterr().out


def test_klientas_naudojamas_pakartotinai(cfg):
    a = app(cfg)
    client = FakeClient(
        ([text_delta("a")], message(text="a")),
        ([text_delta("b")], message(text="b")),
    )
    a._client = client
    a.ask("pirmas")
    a.ask("antras")
    assert a._client is client and len(client.calls) == 2


# ---- komandos -----------------------------------------------------------


def test_komanda_nauja_issaugo_sena(cfg):
    a = app(cfg)
    a.session.add_user("senas")
    senas = a.session.id
    a._command("/nauja")
    assert a.session.id != senas
    assert a.store.load(senas).title == "senas"


def test_komanda_modelis_ir_pastangos(cfg, capsys):
    a = app(cfg)
    a._command("/modelis claude-sonnet-5")
    assert a.cfg.model == "claude-sonnet-5" and a.session.model == "claude-sonnet-5"
    a._command("/pastangos low")
    assert a.cfg.effort == "low"
    a._command("/pastangos kazkas")
    assert "galimos" in capsys.readouterr().err


def test_komanda_paieska_perjungia(cfg):
    a = app(cfg)
    a._command("/paieska off")
    assert a.cfg.search is False
    a._command("/paieska")          # be argumento — perjungia atgal
    assert a.cfg.search is True
    a._command("/mastymas on")
    assert a.cfg.show_thinking is True


def test_komanda_tesk(cfg, capsys):
    a = app(cfg)
    a.session.add_user("pirmas pokalbis")
    a.store.save(a.session)
    senas = a.session.id
    a.session = Session()
    a._command("/tesk")
    assert a.session.id == senas
    a._command("/tesk nera-tokios")
    assert "nėra" in capsys.readouterr().err


def test_komanda_istorija_ir_kaina(cfg, capsys):
    a = app(cfg)
    a.session.add_user("klausimas")
    a.session.add_assistant([{"type": "text", "text": "atsakymas"}])
    a._command("/istorija")
    a._command("/kaina")
    out = capsys.readouterr().out
    assert "klausimas" in out and "atsakymas" in out
    assert "žetonų" in out


def test_iseiti_ir_nezinoma_komanda(cfg, capsys):
    a = app(cfg)
    assert a._command("/iseiti") is False
    assert a._command("/pagalba") is None
    a._command("/nesamone")
    assert "nežinoma komanda" in capsys.readouterr().err


# ---- smulkmenos ---------------------------------------------------------


@pytest.mark.parametrize(
    "klaida, tekstas",
    [
        (ApiError("x", 401), "ANTHROPIC_API_KEY"),
        (ApiError("x", 403), "teisių"),
        (ApiError("x", 404), "modelio"),
        (ApiError("x", 429), "Per daug"),
        (ApiError("x", 500), "serverio klaida"),
        (ApiError("kažkas kito", 400), "kažkas kito"),
    ],
)
def test_klaidu_vertimas(klaida, tekstas):
    assert tekstas in cli.friendly_error(klaida)


def test_nera_rakto_dar_nesusisiekus_su_api():
    """SDK tokiu atveju meta ne HTTP klaidą, o angliškai paaiškina prie kliento."""
    e = TypeError("Could not resolve authentication method. Expected one of api_key, ...")
    assert "ANTHROPIC_API_KEY" in cli.friendly_error(e)


def test_rysio_klaida():
    class APIConnectionError(Exception):
        pass

    assert "ryšį" in cli.friendly_error(APIConnectionError())


def test_zinutes_tekstas():
    assert cli._message_text({"content": "paprastas"}) == "paprastas"
    assert cli._message_text({"content": [{"type": "text", "text": "blokas"}]}) == "blokas"
    assert cli._message_text({"content": [{"type": "thinking", "thinking": "x"}]}) == ""


def test_parametru_apdorojimas():
    args = cli.build_parser().parse_args(["kiek", "valandų", "--pastangos", "low"])
    assert args.klausimas == ["kiek", "valandų"] and args.pastangos == "low"
    assert cli.build_parser().parse_args(["--tesk"]).tesk == ""


def test_main_be_klausimo_is_duodeles(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ASISTENTAS_HOME", str(tmp_path / "a"))
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False, "read": lambda self: ""})())
    assert cli.main([]) == 2
    assert "Nėra klausimo" in capsys.readouterr().err
