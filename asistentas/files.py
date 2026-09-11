"""Darbas su tavo failais: paieška ir skaitymas nurodytuose kataloguose.

Sąmoningai tik skaitymas. Asistentas gali rasti ir perskaityti tavo užrašus,
bet nieko neperrašo ir neištrina — failų keitimas yra kitokio pasitikėjimo
lygis, o ne dar vienas nustatymas.

Kelius siūlo modelis, todėl kiekvienas tikrinamas pagal leistinų katalogų
sąrašą (`failu_katalogai` nustatymuose). Numatytai sąrašas tuščias — kol
nenurodai, kur žiūrėti, šių įrankių iš viso nėra.
"""

from __future__ import annotations

import os
from pathlib import Path

MAX_FILE_BYTES = 400_000      # didesnių failų neskaitome
MAX_READ_LINES = 400          # kiek eilučių grąžiname per kartą
MAX_MATCHES = 40              # kiek paieškos atitikmenų rodome
MAX_SCAN_FILES = 5000         # kiek failų peržiūrime per paiešką
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".cache", ".Trash", "dist", "build",
}


class FileToolError(Exception):
    """Klaida, kurią grąžiname modeliui kaip įrankio rezultatą."""


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return b"\0" in f.read(2048)
    except OSError:
        return True


class FileTools:
    """Trys įrankiai: rasti failus, ieškoti juose, perskaityti."""

    def __init__(self, roots, max_file_bytes: int = MAX_FILE_BYTES):
        self.configured = [Path(r).expanduser() for r in roots]
        # Nesamas katalogas (pvz. neprijungtas diskas) tyliai praleidžiamas —
        # dėl vienos klaidos nustatymuose asistentas neturi nustoti veikti.
        self.roots = [p.resolve() for p in self.configured if p.is_dir()]
        self.max_file_bytes = max_file_bytes

    @property
    def enabled(self) -> bool:
        return bool(self.roots)

    # ---- įrankių aprašai modeliui --------------------------------------

    def definitions(self) -> list[dict]:
        if not self.enabled:
            return []
        where = ", ".join(str(r) for r in self.roots)
        return [
            {
                "name": "list_files",
                "description": (
                    "List the user's files. Allowed directories: "
                    f"{where}. Use this first to see what exists."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dir": {"type": "string", "description": "Subdirectory to list."},
                        "pattern": {
                            "type": "string",
                            "description": "Glob filter, e.g. '*.md'.",
                        },
                    },
                },
            },
            {
                "name": "search_files",
                "description": (
                    "Search the text inside the user's files (case-insensitive). "
                    f"Allowed directories: {where}. Returns matching lines with paths."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Text to look for."},
                        "dir": {"type": "string", "description": "Limit to this subdirectory."},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "read_file",
                "description": (
                    "Read one of the user's files. "
                    f"Allowed directories: {where}. Long files come back in pages."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File to read."},
                        "start_line": {"type": "integer", "description": "First line (1-based)."},
                    },
                    "required": ["path"],
                },
            },
        ]

    def handles(self, name: str) -> bool:
        return self.enabled and name in {"list_files", "search_files", "read_file"}

    def describe(self, name: str, args: dict) -> str:
        """Ką parodyti vartotojui, kol įrankis dirba."""
        if name == "read_file":
            return f"📄 skaitau: {args.get('path', '')}"
        if name == "search_files":
            return f"📂 ieškau failuose: {args.get('query', '')}"
        return "📂 žiūriu, kokie failai yra"

    def call(self, name: str, args: dict) -> str:
        if name == "list_files":
            return self.list_files(args.get("dir"), args.get("pattern"))
        if name == "search_files":
            return self.search_files(args.get("query", ""), args.get("dir"))
        if name == "read_file":
            return self.read_file(args.get("path", ""), args.get("start_line"))
        raise FileToolError(f"nežinomas įrankis: {name}")

    # ---- saugumas ------------------------------------------------------

    def _resolve(self, path: str | None, *, must_exist: bool = True) -> Path:
        """Kelias iš modelio -> tikras failas leistinuose kataloguose."""
        if not self.roots:
            raise FileToolError("failų katalogai nenurodyti")
        if not path:
            return self.roots[0]
        candidate = Path(str(path)).expanduser()
        options = [candidate] if candidate.is_absolute() else [r / candidate for r in self.roots]
        for option in options:
            try:
                resolved = option.resolve()
            except OSError:
                continue
            if any(resolved == root or resolved.is_relative_to(root) for root in self.roots):
                if must_exist and not resolved.exists():
                    continue
                return resolved
        allowed = ", ".join(str(r) for r in self.roots)
        raise FileToolError(f"`{path}` nepasiekiamas; leidžiama tik: {allowed}")

    def _walk(self, start: Path):
        """Failai po `start`, praleidžiant tarnybinius katalogus."""
        seen = 0
        for base, dirs, names in os.walk(start):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for name in sorted(names):
                if name.startswith("."):
                    continue
                seen += 1
                if seen > MAX_SCAN_FILES:
                    return
                yield Path(base) / name

    def _label(self, path: Path) -> str:
        for root in self.roots:
            if path == root or path.is_relative_to(root):
                return str(path.relative_to(root)) or root.name
        return str(path)

    # ---- įrankiai ------------------------------------------------------

    def list_files(self, directory: str | None = None, pattern: str | None = None) -> str:
        start = self._resolve(directory)
        if start.is_file():
            return self._label(start)
        rows = []
        for path in self._walk(start):
            if pattern and not path.match(pattern):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            rows.append(f"{self._label(path)} ({size} B)")
            if len(rows) >= 200:
                rows.append("… (daugiau failų nerodoma)")
                break
        return "\n".join(rows) if rows else "(failų nerasta)"

    def search_files(self, query: str, directory: str | None = None) -> str:
        if not query.strip():
            raise FileToolError("tuščia paieškos užklausa")
        start = self._resolve(directory)
        needle = query.lower()
        matches: list[str] = []
        for path in self._walk(start):
            try:
                if path.stat().st_size > self.max_file_bytes or _is_binary(path):
                    continue
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    for number, line in enumerate(f, 1):
                        if needle in line.lower():
                            matches.append(f"{self._label(path)}:{number}: {line.strip()[:200]}")
                            if len(matches) >= MAX_MATCHES:
                                matches.append("… (rasta daugiau — patikslink užklausą)")
                                return "\n".join(matches)
            except OSError:
                continue
        return "\n".join(matches) if matches else f"nieko nerasta pagal „{query}“"

    def read_file(self, path: str, start_line: int | None = None) -> str:
        target = self._resolve(path)
        if target.is_dir():
            raise FileToolError(f"`{path}` yra katalogas — naudok list_files")
        if not target.exists():
            raise FileToolError(f"`{path}` nerastas")
        if target.stat().st_size > self.max_file_bytes:
            raise FileToolError(f"failas per didelis ({target.stat().st_size} B)")
        if _is_binary(target):
            raise FileToolError("failas dvejetainis, ne tekstas")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        first = max(1, int(start_line or 1))
        chunk = lines[first - 1 : first - 1 + MAX_READ_LINES]
        if not chunk:
            return "(failo pabaiga)"
        body = "\n".join(f"{first + i:>4}: {line}" for i, line in enumerate(chunk))
        last = first + len(chunk) - 1
        if last < len(lines):
            body += f"\n… ({len(lines) - last} eilutės toliau; start_line={last + 1})"
        return body
