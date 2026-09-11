"""Nustatymai: modelis, asmenybė, paieška internete, vieta.

Viskas laikoma ~/.asistentas/ — asmenybę (`asmenybe.md`) gali laisvai
redaguoti: tai ir yra ta vieta, kuri asistentą daro tavo.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

# Modelis pagal nutylėjimą. Pilnas sąrašas: README.md.
DEFAULT_MODEL = "claude-opus-5"

# Paieškos įrankio versija (serverinis įrankis, veikia Anthropic pusėje).
DEFAULT_SEARCH_TOOL = "web_search_20260209"

# Modeliai, priimantys `system` žinutes pokalbio viduryje. Kituose tokia
# žinutė grąžina 400, todėl datą jiems įdedame į sistemos promptą.
MIDCONV_SYSTEM_MODELS = frozenset({
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-fable-5",
    "claude-fable-5-1",
    "claude-mythos-5",
    "claude-mythos-5-1",
})

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

DEFAULT_PERSONA = """\
Tu esi asmeninis asistentas, veikiantis terminale.

Kaip atsakinėti
- Atsakyk ta pačia kalba, kuria į tave kreipiasi.
- Atsakymą pradėk iš karto: be įžangų, be klausimo perpasakojimo, be „geras klausimas".
- Rašyk trumpai ir konkrečiai. Jei užtenka sakinio, neduok pastraipos.
- Terminale nenaudok lentelių; tinka trumpos pastraipos, sąrašai, kodo blokai.
- Jei ko nors nežinai arba nesi tikras, pasakyk tiesiai. Nespėliok.
- Kai klausiama kodo, duok kodą, o ne jo aprašymą.

Paieška internete
- Ieškok, kai atsakymas priklauso nuo šviežios informacijos: naujienos, kainos,
  tvarkaraščiai, versijos, orai, „kas dabar vyksta".
- Neieškok to, ką ir taip žinai — paieška lėtina atsakymą ir kainuoja.
- Kai remiesi rasta informacija, sakinyje pasakyk šaltinį (pavadinimą ar svetainę).
"""

DEFAULT_CONFIG_TOML = """\
# Asmeninio asistento nustatymai. Pakeitimai galioja nuo kito paleidimo.

# Modelis. Galingiausias: "claude-opus-5". Pigesni: "claude-sonnet-5", "claude-haiku-4-5".
modelis = "claude-opus-5"

# Kiek pastangų modelis skiria mąstymui: low, medium, high, xhigh, max.
# Pokalbiams "medium" dažnai nepastebimai skiriasi nuo "high", bet greitesnis ir pigesnis.
pastangos = "high"

# Ar rodyti modelio mąstymą (pilka spalva virš atsakymo).
rodyti_mastyma = false

# Paieška internete
paieska = true
paieskos_limitas = 5        # daugiausia paieškų viename atsakyme
# leidziami_domenai = ["delfi.lt", "lrt.lt"]   # tik šie (arba)
# draudziami_domenai = ["pinterest.com"]        # visi, išskyrus šiuos

# Vieta — pagal ją parenkami paieškos rezultatai ir skaičiuojama vietos data.
salis = "LT"
laiko_juosta = "Europe/Vilnius"
# miestas = "Vilnius"
# regionas = "Vilniaus apskritis"
"""


def _home() -> Path:
    return Path(os.environ.get("ASISTENTAS_HOME", Path.home() / ".asistentas"))


@dataclass(frozen=True)
class Config:
    """Vienas nekintamas nustatymų rinkinys vienam paleidimui."""

    home: Path
    model: str = DEFAULT_MODEL
    effort: str = "high"
    max_tokens: int = 64000
    persona: str = DEFAULT_PERSONA
    show_thinking: bool = False
    search: bool = True
    search_max_uses: int = 5
    search_tool_type: str = DEFAULT_SEARCH_TOOL
    allowed_domains: tuple[str, ...] = ()
    blocked_domains: tuple[str, ...] = ()
    country: str | None = "LT"
    city: str | None = None
    region: str | None = None
    timezone: str | None = "Europe/Vilnius"
    fallbacks: bool = True
    color: bool = True

    @property
    def sessions_dir(self) -> Path:
        return self.home / "sesijos"

    @property
    def persona_path(self) -> Path:
        return self.home / "asmenybe.md"

    @property
    def config_path(self) -> Path:
        return self.home / "config.toml"

    @property
    def history_path(self) -> Path:
        return self.home / "istorija"

    @property
    def supports_system_messages(self) -> bool:
        return self.model in MIDCONV_SYSTEM_MODELS

    def with_(self, **changes) -> "Config":
        return replace(self, **changes)


class ConfigError(Exception):
    """Blogi nustatymai — parodome žmogui suprantamą žinutę."""


def bootstrap(home: Path) -> None:
    """Pirmo paleidimo metu sukuria ~/.asistentas su pavyzdiniais failais."""
    home.mkdir(parents=True, exist_ok=True)
    try:
        home.chmod(0o700)  # pokalbiai yra asmeniniai
    except OSError:
        pass
    (home / "sesijos").mkdir(exist_ok=True)
    persona = home / "asmenybe.md"
    if not persona.exists():
        persona.write_text(DEFAULT_PERSONA, encoding="utf-8")
    cfg = home / "config.toml"
    if not cfg.exists():
        cfg.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} sugadintas: {e}") from e


def _strings(raw, laukas: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ConfigError(f"`{laukas}` turi būti eilučių sąrašas, pvz. [\"lrt.lt\"]")
    return tuple(raw)


def load(home: Path | None = None, *, create: bool = True) -> Config:
    """Perskaito nustatymus. Eiliškumas: numatyta -> config.toml -> aplinkos kintamieji."""
    home = Path(home) if home is not None else _home()
    if create:
        bootstrap(home)

    data = _read_toml(home / "config.toml")
    persona_path = home / "asmenybe.md"
    persona = persona_path.read_text(encoding="utf-8") if persona_path.exists() else DEFAULT_PERSONA

    allowed = _strings(data.get("leidziami_domenai"), "leidziami_domenai")
    blocked = _strings(data.get("draudziami_domenai"), "draudziami_domenai")
    if allowed and blocked:
        raise ConfigError(
            "config.toml: nurodyk arba `leidziami_domenai`, arba `draudziami_domenai`, ne abu."
        )

    cfg = Config(
        home=home,
        model=str(os.environ.get("ASISTENTAS_MODELIS") or data.get("modelis") or DEFAULT_MODEL),
        effort=str(os.environ.get("ASISTENTAS_PASTANGOS") or data.get("pastangos") or "high"),
        persona=persona.strip(),
        show_thinking=bool(data.get("rodyti_mastyma", False)),
        search=bool(data.get("paieska", True)),
        search_max_uses=int(data.get("paieskos_limitas", 5)),
        allowed_domains=allowed,
        blocked_domains=blocked,
        country=data.get("salis", "LT"),
        city=data.get("miestas"),
        region=data.get("regionas"),
        timezone=data.get("laiko_juosta", "Europe/Vilnius"),
        color=os.environ.get("NO_COLOR") is None,
    )
    if cfg.effort not in EFFORT_LEVELS:
        raise ConfigError(
            f"nežinomos pastangos `{cfg.effort}`; galimos: {', '.join(EFFORT_LEVELS)}"
        )
    return cfg
