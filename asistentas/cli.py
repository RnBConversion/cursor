"""Komandinė eilutė: pokalbis terminale ir vienkartiniai klausimai.

    asistentas                     # pokalbis
    asistentas "kiek kainuoja X"   # vienas klausimas ir atgal į terminalą
    echo tekstas | asistentas "santrauka"
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from asistentas import __version__, config, lt
from asistentas.agent import Assistant, Turn
from asistentas.pricing import format_cost
from asistentas.render import Colors, MarkdownStream
from asistentas.session import Session, Store

PROMPT = "tu ▸ "

HELP = """\
komandos
  /nauja                  pradėti naują pokalbį
  /sesijos                paskutiniai pokalbiai
  /tesk [id]              tęsti pokalbį (be id — paskutinį)
  /istorija               parodyti šio pokalbio eigą
  /kaina                  kiek iki šiol kainavo ši sesija
  /tiekejas [anthropic|ollama]  kas galvoja: Claude ar tavo Mac'as
  /modelis [pavadinimas]  parodyti arba pakeisti modelį
  /pastangos [low|medium|high|xhigh|max]
  /paieska [on|off]       paieška internete
  /mastymas [on|off]      rodyti modelio mąstymą
  /balsas                 užduoti klausimą balsu
  /atmintis [viskas|pamirsk]   ką asistentas apie tave įsiminė
  /failai                 kuriuos katalogus jis mato
  /asmenybe               kur redaguoti asistento charakterį
  /pagalba                šis sąrašas
  /iseiti                 išeiti (arba Ctrl+D)

