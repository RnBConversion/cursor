import sys

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


# ---- atmintis ir failai -------------------------------------------------


def test_atmintis_tuscia(cfg, capsys):
    app(cfg)._command("/atmintis")
    assert "tuščia" in capsys.readouterr().out


def test_atmintis_rodo_ir_istrina(cfg, capsys, monkeypatch):
    from asistentas.memory import MemoryStore

    store = MemoryStore(cfg.memory_dir)
    store.call({"command": "create", "path": "/memories/apie.md", "file_text": "Vardas: R"})
    a = app(cfg)

    a._command("/atmintis")
    assert "/memories/apie.md" in capsys.readouterr().out
    a._command("/atmintis viskas")
    assert "Vardas: R" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda *_: "ne")
    a._command("/atmintis pamirsk")
    assert store.files()                       # neišdrįsus — lieka

    monkeypatch.setattr("builtins.input", lambda *_: "taip")
    a._command("/atmintis pamirsk")
    assert store.files() == []
    assert "ištrinta" in capsys.readouterr().out


def test_atmintis_isjungta(cfg, capsys):
    app(cfg.with_(memory=False))._command("/atmintis")
    assert "išjungta" in capsys.readouterr().out


def test_failai_be_nustatymu(cfg, capsys):
    app(cfg)._command("/failai")
    assert "nenurodyti" in capsys.readouterr().out


def test_failai_rodo_katalogus(cfg, capsys, tmp_path):
    katalogas = tmp_path / "uzrasai"
    katalogas.mkdir()
    a = app(cfg.with_(files_roots=(str(katalogas), str(tmp_path / "nera"))))
    a._command("/failai")
    isvestis = capsys.readouterr().out
    assert str(katalogas) in isvestis
    assert "(nerastas)" in isvestis          # klaidingas kelias matomas iš karto
    assert "skaitoma tik" in isvestis


# ---- balso įvestis ------------------------------------------------------


class FakeVoice:
    def __init__(self, text="kada terminas", ready=True, klaida=None):
        self._text, self.ready, self._klaida = text, ready, klaida
        self.kviesta = 0

    def problems(self):
        return ["įrašymo programos — brew install sox", "atpažinimo variklio — pip install faster-whisper"]

    def capture(self, wait, on_start=None, on_transcribe=None):
        self.kviesta += 1
        if self._klaida:
            raise self._klaida
        if on_start:
            on_start()
        return self._text


def test_balsas_padeda_teksta_i_ivesties_eilute(cfg):
    a = app(cfg)
    a._voice_input = FakeVoice("kada mano projekto terminas")
    a._command("/balsas")
    assert a._pending == "kada mano projekto terminas"


def test_balsas_be_irangos_pasako_ka_diegti(cfg, capsys):
    a = app(cfg)
    a._voice_input = FakeVoice(ready=False)
    a._command("/balsas")
    err = capsys.readouterr().err
    assert "brew install sox" in err and "faster-whisper" in err
    assert a._pending == ""


def test_balsas_isjungtas_nustatymuose(cfg, capsys):
    from asistentas.config import Voice

    a = app(cfg.with_(voice=Voice(enabled=False)))
    a._command("/balsas")
    assert "išjungta" in capsys.readouterr().out


def test_balso_klaida_nenutraukia_pokalbio(cfg, capsys):
    from asistentas.voice import VoiceError

    a = app(cfg)
    a._voice_input = FakeVoice(klaida=VoiceError("mikrofonas užimtas"))
    a._command("/balsas")
    assert "mikrofonas užimtas" in capsys.readouterr().err
    assert a._pending == ""


def test_tyla_nesiunciama_i_api(cfg, capsys):
    a = app(cfg)
    a._voice_input = FakeVoice(text="")
    a._command("/balsas")
    assert "negirdėjau" in capsys.readouterr().out
    assert a._pending == ""


def test_nutraukus_irasyma_liekame_pokalbyje(cfg, capsys):
    a = app(cfg)
    a._voice_input = FakeVoice(klaida=KeyboardInterrupt())
    a._command("/balsas")
    assert "atšaukta" in capsys.readouterr().out


