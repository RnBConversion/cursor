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
