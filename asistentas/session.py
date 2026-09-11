"""Pokalbių saugojimas: viena sesija — vienas JSON failas ~/.asistentas/sesijos/.

Žinutės saugomos tokios, kokias jas grąžino API (tie patys blokai), kad
tęsiant pokalbį istorija būtų atkuriama be nuostolių.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from asistentas.pricing import Usage

FORMAT_VERSION = 1
TITLE_MAX = 60


def _tool_uses(message: dict) -> list[dict]:
    """Įrankių iškvietimai žinutėje (tuščia, jei tai ne asistento eilė)."""
    if message.get("role") != "assistant":
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [
        b for b in content
        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")
    ]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


@dataclass
class Session:
    id: str = field(default_factory=new_id)
    title: str = ""
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    messages: list[dict] = field(default_factory=list)
    # Data, apie kurią modeliui jau pasakėme (kad nekartotume kas žinutę).
    last_date: str = ""

    def add_user(self, text: str) -> None:
        if not self.title:
            self.title = text.strip().splitlines()[0][:TITLE_MAX] if text.strip() else "(tuščia)"
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, content: list[dict]) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def extend_assistant(self, content: list[dict]) -> None:
        """Pratęsia paskutinį atsakymą (po `pause_turn` tai ta pati eilė)."""
        if self.messages and self.messages[-1]["role"] == "assistant":
            self.messages[-1]["content"] = list(self.messages[-1]["content"]) + list(content)
        else:
            self.add_assistant(content)

    def add_system(self, text: str) -> None:
        self.messages.append({"role": "system", "content": text})

    def add_tool_results(self, blocks: list[dict]) -> None:
        """Visi vieno žingsnio įrankių rezultatai keliauja viena žinute."""
        self.messages.append({"role": "user", "content": blocks})

    def rollback_turn(self) -> None:
        """Grąžina istoriją į paskutinę baigtą asistento eilę.

        Naudojama, kai atsakymo taip ir negavome: istorija negali likti
        nei su neatsakytu klausimu, nei su iškviestu įrankiu be rezultato.
        """
        while self.messages:
            last = self.messages[-1]
            if last["role"] == "assistant" and not _tool_uses(last):
                break
            self.messages.pop()

    def close_dangling_tools(self, reason: str) -> None:
        """Užbaigia pakibusius įrankių iškvietimus (pvz. nutraukus Ctrl+C).

        API reikalauja, kad po kiekvieno `tool_use` eitų `tool_result`.
        """
        pending = _tool_uses(self.messages[-1]) if self.messages else []
        if not pending:
            return
        self.add_tool_results(
            [
                {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": reason,
                    "is_error": True,
                }
                for block in pending
            ]
        )

    @property
    def turns(self) -> int:
        return sum(1 for m in self.messages if m["role"] == "user")

    def to_dict(self) -> dict:
        return {
            "versija": FORMAT_VERSION,
            "id": self.id,
            "pavadinimas": self.title,
            "sukurta": self.created,
            "atnaujinta": self.updated,
            "modelis": self.model,
            "paskutine_data": self.last_date,
            "naudojimas": self.usage.to_dict(),
            "zinutes": self.messages,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        return cls(
            id=data.get("id") or new_id(),
            title=data.get("pavadinimas", ""),
            created=data.get("sukurta", _now()),
            updated=data.get("atnaujinta", _now()),
            model=data.get("modelis", ""),
            usage=Usage.from_dict(data.get("naudojimas")),
            messages=list(data.get("zinutes") or []),
            last_date=data.get("paskutine_data", ""),
        )


class Store:
    """Sesijų failai diske."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)

    def _path(self, session_id: str) -> Path:
        safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
        if not safe:
            raise ValueError(f"netinkamas sesijos id: {session_id!r}")
        return self.dir / f"{safe}.json"

    def save(self, session: Session) -> Path:
        """Įrašo atomiškai: nutrūkęs procesas nesugadina ankstesnės sesijos."""
        self.dir.mkdir(parents=True, exist_ok=True)
        session.updated = _now()
        path = self._path(session.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return path

    def load(self, session_id: str) -> Session:
        path = self._path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"sesijos `{session_id}` nėra")
        return Session.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list(self, limit: int = 20) -> list[Session]:
        """Naujausios sesijos pirmiau. Sugadintus failus tyliai praleidžia."""
        if not self.dir.exists():
            return []
        out: list[Session] = []
        for path in sorted(self.dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                out.append(Session.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, OSError, TypeError):
                continue
            if len(out) >= limit:
                break
        return out

    def latest(self) -> Session | None:
        found = self.list(limit=1)
        return found[0] if found else None
