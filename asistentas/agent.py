"""Bendravimas su Claude API.

Vienas klausimas = vienas `ask()` iškvietimas: atsakymas rašomas srautu,
paieška internete vyksta Anthropic serveriuose, o istorija auga sesijoje.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from asistentas.config import Config
from asistentas.pricing import Usage
from asistentas.session import Session

# Serverinė paieška gali sustoti ties vidiniu ciklo limitu (`pause_turn`);
# tada užklausą kartojame — serveris tęsia nuo tos vietos.
MAX_CONTINUATIONS = 5

# Atsarginis modelis, kai Claude Opus 5 atsisako atsakyti dėl saugumo
# klasifikatoriaus: serveris pats perleidžia užklausą tinkamam modeliui.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

WEEKDAYS_LT = (
    "pirmadienis", "antradienis", "trečiadienis", "ketvirtadienis",
    "penktadienis", "šeštadienis", "sekmadienis",
)

SEARCH_ERRORS_LT = {
    "max_uses_exceeded": "pasiektas paieškų limitas šiame atsakyme",
    "too_many_requests": "per daug paieškos užklausų — pabandyk vėliau",
    "invalid_input": "netinkama paieškos užklausa",
    "query_too_long": "paieškos užklausa per ilga",
    "unavailable": "paieška laikinai neveikia",
}


@dataclass
class Turn:
    """Vieno klausimo rezultatas."""

    text: str = ""
    sources: list[tuple[str, str]] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    stop_reason: str | None = None
    refusal: str | None = None
    interrupted: bool = False
    notes: list[str] = field(default_factory=list)


class Assistant:
    def __init__(self, config: Config, session: Session, client=None):
        self.config = config
        self.session = session
        self._client = client
        self._fallbacks = config.fallbacks

    # ---- viešoji dalis -------------------------------------------------

    def ask(self, text: str, renderer) -> Turn:
        """Užduoda klausimą ir rašo atsakymą per `renderer`."""
        self.session.model = self.config.model
        self.session.add_user(text)
        self._add_date_if_needed()

        turn = Turn()
        try:
            self._run(turn, renderer)
        except KeyboardInterrupt:
            turn.interrupted = True
            self._keep_partial(turn)
            raise
        finally:
            renderer.close()
        self.session.usage = self.session.usage + turn.usage
        return turn

    # ---- užklausos sudėliojimas ---------------------------------------

    @property
    def cached_client(self):
        """Jau sukurtas klientas arba None — kad CLI galėtų jį naudoti toliau."""
        return self._client

    def client(self):
        if self._client is None:
            import anthropic  # importuojame vėlai — greitesnis paleidimas

            self._client = anthropic.Anthropic()
        return self._client

    def local_now(self) -> datetime:
        tz = self.config.timezone
        if tz:
            try:
                return datetime.now(ZoneInfo(tz))
            except (ZoneInfoNotFoundError, ValueError):
                pass
        return datetime.now().astimezone()

    def today_line(self) -> str:
        now = self.local_now()
        diena = WEEKDAYS_LT[now.weekday()]
        vieta = self.config.timezone or "vietos laikas"
        return f"Šiandien {now:%Y-%m-%d}, {diena}. Vietos laikas {now:%H:%M} ({vieta})."

    def _add_date_if_needed(self) -> None:
        """Modelis turi žinoti šiandienos datą — kitaip paieška beprasmė.

        Data keliauja atskira `system` žinute po vartotojo klausimo: taip
        nekeičiamas sistemos promptas ir nesugriaunama talpykla. Įdedame tik
        kai data pasikeitė, kad istorija nesiterštų.
        """
        if not self.config.supports_system_messages:
            return  # tokiam modeliui data jau įdėta į sistemos promptą
        today = self.local_now().strftime("%Y-%m-%d")
        if self.session.last_date == today:
            return
        self.session.add_system(self.today_line())
        self.session.last_date = today

    def system_blocks(self) -> list[dict]:
        text = self.config.persona
        if not self.config.supports_system_messages:
            # Šis modelis nepriima `system` žinučių pokalbio viduryje, tad
            # data lieka prompte (talpykla atsinaujina kartą per parą).
            text = f"{text}\n\n{self.today_line()}"
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]

    def tools(self) -> list[dict]:
        if not self.config.search:
            return []
        tool: dict = {
            "type": self.config.search_tool_type,
            "name": "web_search",
            "max_uses": self.config.search_max_uses,
        }
        location = {
            k: v
            for k, v in (
                ("city", self.config.city),
                ("region", self.config.region),
                ("country", self.config.country),
                ("timezone", self.config.timezone),
            )
            if v
        }
        if location:
            tool["user_location"] = {"type": "approximate", **location}
        if self.config.allowed_domains:
            tool["allowed_domains"] = list(self.config.allowed_domains)
        elif self.config.blocked_domains:
            tool["blocked_domains"] = list(self.config.blocked_domains)
        return [tool]

    def request_kwargs(self) -> dict:
        thinking: dict = {"type": "adaptive"}
        if self.config.show_thinking:
            thinking["display"] = "summarized"
        kwargs: dict = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": self.system_blocks(),
            "messages": list(self.session.messages),
            "thinking": thinking,
            "output_config": {"effort": self.config.effort},
            "cache_control": {"type": "ephemeral"},
        }
        tools = self.tools()
        if tools:
            kwargs["tools"] = tools
        if self._fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    # ---- pokalbio ciklas -----------------------------------------------

    def _run(self, turn: Turn, renderer) -> None:
        resuming = False  # ar tęsiame ties `pause_turn` nutrūkusią eilę
        for _ in range(MAX_CONTINUATIONS):
            try:
                final = self._stream_once(turn, renderer)
            except Exception as e:  # noqa: BLE001 — tikriname konkrečiai žemiau
                if self._fallbacks and _is_fallback_error(e):
                    # Šis API arba SDK dar nemoka serverinio atsarginio modelio.
                    self._fallbacks = False
                    continue
                raise

            turn.usage.add_message(getattr(final, "usage", None))
            content = _content_dicts(final)
            if resuming:
                self.session.extend_assistant(content)
            else:
                self.session.add_assistant(content)
            self._collect_sources(final, turn)
            turn.stop_reason = getattr(final, "stop_reason", None)

            if turn.stop_reason == "pause_turn":
                resuming = True
                continue  # serveris tęsia ten, kur sustojo
            if turn.stop_reason == "refusal":
                turn.refusal = _refusal_text(final)
            elif turn.stop_reason == "max_tokens":
                turn.notes.append("atsakymas nutrūko ties ilgio riba")
            return
        turn.notes.append(f"nutraukiau po {MAX_CONTINUATIONS} tęsinių")

    def _stream_once(self, turn: Turn, renderer):
        tool_input = ""
        thinking_shown = False
        with self.client().beta.messages.stream(**self.request_kwargs()) as stream:
            for event in stream:
                kind = getattr(event, "type", "")

                if kind == "content_block_start":
                    block_type = getattr(getattr(event, "content_block", None), "type", "")
                    if block_type == "server_tool_use":
                        tool_input = ""

                elif kind == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    dtype = getattr(delta, "type", "")
                    if dtype == "text_delta":
                        chunk = getattr(delta, "text", "") or ""
                        if chunk:
                            if thinking_shown:
                                renderer.thinking_end()
                                thinking_shown = False
                            turn.text += chunk
                            renderer.feed(chunk)
                    elif dtype == "thinking_delta" and self.config.show_thinking:
                        chunk = getattr(delta, "thinking", "") or ""
                        if chunk:
                            renderer.thinking(chunk)
                            thinking_shown = True
                    elif dtype == "input_json_delta":
                        tool_input += getattr(delta, "partial_json", "") or ""

                elif kind == "content_block_stop":
                    if tool_input:
                        if thinking_shown:
                            renderer.thinking_end()
                            thinking_shown = False
                        renderer.note(f"🔎 {_query_of(tool_input)}")
                        tool_input = ""

            if thinking_shown:
                renderer.thinking_end()
            return stream.get_final_message()

    def _collect_sources(self, final, turn: Turn) -> None:
        seen = {url for _, url in turn.sources}
        for block in getattr(final, "content", None) or []:
            if getattr(block, "type", "") != "web_search_tool_result":
                continue
            content = getattr(block, "content", None)
            if isinstance(content, list):
                for result in content:
                    url = getattr(result, "url", None)
                    if url and url not in seen:
                        seen.add(url)
                        turn.sources.append((getattr(result, "title", "") or url, url))
            else:
                # Serverinio įrankio klaida grįžta ne sąrašu, o objektu.
                code = getattr(content, "error_code", None)
                if code:
                    turn.notes.append(
                        f"paieška: {SEARCH_ERRORS_LT.get(code, code)}"
                    )

    def _keep_partial(self, turn: Turn) -> None:
        """Nutraukus atsakymą (Ctrl+C) istorija turi likti tvarkinga."""
        if turn.text.strip():
            self.session.add_assistant([{"type": "text", "text": turn.text}])
        else:
            self.session.drop_last_user()
            self.session.last_date = ""


def _query_of(partial_json: str) -> str:
    try:
        data = json.loads(partial_json)
    except json.JSONDecodeError:
        return "ieškau internete…"
    query = data.get("query") if isinstance(data, dict) else None
    return f"ieškau: {query}" if query else "ieškau internete…"


def _content_dicts(message) -> list[dict]:
    """Atsakymo blokai tokiu pat pavidalu, kokiu juos atsiuntė API."""
    to_dict = getattr(message, "to_dict", None)
    if callable(to_dict):
        content = to_dict(mode="json").get("content")
        if isinstance(content, list):
            return content
    return list(getattr(message, "content", None) or [])


def _refusal_text(final) -> str:
    details = getattr(final, "stop_details", None)
    explanation = getattr(details, "explanation", None)
    category = getattr(details, "category", None)
    if explanation:
        return str(explanation)
    if category:
        return f"modelis atsisakė atsakyti (kategorija: {category})"
    return "modelis atsisakė atsakyti"


def _is_fallback_error(error) -> bool:
    """Ar klaida susijusi su serverinio atsarginio modelio parametru?"""
    status = getattr(error, "status_code", None)
    if status not in (400, 404):
        return False
    text = f"{getattr(error, 'message', '')} {error}".lower()
    return "fallback" in text or "beta" in text
