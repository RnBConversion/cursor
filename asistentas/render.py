"""Atsakymo rašymas į terminalą.

Claude atsako markdown'u, o tekstas ateina gabalėliais. Čia paprastas
būsenų automatas, kuris žymes keičia spalvomis nelaukdamas atsakymo pabaigos:
sulaikomi tik tie simboliai, kurie dar gali būti žymės pradžia.

Kai spalvos išjungtos (NO_COLOR arba išvestis nukreipta į failą), tekstas
rašomas toks, koks yra — gaunasi tvarkingas markdown failas.
"""

from __future__ import annotations

import re
import sys

PREFIX_MAX = 4  # kiek simbolių eilutės pradžioje užtenka žymei atpažinti

_HEADER = re.compile(r"^(#{1,6})\s")
_BULLET = re.compile(r"^(\s*)[-*+]\s")
_NUMBER = re.compile(r"^(\s*)(\d+\.)\s")


class Colors:
    """ANSI kodai arba tušti stringai, jei spalvos išjungtos."""

    def __init__(self, enabled: bool = True):
        self.enabled = bool(enabled)

        def c(code: str) -> str:
            return code if self.enabled else ""

        self.reset = c("\033[0m")
        self.bold = c("\033[1m")
        self.dim = c("\033[2m")
        self.red = c("\033[31m")
        self.green = c("\033[32m")
        self.yellow = c("\033[33m")
        self.blue = c("\033[34m")
        self.magenta = c("\033[35m")
        self.cyan = c("\033[36m")

    @classmethod
    def auto(cls, want_color: bool = True, stream=None) -> "Colors":
        stream = stream or sys.stdout
        return cls(bool(want_color) and hasattr(stream, "isatty") and stream.isatty())


