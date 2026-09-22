import pytest

from asistentas import config


def test_pirmas_paleidimas_sukuria_failus(home):
    cfg = config.load(home=home)
    assert cfg.persona_path.exists() and cfg.config_path.exists()
    assert cfg.sessions_dir.is_dir()
    assert cfg.model == "claude-opus-5"
    assert cfg.search is True


def test_katalogas_neprieinamas_kitiems(home):
    config.load(home=home)
    assert (home.stat().st_mode & 0o077) == 0     # pokalbiai yra asmeniniai


def test_asmenybe_skaitoma_is_failo(home):
    config.load(home=home)
    (home / "asmenybe.md").write_text("Tu esi lakoniškas.", encoding="utf-8")
    assert config.load(home=home).persona == "Tu esi lakoniškas."


def test_nustatymai_is_toml(home):
    config.bootstrap(home)
    (home / "config.toml").write_text(
        'modelis = "claude-sonnet-5"\npastangos = "low"\npaieska = false\n'
        'paieskos_limitas = 2\nsalis = "DE"\nmiestas = "Berlynas"\n',
        encoding="utf-8",
    )
    cfg = config.load(home=home)
    assert (cfg.model, cfg.effort, cfg.search) == ("claude-sonnet-5", "low", False)
    assert (cfg.search_max_uses, cfg.country, cfg.city) == (2, "DE", "Berlynas")


def test_aplinkos_kintamasis_stipresnis(home, monkeypatch):
    config.bootstrap(home)
    (home / "config.toml").write_text('modelis = "claude-sonnet-5"', encoding="utf-8")
    monkeypatch.setenv("ASISTENTAS_MODELIS", "claude-haiku-4-5")
    assert config.load(home=home).model == "claude-haiku-4-5"


def test_blogos_pastangos(home):
    config.bootstrap(home)
    (home / "config.toml").write_text('pastangos = "labai didelės"', encoding="utf-8")
    with pytest.raises(config.ConfigError, match="pastangos"):
        config.load(home=home)


def test_negalima_abieju_domenu_sarasu(home):
    config.bootstrap(home)
    (home / "config.toml").write_text(
        'leidziami_domenai = ["a.lt"]\ndraudziami_domenai = ["b.lt"]', encoding="utf-8"
    )
    with pytest.raises(config.ConfigError, match="ne abu"):
        config.load(home=home)


def test_blogas_domenu_tipas(home):
    config.bootstrap(home)
    (home / "config.toml").write_text("leidziami_domenai = 5", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="sąrašas"):
        config.load(home=home)


def test_sugadintas_toml_paaiskinamas(home):
    config.bootstrap(home)
    (home / "config.toml").write_text("modelis = ", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="sugadintas"):
        config.load(home=home)


def test_zinome_kurie_modeliai_priima_sistemos_zinutes(home):
    cfg = config.load(home=home)
    assert cfg.supports_system_messages is True
    assert cfg.with_(model="claude-sonnet-5").supports_system_messages is False


