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

# Ilgalaikė atmintis: ką asistentas žino apie tave tarp pokalbių.
# Turinys — paprasti tekstiniai failai ~/.asistentas/atmintis/.
atmintis = true

# Tavo failai. Kol sąrašas tuščias, asistentas jų nemato iš viso.
# Nurodyti katalogai skaitomi (bet niekada nekeičiami ir netrinami).
# failu_katalogai = ["~/Dokumentai", "~/uzrasai"]

# Balso įvestis: /balsas pokalbyje arba `asistentas --balsas`.
# Reikia dviejų dalykų kompiuteryje: įrašymo programos (sox / arecord / ffmpeg)
# ir atpažinimo variklio — paprasčiausia `pip install faster-whisper`.
[balsas]
ijungta = true
kalba = "lt"                 # arba "auto", jei maišai kalbas
# variklis = "auto"          # auto | faster-whisper | whisper.cpp | komanda
# modelis = "large-v3"       # faster-whisper; greitesni ir prastesni: "small", "medium"
# whisper_modelis = "~/modeliai/ggml-large-v3.bin"   # jei naudoji whisper.cpp
# komanda = "mano-stt --lang {kalba} {failas}"       # arba visai savas variklis
# maks_sekundes = 120

# MCP serveriai — Gmail, kalendorius, Slack ir kt.
# Prieigos raktas laikomas aplinkos kintamajame, ne šiame faile.
# [[mcp]]
# pavadinimas = "gmail"
# url = "https://mcp.pavyzdys.lt/gmail"
# token_env = "GMAIL_MCP_TOKEN"
"""


def _home() -> Path:
    return Path(os.environ.get("ASISTENTAS_HOME", Path.home() / ".asistentas"))


@dataclass(frozen=True)
class Voice:
    """Balso įvesties nustatymai (nieko neprivaloma — veikia su tuo, kas įdiegta)."""

    enabled: bool = True
    language: str = "lt"
    recorder: str = "auto"          # auto | rec | sox | arecord | pw-record | ffmpeg
    engine: str = "auto"            # auto | faster-whisper | whisper.cpp | komanda
    whisper_binary: str = "whisper-cli"
    whisper_model: str = ""
    model: str = "large-v3"
    command: str = ""
    max_seconds: int = 120


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
    memory: bool = True
    files_roots: tuple[str, ...] = ()
    max_file_bytes: int = 400_000
    mcp_servers: tuple[dict, ...] = ()
    voice: Voice = field(default_factory=Voice)
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
    def memory_dir(self) -> Path:
        return self.home / "atmintis"

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


def bootstrap(home: Path | str) -> None:
    """Pirmo paleidimo metu sukuria ~/.asistentas su pavyzdiniais failais."""
    home = Path(home)
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


def _voice(raw) -> Voice:
    if raw is None:
        return Voice()
    if not isinstance(raw, dict):
        raise ConfigError("`[balsas]` turi būti lentelė")
    voice = Voice(
        enabled=bool(raw.get("ijungta", True)),
        language=str(raw.get("kalba", "lt")),
        recorder=str(raw.get("irasymas", "auto")),
        engine=str(raw.get("variklis", "auto")),
        whisper_binary=str(raw.get("whisper_binaras", "whisper-cli")),
        whisper_model=str(raw.get("whisper_modelis", "")),
        model=str(raw.get("modelis", "large-v3")),
        command=str(raw.get("komanda", "")),
        max_seconds=int(raw.get("maks_sekundes", 120)),
    )
    if voice.max_seconds < 1:
        raise ConfigError("`maks_sekundes` turi būti bent 1")
    return voice


def _mcp(raw) -> tuple[dict, ...]:
    """MCP serveriai: Gmail, kalendorius ir visa kita, kas kalba MCP kalba."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("`[[mcp]]` turi būti lentelių sąrašas")
    servers, names = [], set()
    for i, entry in enumerate(raw, 1):
        if not isinstance(entry, dict):
            raise ConfigError(f"[[mcp]] #{i}: turi būti lentelė")
        name = str(entry.get("pavadinimas") or "").strip()
        url = str(entry.get("url") or "").strip()
        if not name or not url:
            raise ConfigError(f"[[mcp]] #{i}: būtini `pavadinimas` ir `url`")
        if not url.startswith("https://"):
            raise ConfigError(f"[[mcp]] `{name}`: adresas turi prasidėti https://")
        if name in names:
            raise ConfigError(f"[[mcp]] pavadinimas `{name}` kartojasi")
        names.add(name)
        servers.append({"pavadinimas": name, "url": url, "token_env": entry.get("token_env")})
    return tuple(servers)


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
        memory=bool(data.get("atmintis", True)),
        files_roots=_strings(data.get("failu_katalogai"), "failu_katalogai"),
        max_file_bytes=int(data.get("failu_dydzio_riba", 400_000)),
        mcp_servers=_mcp(data.get("mcp")),
        voice=_voice(data.get("balsas")),
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