Ctrl+C nutraukia atsakymą, bet neišjungia asistento."""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="asistentas",
        description="Asmeninis AI asistentas terminale.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Be klausimo paleidžia pokalbį. Nustatymai: ~/.asistentas/config.toml",
    )
    p.add_argument("klausimas", nargs="*", help="klausimas (jei nenurodyta — pokalbis)")
    p.add_argument("--modelis", help="modelis, pvz. claude-opus-5")
    p.add_argument("--tiekejas", choices=("anthropic", "ollama"), help="kas galvoja")
    p.add_argument("--pastangos", choices=config.EFFORT_LEVELS, help="mąstymo gylis")
    p.add_argument("--be-paieskos", action="store_true", help="neieškoti internete")
    p.add_argument("--mastymas", action="store_true", help="rodyti modelio mąstymą")
    p.add_argument("--balsas", action="store_true", help="klausti balsu, o ne raštu")
    p.add_argument("--tesk", nargs="?", const="", metavar="ID", help="tęsti pokalbį")
    p.add_argument("--kaina", action="store_true", help="visada rodyti kainą")
    p.add_argument("--versija", action="version", version=f"asistentas {__version__}")
    return p


class App:
    def __init__(
        self,
        cfg: config.Config,
        colors: Colors,
        show_footer: bool,
        voice_mode: bool = False,
    ):
        self.cfg = cfg
        self.colors = colors
        self.store = Store(cfg.sessions_dir)
        self.session = Session(model=cfg.model)
        self.show_footer = show_footer
        self.voice_mode = voice_mode
        self._client = None
        self._voice_input = None
        self._pending = ""      # tekstas, kuris atsiras įvesties eilutėje

    # ---- klausimas -----------------------------------------------------

    def ask(self, question: str) -> int:
        assistant = Assistant(self.cfg, self.session, client=self._client)
        renderer = MarkdownStream(self.colors, out=sys.stdout, err=sys.stderr)
        try:
            turn = assistant.ask(question, renderer)
        except KeyboardInterrupt:
            self.store.save(self.session)
            self._dim("(nutraukta)")
            return 130
        except Exception as e:  # API klaidos neturi griauti pokalbio
            self._error(friendly_error(e))
            return 1
        finally:
            self._client = assistant.cached_client  # klientą naudojame pakartotinai

        self.store.save(self.session)
        self._footer(turn)
        if turn.refusal:
            self._dim(f"(modelis atsisakė: {turn.refusal})")
        for note in turn.notes:
            self._dim(f"({note})")
        return 0

    # ---- pokalbis ------------------------------------------------------

    def repl(self) -> int:
        self._setup_readline()
        c = self.colors
        paieska = self.cfg.search and self.cfg.provider != "ollama"
        print(
            f"{c.dim}  asistentas · {self.model_label()} · paieška: "
            f"{'taip' if paieska else 'ne'}{c.reset}"
        )
        print(f"{c.dim}  /pagalba — komandos · Ctrl+D — išeiti{c.reset}\n")

        while True:
            if self.voice_mode and not self._pending:
                self._pending = self.voice_capture()
            try:
                line = self._read_line()
            except KeyboardInterrupt:
                print()
                continue
            except EOFError:
                print()
                return self._bye()

            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                if self._command(line) is False:
                    return self._bye()
                continue
            print()
            self.ask(line)
            print()

    def _read_line(self) -> str:
        """Įvesties eilutė. Balsu atpažintas tekstas įrašomas į ją iš anksto,
        kad prieš siunčiant galėtum pataisyti neteisingai išgirstą žodį."""
        prefill, self._pending = self._pending, ""
        prompt = f"{self.colors.bold}{self.colors.cyan}{PROMPT}{self.colors.reset}"
        if not prefill:
            return input(prompt)
        try:
            import readline

            readline.set_startup_hook(lambda: readline.insert_text(prefill))
        except (ImportError, AttributeError, OSError):
            # Windows readline neturi, macOS libedit gali neturėti kabliuko.
            # Tada tekstą tiesiog parodome: Enter jį patvirtina.
            self._dim(prefill)
            return input(prompt) or prefill
        try:
            return input(prompt)
        finally:
            readline.set_startup_hook()

    # ---- balsas --------------------------------------------------------

    def voice(self):
        if self._voice_input is None:
            from asistentas.voice import VoiceInput

            self._voice_input = VoiceInput(self.cfg.voice)
        return self._voice_input

    def voice_capture(self) -> str:
        """Įrašo klausimą balsu ir grąžina atpažintą tekstą (arba tuščią)."""
        from asistentas.voice import VoiceError, wait_for_enter

        if not self.cfg.voice.enabled:
            self._dim("balso įvestis išjungta (config.toml: [balsas] ijungta = false)")
            return ""
        voice = self.voice()
        if not voice.ready:
            self._error("balso įvesčiai trūksta:")
            for problem in voice.problems():
                self._error(f"  • {problem}")
            return ""
        try:
            text = voice.capture(
                wait=lambda: wait_for_enter(self.cfg.voice.max_seconds),
                on_start=lambda: self._dim("🎤 kalbėk… (Enter — baigti, Ctrl+C — atšaukti)"),
                on_transcribe=lambda: self._dim("⏳ atpažįstu…"),
            )
        except KeyboardInterrupt:
            print()
            self._dim("(atšaukta)")
            return ""
        except VoiceError as e:
            self._error(str(e))
            return ""
        if not text:
            self._dim("negirdėjau nieko")
        return text

    def _bye(self) -> int:
        if self.session.messages:
            self.store.save(self.session)
            self._dim(f"pokalbis išsaugotas: {self.session.id}")
        return 0

    def _setup_readline(self) -> None:
        try:
            import readline  # rodyklės aukštyn/žemyn, Ctrl+R
        except ImportError:
            return
        try:
            readline.read_history_file(self.cfg.history_path)
        except (OSError, ValueError):
            pass
        readline.set_history_length(1000)
        import atexit

        atexit.register(_save_history, readline, str(self.cfg.history_path))

    # ---- komandos ------------------------------------------------------

    def _command(self, line: str) -> bool | None:
        parts = line[1:].split()
        name = parts[0].lower() if parts else ""
        arg = " ".join(parts[1:]).strip()

        if name in ("iseiti", "išeiti", "exit", "quit", "q"):
            return False
        if name in ("pagalba", "help", "?"):
            print(HELP)
        elif name == "nauja":
            if self.session.messages:
                self.store.save(self.session)
            self.session = Session(model=self.cfg.model)
            self._dim("naujas pokalbis")
        elif name == "sesijos":
            self._list_sessions()
        elif name == "tesk":
            self._resume(arg)
        elif name == "istorija":
            self._history()
        elif name == "kaina":
            self._cost()
        elif name == "tiekejas":
            self._provider(arg)
        elif name == "modelis":
            if arg:
                if self.cfg.provider == "ollama":
                    self.cfg = self.cfg.with_(ollama=replace(self.cfg.ollama, model=arg))
                else:
                    self.cfg = self.cfg.with_(model=arg)
                self.session.model = arg
                self._dim(f"modelis: {arg}")
            else:
                self._dim(f"modelis: {self.model_label()}")
        elif name == "pastangos":
            if arg in config.EFFORT_LEVELS:
                self.cfg = self.cfg.with_(effort=arg)
                self._dim(f"pastangos: {arg}")
            elif arg:
                self._error(f"galimos: {', '.join(config.EFFORT_LEVELS)}")
            else:
                self._dim(f"pastangos: {self.cfg.effort}")
        elif name == "paieska":
            self._toggle("search", arg, "paieška")
        elif name == "mastymas":
            self._toggle("show_thinking", arg, "mąstymas")
        elif name == "balsas":
            self._pending = self.voice_capture()
        elif name == "atmintis":
            self._memory(arg)
        elif name == "failai":
            self._files()
        elif name == "asmenybe":
            self._dim(f"redaguok: {self.cfg.persona_path}")
        else:
            self._error(f"nežinoma komanda /{name} — /pagalba")
        return None

    def _toggle(self, field: str, arg: str, label: str) -> None:
        current = getattr(self.cfg, field)
        if arg in ("on", "taip", "1"):
            current = True
        elif arg in ("off", "ne", "0"):
            current = False
        elif arg:
            self._error("naudok on arba off")
            return
        else:
            current = not current
        self.cfg = self.cfg.with_(**{field: current})
        self._dim(f"{label}: {'įjungta' if current else 'išjungta'}")

    def _provider(self, arg: str) -> None:
        """Perjungia variklį pokalbio viduryje — istorija lieka ta pati."""
        if not arg:
            self._dim(f"tiekėjas: {self.model_label()}")
            return
        if arg not in ("anthropic", "ollama"):
            self._error("galimi: anthropic, ollama")
            return
        self.cfg = self.cfg.with_(provider=arg)
        self._client = None       # kitam varikliui reikia kito kliento
        self._dim(f"tiekėjas: {self.model_label()}")
        if arg == "ollama":
            self._dim("paieškos internete ir MCP šiuo varikliu nėra")

    def model_label(self) -> str:
        if self.cfg.provider != "ollama":
            return self.cfg.model
        vieta = "lokaliai" if self.local_ollama else "debesyje"
        return f"ollama {self.cfg.ollama.model} ({vieta})"

    @property
    def local_ollama(self) -> bool:
        address = self.cfg.ollama.address
        return "localhost" in address or "127.0.0.1" in address

    def cost_text(self, usage) -> str:
        """Lokaliai sukamas modelis nieko nekainuoja — nerodome $0.00."""
        if self.cfg.provider == "ollama":
            return "lokaliai" if self.local_ollama else "debesų kreditai"
        return format_cost(usage.cost(self.cfg.model))

    def _memory(self, arg: str) -> None:
        """Atmintis turi būti matoma ir ištrinama — tai tavo duomenys."""
        if not self.cfg.memory:
            self._dim("atmintis išjungta (config.toml: atmintis = false)")
            return
        from asistentas.memory import MemoryStore

        store = MemoryStore(self.cfg.memory_dir)
        files = store.files()

        if arg == "pamirsk":
            if not files:
                self._dim("atmintis ir taip tuščia")
                return
            if not self._confirm(f"ištrinti visą atmintį ({lt.count(len(files), 'failą', 'failus', 'failų')})?"):
                self._dim("palikta")
                return
            import shutil

            shutil.rmtree(self.cfg.memory_dir, ignore_errors=True)
            self._dim("atmintis ištrinta")
            return

        if not files:
            self._dim("atmintis tuščia — asistentas dar nieko apie tave neįsirašė")
            return
        if arg == "viskas":
            print(store.read_all(limit=20000))
            return
        for name, size in files:
            print(f"{self.colors.dim}  {name} ({size} B){self.colors.reset}")
        self._dim("„/atmintis viskas" + '" — turinys, „/atmintis pamirsk" — ištrinti')

    def _files(self) -> None:
        from asistentas.files import FileTools

        tools = FileTools(self.cfg.files_roots, self.cfg.max_file_bytes)
        if not tools.configured:
            self._dim("failų katalogai nenurodyti (config.toml: failu_katalogai)")
            return
        for path in tools.configured:
            ok = path.expanduser().is_dir()
            zyme = "" if ok else "  (nerastas)"
            print(f"{self.colors.dim}  {path}{zyme}{self.colors.reset}")
        self._dim("skaitoma tik — asistentas failų nekeičia")

    def _confirm(self, question: str) -> bool:
        try:
            return input(f"{question} (taip/ne) ").strip().lower() in ("taip", "t", "yes", "y")
        except (EOFError, KeyboardInterrupt):
            print()
            return False

    def _list_sessions(self) -> None:
        sessions = self.store.list(limit=10)
        if not sessions:
            self._dim("pokalbių dar nėra")
            return
        c = self.colors
        for s in sessions:
            mark = "•" if s.id == self.session.id else " "
            print(
                f"{c.dim}{mark} {s.id}{c.reset}  {s.title[:48]}"
                f"{c.dim}  ({s.turns} kl.){c.reset}"
            )

    def _resume(self, session_id: str) -> None:
        try:
            if session_id:
                loaded = self.store.load(session_id)
            else:
                loaded = self.store.latest()
                if loaded is None:
                    self._dim("nėra ką tęsti")
                    return
        except (FileNotFoundError, ValueError) as e:
            self._error(str(e))
            return
        if self.session.messages and self.session.id != loaded.id:
            self.store.save(self.session)
        self.session = loaded
        self._dim(f"tęsiame: {loaded.id} — {loaded.title[:48]} ({loaded.turns} kl.)")

    def _history(self) -> None:
        c = self.colors
        if not self.session.messages:
            self._dim("pokalbis tuščias")
            return
        for msg in self.session.messages:
            role = msg.get("role")
            text = _message_text(msg)
            if not text:
                continue
            label = {"user": "tu", "assistant": "ai", "system": "sys"}.get(role, role)
            print(f"{c.dim}{label:>3} ▸{c.reset} {text[:200]}")

    def _cost(self) -> None:
        u = self.session.usage
        self._dim(
            f"{self.cost_text(u)} · {lt.tokens(u.total_tokens)} · "
            f"{lt.searches(u.searches)} · {lt.questions(self.session.turns)}"
        )

    # ---- išvestis ------------------------------------------------------

    def _footer(self, turn: Turn) -> None:
        if not self.show_footer:
            return
        c = self.colors
        for i, (title, url) in enumerate(turn.sources, 1):
            print(f"{c.dim}  {i}. {title[:60]} — {url}{c.reset}")
        u = turn.usage
        bits = [self.cost_text(u), f"{lt.number(u.total_tokens)} žet."]
        if u.searches:
            bits.append(lt.searches(u.searches))
        if u.cache_read_tokens:
            bits.append("talpykla")
        print(f"{c.dim}  {' · '.join(bits)}{c.reset}")

    def _dim(self, text: str) -> None:
        print(f"{self.colors.dim}{text}{self.colors.reset}")

    def _error(self, text: str) -> None:
        print(f"{self.colors.red}{text}{self.colors.reset}", file=sys.stderr)


def _save_history(readline, path: str) -> None:
    try:
        readline.write_history_file(path)
    except OSError:
        pass


def _message_text(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return " ".join(parts).strip()


def friendly_error(e: Exception) -> str:
    """API klaidos lietuviškai — be pėdsakų (traceback) vartotojui."""
    name = type(e).__name__
    status = getattr(e, "status_code", None)
    message = str(getattr(e, "message", None) or e)
    lower = message.lower()

    # Rakto nebuvimas paaiškėja arba kuriant klientą, arba iš 401 atsakymo.
    if (
        name == "AuthenticationError"
        or status == 401
        or "api_key" in lower
        or "authentication method" in lower
    ):
        return (
            "Nėra galiojančio API rakto.\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...\n"
            "  raktą gausi čia: https://console.anthropic.com/settings/keys"
        )
    if name == "PermissionDeniedError" or status == 403:
        return "Raktas neturi teisių šiam veiksmui."
    if name == "NotFoundError" or status == 404:
        return "Tokio modelio nėra — patikrink /modelis."
    if name == "RateLimitError" or status == 429:
        return "Per daug užklausų. Palauk minutę ir bandyk vėl."
    if name == "APIConnectionError" or name == "APITimeoutError":
        return "Nepavyko pasiekti API. Patikrink interneto ryšį."
    if isinstance(status, int) and status >= 500:
        return f"Anthropic serverio klaida ({status}). Bandyk vėliau."
    return f"Klaida: {message}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        cfg = config.load()
    except config.ConfigError as e:
        print(f"Nustatymų klaida: {e}", file=sys.stderr)
        return 2

    if args.tiekejas:
        cfg = cfg.with_(provider=args.tiekejas)
    if args.modelis:
        cfg = cfg.with_(
            ollama=replace(cfg.ollama, model=args.modelis)
            if cfg.provider == "ollama"
            else cfg.ollama,
            model=args.modelis if cfg.provider != "ollama" else cfg.model,
        )
    if args.pastangos:
        cfg = cfg.with_(effort=args.pastangos)
    if args.be_paieskos:
        cfg = cfg.with_(search=False)
    if args.mastymas:
        cfg = cfg.with_(show_thinking=True)

    colors = Colors.auto(cfg.color)
    question = " ".join(args.klausimas).strip()

    # Tekstas iš dūdelės (pipe) prisegamas prie klausimo.
    piped = ""
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
    if piped:
        question = f"{question}\n\n{piped}" if question else piped

    app = App(
        cfg,
        colors,
        show_footer=colors.enabled or args.kaina,
        voice_mode=args.balsas,
    )

    if args.tesk is not None:
        app._resume(args.tesk)

    if args.balsas and not question:
        if not sys.stdin.isatty():
            print("Balsui reikia terminalo.", file=sys.stderr)
            return 2
        question = app.voice_capture()
        if not question:
            return 1
        app._dim(f"▸ {question}")

    if question:
        return app.ask(question)
    if not sys.stdin.isatty():
        print("Nėra klausimo.", file=sys.stderr)
        return 2
    return app.repl()