def test_no_color(home, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert config.load(home=home).color is False


def test_atmintis_ir_failai_is_toml(home):
    config.bootstrap(home)
    (home / "config.toml").write_text(
        'atmintis = false\nfailu_katalogai = ["~/Dokumentai", "/tmp"]\nfailu_dydzio_riba = 1000\n',
        encoding="utf-8",
    )
    cfg = config.load(home=home)
    assert cfg.memory is False
    assert cfg.files_roots == ("~/Dokumentai", "/tmp")
    assert cfg.max_file_bytes == 1000
    assert cfg.memory_dir == home / "atmintis"


def test_be_nustatymu_failu_nemato(home):
    """Kol kelias nenurodytas, asistentas failų nemato — numatytoji kodo elgsena."""
    assert config.Config(home=home).files_roots == ()
    config.bootstrap(home)
    (home / "config.toml").write_text("modelis = \"claude-opus-5\"", encoding="utf-8")
    assert config.load(home=home).files_roots == ()


def test_numatytas_failas_paruostas_asmeniniam_naudojimui(home):
    """Sukurtame config.toml vieta ir dokumentų katalogas jau įrašyti."""
    cfg = config.load(home=home)
    assert cfg.city == "Telšiai" and cfg.region == "Telšių apskritis"
    assert cfg.country == "LT" and cfg.timezone == "Europe/Vilnius"
    # macOS tikras kelias yra ~/Documents, nors Finder rodo „Dokumentai"
    assert cfg.files_roots == ("~/Dokumentai", "~/Documents")


def test_mcp_serveriai(home):
    config.bootstrap(home)
    (home / "config.toml").write_text(
        '[[mcp]]\npavadinimas = "gmail"\nurl = "https://mcp.pvz.lt/gmail"\ntoken_env = "GMAIL_TOKEN"\n'
        '[[mcp]]\npavadinimas = "kalendorius"\nurl = "https://mcp.pvz.lt/cal"\n',
        encoding="utf-8",
    )
    serveriai = config.load(home=home).mcp_servers
    assert [s["pavadinimas"] for s in serveriai] == ["gmail", "kalendorius"]
    assert serveriai[0]["token_env"] == "GMAIL_TOKEN"
    assert serveriai[1]["token_env"] is None


@pytest.mark.parametrize(
    "turinys, klaida",
    [
        ('[[mcp]]\nurl = "https://x.lt"\n', "būtini"),
        ('[[mcp]]\npavadinimas = "a"\n', "būtini"),
        ('[[mcp]]\npavadinimas = "a"\nurl = "http://x.lt"\n', "https"),
        ('[[mcp]]\npavadinimas = "a"\nurl = "https://x.lt"\n[[mcp]]\npavadinimas = "a"\nurl = "https://y.lt"\n', "kartojasi"),
        ('mcp = "gmail"\n', "sąrašas"),
    ],
)
def test_blogi_mcp_nustatymai(home, turinys, klaida):
    config.bootstrap(home)
    (home / "config.toml").write_text(turinys, encoding="utf-8")
    with pytest.raises(config.ConfigError, match=klaida):
        config.load(home=home)


def test_raktai_nelaikomi_nustatymuose(home):
    """Prieigos raktas nurodomas aplinkos kintamojo vardu, ne pačiu raktu."""
    assert "token_env" in config.DEFAULT_CONFIG_TOML
    assert "sk-ant" not in config.DEFAULT_CONFIG_TOML


def test_ollama_nustatymai(home):
    config.bootstrap(home)
    (home / "config.toml").write_text(
        'tiekejas = "ollama"\n[ollama]\nadresas = "https://ollama.com/"\n'
        'modelis = "gpt-oss:120b"\nraktas_env = "MANO_RAKTAS"\n',
        encoding="utf-8",
    )
    cfg = config.load(home=home)
    assert cfg.provider == "ollama"
    assert cfg.ollama.address == "https://ollama.com"      # pabaigos brūkšnys nuimtas
    assert cfg.ollama.model == "gpt-oss:120b"
    assert cfg.ollama.key_env == "MANO_RAKTAS"


def test_ollama_numatytai_lokaliai(home):
    assert config.load(home=home).ollama.address == "http://localhost:11434"


def test_blogas_ollama_adresas(home):
    config.bootstrap(home)
    (home / "config.toml").write_text('[ollama]\nadresas = "localhost:11434"', encoding="utf-8")
    with pytest.raises(config.ConfigError, match="http://"):
        config.load(home=home)


def test_nezinomas_tiekejas_nustatymuose(home):
    config.bootstrap(home)
    (home / "config.toml").write_text('tiekejas = "openai"', encoding="utf-8")
    with pytest.raises(config.ConfigError, match="nežinomas tiekėjas"):
        config.load(home=home)
