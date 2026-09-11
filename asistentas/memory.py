"""Ilgalaikė atmintis: ką asistentas žino apie tave tarp pokalbių.

Naudojamas Anthropic atminties įrankis (`memory_20250818`): modelis pats
rašo ir skaito failus, o mes juos laikome ~/.asistentas/atmintis/.
Visi keliai ateina iš modelio, todėl kiekvienas tikrinamas — už atminties
katalogo ribų neišeinama jokiu būdu.
"""

from __future__ import annotations

import shutil
from pathlib import Path, PurePosixPath

from anthropic.lib.tools import BetaAbstractMemoryTool

# Įrankio sutartis: visi keliai prasideda /memories
ROOT_PREFIX = "memories"
MAX_VIEW_BYTES = 100_000


class MemoryError(Exception):
    """Netinkamas kelias arba neįmanomas veiksmas — grąžiname modeliui."""


class MemoryStore(BetaAbstractMemoryTool):
    """Atmintis paprastuose tekstiniuose failuose — juos gali skaityti ir pats."""

    def __init__(self, root: Path, cache_control=None):
        super().__init__(cache_control=cache_control)
        self.root = Path(root)

    # ---- saugumas ------------------------------------------------------

    def _resolve(self, path: str) -> Path:
        """Modelio kelias -> tikras failas. Išeiti iš katalogo neleidžiama."""
        if not isinstance(path, str) or not path.strip():
            raise MemoryError("kelias negali būti tuščias")
        pure = PurePosixPath(path)
        parts = pure.parts
        if not pure.is_absolute() or len(parts) < 2 or parts[1] != ROOT_PREFIX:
            raise MemoryError(f"kelias turi prasidėti /{ROOT_PREFIX}")
        root = self.root.resolve()
        target = (root / Path(*parts[2:])).resolve()
        if target != root and not target.is_relative_to(root):
            raise MemoryError("kelias išeina už atminties ribų")
        return target

    def _display(self, target: Path) -> str:
        root = self.root.resolve()
        if target == root:
            return f"/{ROOT_PREFIX}"
        return f"/{ROOT_PREFIX}/{target.relative_to(root).as_posix()}"

    # ---- įrankio komandos ---------------------------------------------

    def view(self, command) -> str:
        target = self._resolve(command.path)
        # Pirmą kartą atminties katalogo dar nėra — tai ne klaida, o tuščia atmintis.
        if target.is_dir() or target == self.root.resolve():
            return self._list_dir(target)
        if not target.exists():
            raise MemoryError(f"{self._display(target)} nerastas")
        text = target.read_text(encoding="utf-8", errors="replace")[:MAX_VIEW_BYTES]
        lines = text.splitlines()
        start, end = 1, len(lines)
        view_range = getattr(command, "view_range", None)
        if view_range:
            start = max(1, int(view_range[0]))
            end = len(lines) if int(view_range[1]) == -1 else min(len(lines), int(view_range[1]))
        numbered = [f"{i:>4}: {lines[i - 1]}" for i in range(start, end + 1)]
        return "\n".join(numbered) if numbered else "(tuščias failas)"

    def _list_dir(self, target: Path) -> str:
        if not target.exists():
            return "(atmintis tuščia)"
        entries = sorted(target.rglob("*"))
        if not entries:
            return "(atmintis tuščia)"
        rows = []
        for entry in entries:
            name = self._display(entry)
            rows.append(f"{name}/" if entry.is_dir() else f"{name} ({entry.stat().st_size} B)")
        return "\n".join(rows)

    def create(self, command) -> str:
        target = self._resolve(command.path)
        if target.is_dir():
            raise MemoryError(f"{self._display(target)} yra katalogas")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(command.file_text, encoding="utf-8")
        return f"įrašyta: {self._display(target)}"

    def str_replace(self, command) -> str:
        target = self._resolve(command.path)
        if not target.is_file():
            raise MemoryError(f"{self._display(target)} nerastas")
        text = target.read_text(encoding="utf-8")
        found = text.count(command.old_str)
        if found == 0:
            raise MemoryError("tokio teksto faile nėra")
        if found > 1:
            raise MemoryError(f"tekstas kartojasi {found} kartus — nurodyk tiksliau")
        target.write_text(text.replace(command.old_str, command.new_str, 1), encoding="utf-8")
        return f"pakeista: {self._display(target)}"

    def insert(self, command) -> str:
        target = self._resolve(command.path)
        if not target.is_file():
            raise MemoryError(f"{self._display(target)} nerastas")
        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        index = int(command.insert_line)
        if not 0 <= index <= len(lines):
            raise MemoryError(f"eilutė {index} už ribų (faile {len(lines)})")
        text = command.insert_text
        if not text.endswith("\n"):
            text += "\n"
        lines.insert(index, text)
        target.write_text("".join(lines), encoding="utf-8")
        return f"įterpta: {self._display(target)}:{index}"

    def delete(self, command) -> str:
        target = self._resolve(command.path)
        if target == self.root.resolve():
            raise MemoryError("viso atminties katalogo ištrinti negalima")
        if not target.exists():
            raise MemoryError(f"{self._display(target)} nerastas")
        name = self._display(target)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return f"ištrinta: {name}"

    def rename(self, command) -> str:
        source = self._resolve(command.old_path)
        target = self._resolve(command.new_path)
        if not source.exists():
            raise MemoryError(f"{self._display(source)} nerastas")
        if target.exists():
            raise MemoryError(f"{self._display(target)} jau yra")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        return f"pervadinta: {self._display(source)} -> {self._display(target)}"

    # ---- žmogui --------------------------------------------------------

    def files(self) -> list[tuple[str, int]]:
        """Kas šiuo metu atmintyje — komandai /atmintis."""
        root = self.root.resolve()
        if not root.exists():
            return []
        return [
            (self._display(p), p.stat().st_size)
            for p in sorted(root.rglob("*"))
            if p.is_file()
        ]

    def read_all(self, limit: int = 4000) -> str:
        """Visas atminties turinys — kad galėtum jį perskaityti pats."""
        parts = []
        for name, _ in self.files():
            path = self._resolve(name)
            parts.append(f"# {name}\n{path.read_text(encoding='utf-8', errors='replace')}")
        text = "\n\n".join(parts)
        return text[:limit] + ("\n…" if len(text) > limit else "")
