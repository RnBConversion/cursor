"""Komandinė eilutė: pokalbis terminale ir vienkartiniai klausimai.

    asistentas                     # pokalbis
    asistentas "kiek kainuoja X"   # vienas klausimas ir atgal į terminalą
    echo tekstas | asistentas "santrauka"
"""

from __future__ import annotations

import argparse
import sys

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
  /modelis [pavadinimas]  parodyti arba pakeisti modelį
  /pastangos [low|medium|high|xhigh|max]
  /paieska [on|off]       paieška internete
  /mastymas [on|off]      rodyti modelio mąstymą
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
    p.add_argument("--pastangos", choices=config.EFFORT_LEVELS, help="mąstymo gylis")
    p.add_argument("--be-paieskos", action="store_true", help="neieškoti internete")
    p.add_argument("--mastymas", action="store_true", help="rodyti modelio mąstymą")
    p.add_argument("--tesk", nargs="?", const="", metavar="ID", help="tęsti pokalbį")
    p.add_argument("--kaina", action="store_true", help="visada rodyti kainą")
    p.add_argument("--versija", action="version", version=f"asistentas {__version__}")
    return p


class App:
    def __init__(self, cfg: config.Config, colors: Colors, show_footer: bool):
        self.cfg = cfg
        self.colors = colors
        self.store = Store(cfg.sessions_dir)
        self.session = Session(model=cfg.model)
        self.show_footer = show_footer
        self._client = None

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
        print(
            f"{c.dim}  asistentas · {self.cfg.model} · paieška: "
            f"{'taip' if self.cfg.search else 'ne'}{c.reset}"
        )
        print(f"{c.dim}  /pagalba — komandos · Ctrl+D — išeiti{c.reset}\n")

        while True:
            try:
                line = input(f"{c.bold}{c.cyan}{PROMPT}{c.reset}")
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
        elif name == "modelis":
            if arg:
                self.cfg = self.cfg.with_(model=arg)
                self.session.model = arg
                self._dim(f"modelis: {arg}")
            else:
                self._dim(f"modelis: {self.cfg.model}")
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
            f"{format_cost(u.cost(self.cfg.model))} · {lt.tokens(u.total_tokens)} · "
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
        bits = [format_cost(u.cost(self.cfg.model)), f"{lt.number(u.total_tokens)} žet."]
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

    if args.modelis:
        cfg = cfg.with_(model=args.modelis)
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

    app = App(cfg, colors, show_footer=colors.enabled or args.kaina)

    if args.tesk is not None:
        app._resume(args.tesk)

    if question:
        return app.ask(question)
    if not sys.stdin.isatty():
        print("Nėra klausimo.", file=sys.stderr)
        return 2
    return app.repl()