def test_atpazinta_teksta_galima_pataisyti(cfg, monkeypatch):
    """Balsu atpažintas tekstas atsiranda eilutėje, bet paskutinis žodis — tavo."""
    a = app(cfg)
    a._pending = "kada mano projekto terminas"
    monkeypatch.setattr("builtins.input", lambda *_: "kada mano projekto terminas?")
    assert a._read_line() == "kada mano projekto terminas?"
    assert a._pending == ""


def test_prefill_paduodamas_readline(cfg, monkeypatch):
    import readline

    ikelta = []
    monkeypatch.setattr(readline, "insert_text", ikelta.append)
    monkeypatch.setattr(readline, "set_startup_hook", lambda hook=None: hook and hook())
    monkeypatch.setattr("builtins.input", lambda *_: "x")
    a = app(cfg)
    a._pending = "atpažintas tekstas"
    a._read_line()
    assert ikelta == ["atpažintas tekstas"]


def test_balsas_vienkartiniam_klausimui_reikia_terminalo(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ASISTENTAS_HOME", str(tmp_path / "a"))
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False, "read": lambda self: ""})())
    assert cli.main(["--balsas"]) == 2
    assert "terminalo" in capsys.readouterr().err


def test_balso_veiksena_paleidziama_veliava():
    assert cli.build_parser().parse_args(["--balsas"]).balsas is True


def test_veikia_ir_be_readline(cfg, monkeypatch):
    """Windows readline neturi — tekstas tada tiesiog parodomas, Enter patvirtina."""
    monkeypatch.setitem(sys.modules, "readline", None)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    a = app(cfg)
    a._pending = "atpažintas tekstas"
    assert a._read_line() == "atpažintas tekstas"


def test_veikia_kai_readline_neturi_kabliuko(cfg, monkeypatch, capsys):
    """macOS libedit: prefill gali neveikti — tai neturi nulaužti pokalbio."""
    import readline

    def nepalaikoma(*_):
        raise AttributeError("set_startup_hook")

    monkeypatch.setattr(readline, "set_startup_hook", nepalaikoma)
    monkeypatch.setattr("builtins.input", lambda *_: "")
    a = app(cfg)
    a._pending = "atpažintas tekstas"
    assert a._read_line() == "atpažintas tekstas"
    assert "atpažintas tekstas" in capsys.readouterr().out


# ---- tiekėjo perjungimas ------------------------------------------------


def test_tiekejo_perjungimas(cfg, capsys):
    a = app(cfg)
    a._command("/tiekejas ollama")
    assert a.cfg.provider == "ollama"
    isvestis = capsys.readouterr().out
    assert "ollama qwen3:32b (lokaliai)" in isvestis
    assert "paieškos internete ir MCP šiuo varikliu nėra" in isvestis
    a._command("/tiekejas anthropic")
    assert a.cfg.provider == "anthropic"


def test_nezinomas_tiekejas(cfg, capsys):
    a = app(cfg)
    a._command("/tiekejas kazkoks")
    assert "galimi: anthropic, ollama" in capsys.readouterr().err
    assert a.cfg.provider == "anthropic"


def test_lokalus_modelis_nerodo_kainos(cfg):
    from asistentas.pricing import Usage

    a = app(cfg.with_(provider="ollama"))
    assert a.cost_text(Usage(input_tokens=5000)) == "lokaliai"


def test_debesies_ollama_rodo_kreditus(cfg):
    from asistentas.config import Ollama
    from asistentas.pricing import Usage

    a = app(cfg.with_(provider="ollama", ollama=Ollama(address="https://ollama.com")))
    assert a.cost_text(Usage(input_tokens=5000)) == "debesų kreditai"
    assert "debesyje" in a.model_label()


def test_modelis_keiciamas_tam_varikliui_kuris_ijungtas(cfg):
    a = app(cfg.with_(provider="ollama"))
    a._command("/modelis llama3.3:70b")
    assert a.cfg.ollama.model == "llama3.3:70b"
    assert a.cfg.model == "claude-opus-5"      # Claude modelis nepaliestas


def test_tiekejas_is_veliavos(monkeypatch, tmp_path):
    monkeypatch.setenv("ASISTENTAS_HOME", str(tmp_path / "a"))
    assert cli.build_parser().parse_args(["--tiekejas", "ollama"]).tiekejas == "ollama"