class MarkdownStream:
    """Rašo srautu ateinantį markdown tekstą į terminalą."""

    def __init__(self, colors: Colors, out=None, err=None):
        self.c = colors
        self.out = out if out is not None else sys.stdout
        self.err = err if err is not None else sys.stderr
        self._at_line_start = True
        self._prefix = ""          # eilutės pradžios buferis
        self._pending = ""         # sulaikytas simbolis (galima `**` pradžia)
        self._line_style = ""      # stilius, galiojantis iki eilutės galo
        self._fence = False        # ar esame kodo bloke
        self._swallow = False      # praryjame ``` eilutės likutį
        self._bold = False
        self._code = False
        self._started = False      # ar jau ką nors rašėme
        self._nl = True            # ar paskutinis simbolis buvo eilutės pabaiga
        self._thinking = False     # ar dabar rašomas mąstymas

    # ---- viešoji dalis -------------------------------------------------

    def feed(self, text: str) -> None:
        if not text:
            return
        self.thinking_end()  # atsakymas visada pradedamas nauja eilute
        if not self.c.enabled:
            self._text(text)
            return
        for ch in text:
            self._char(ch)

    def note(self, text: str, color: str | None = None) -> None:
        """Tarnybinė eilutė (pvz. „ieškau internete"), atskirta nuo atsakymo."""
        self.thinking_end()
        if self._prefix:
            self._decide()
        if not self.c.enabled:
            # Nukreipiant išvestį į failą pastabos neturi terštis su atsakymu.
            self.err.write(text + "\n")
            self.err.flush()
            return
        self._break_line()
        self._style(color or self.c.dim)
        self._text(text)
        self._style(self.c.reset)
        self._text("\n")
        self._at_line_start = True

    def thinking(self, text: str) -> None:
        """Modelio mąstymas — blanki eilutė virš atsakymo (jei įjungta)."""
        if not text:
            return
        if not self.c.enabled:
            self.err.write(text)
            self.err.flush()
            return
        if not self._thinking:
            self._break_line()
            self._thinking = True
            self._style(self.c.dim)
        self._text(text)

    def thinking_end(self) -> None:
        if not self._thinking:
            return
        self._thinking = False
        if not self.c.enabled:
            self.err.write("\n")
            self.err.flush()
            return
        self._style(self.c.reset)
        if not self._nl:
            self._text("\n")

    def close(self) -> None:
        """Užbaigia atsakymą: išvalo buferius ir palieka švarią eilutę."""
        self.thinking_end()
        if self._prefix:
            self._decide()
        if self._pending:
            self._text(self._pending)
            self._pending = ""
        self._style(self.c.reset)
        if self._started and not self._nl:
            self._text("\n")
        self._reset_state()

    # ---- vidinė virtuvė ------------------------------------------------

    def _reset_state(self) -> None:
        self._at_line_start = True
        self._prefix = ""
        self._pending = ""
        self._line_style = ""
        self._fence = False
        self._swallow = False
        self._bold = False
        self._code = False

    def _style(self, codes: str) -> None:
        if codes:
            self.out.write(codes)

    def _text(self, s: str) -> None:
        if not s:
            return
        self.out.write(s)
        self.out.flush()
        self._started = True
        self._nl = s.endswith("\n")

    def _restyle(self) -> None:
        codes = self.c.reset + self._line_style
        if self._bold:
            codes += self.c.bold
        if self._code:
            codes += self.c.yellow
        self._style(codes)

    def _break_line(self) -> None:
        if self._started and not self._nl:
            self._style(self.c.reset)
            self._text("\n")

    def _char(self, ch: str) -> None:
        if self._swallow:  # ``` eilutės likutis (kalbos pavadinimas)
            if ch == "\n":
                self._swallow = False
                self._at_line_start = True
            return

        if self._at_line_start:
            if ch == "\n":
                self._decide()
                if self._swallow:  # tai buvo vien ``` — eilutės nerašome
                    self._swallow = False
                    self._at_line_start = True
                    return
                self._newline()
                return
            self._prefix += ch
            if len(self._prefix) >= PREFIX_MAX:
                self._decide()
            return

        self._inline(ch)

    def _decide(self) -> None:
        """Nusprendžia, kas per eilutė, ir išrašo sukauptą jos pradžią."""
        prefix, self._prefix = self._prefix, ""
        self._at_line_start = False

        if self._fence:
            if prefix.startswith("```"):
                self._fence = False
                self._swallow = True
                return
            self._style(self.c.dim)
            self._text("│ ")
            self._line_style = self.c.green
            self._restyle()
            for ch in prefix:
                self._text(ch)
            return

        if prefix.startswith("```"):
            self._fence = True
            self._swallow = True
            return

        m = _HEADER.match(prefix)
        if m:
            self._line_style = self.c.bold + self.c.cyan
            self._restyle()
            self._rest(prefix[m.end():])
            return

        m = _BULLET.match(prefix)
        if m:
            self._style(self.c.cyan)
            self._text(m.group(1) + "• ")
            self._restyle()
            self._rest(prefix[m.end():])
            return

        m = _NUMBER.match(prefix)
        if m:
            self._style(self.c.cyan)
            self._text(m.group(1) + m.group(2) + " ")
            self._restyle()
            self._rest(prefix[m.end():])
            return

        if prefix.startswith("> "):
            self._line_style = self.c.dim
            self._restyle()
            self._text("│ ")
            self._rest(prefix[2:])
            return

        self._restyle()
        self._rest(prefix)

    def _rest(self, s: str) -> None:
        for ch in s:
            self._inline(ch)

    def _inline(self, ch: str) -> None:
        if self._fence:
            if ch == "\n":
                self._newline()
            else:
                self._text(ch)
            return

        if self._pending == "*":
            self._pending = ""
            if ch == "*":
                self._bold = not self._bold
                self._restyle()
                return
            self._text("*")  # pavienė žvaigždutė — paprastas simbolis

        if ch == "\n":
            self._newline()
            return
        if ch == "*":
            self._pending = "*"
            return
        if ch == "`":
            self._code = not self._code
            self._restyle()
            return
        self._text(ch)

    def _newline(self) -> None:
        if self._pending:
            self._text(self._pending)
            self._pending = ""
        self._style(self.c.reset)
        self._text("\n")
        self._line_style = ""
        self._at_line_start = True
