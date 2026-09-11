"""Žetonų ir kainos skaičiavimas.

Kainos — Anthropic API sąrašinės, JAV doleriais už 1 mln. žetonų.
Jei naudoji Bedrock ar Vertex, kainos kitokios — pasitikslink pas tiekėją.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# modelis -> (įvestis, išvestis) USD už 1M žetonų
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-fable-5-1": (10.0, 50.0),
}

CACHE_WRITE_RATE = 1.25  # įrašymas į talpyklą brangesnis už paprastą įvestį
CACHE_READ_RATE = 0.10   # skaitymas iš talpyklos ~10 kartų pigesnis
SEARCH_USD = 10.0 / 1000  # viena paieška internete


@dataclass
class Usage:
    """Sukauptas vieno atsakymo arba visos sesijos sunaudojimas."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    searches: int = 0

    def add_message(self, usage) -> "Usage":
        """Prideda vieno API atsakymo `usage` objektą (atsparu trūkstamiems laukams)."""
        self.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        self.cache_read_tokens += int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        self.cache_write_tokens += int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        server = getattr(usage, "server_tool_use", None)
        if server is not None:
            self.searches += int(getattr(server, "web_search_requests", 0) or 0)
        return self

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            searches=self.searches + other.searches,
        )

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )

    def cost(self, model: str) -> float | None:
        """Kaina doleriais arba None, jei modelio kainos nežinome."""
        price = PRICES.get(model)
        if price is None:
            return None
        in_rate, out_rate = price
        return (
            self.input_tokens * in_rate
            + self.cache_write_tokens * in_rate * CACHE_WRITE_RATE
            + self.cache_read_tokens * in_rate * CACHE_READ_RATE
            + self.output_tokens * out_rate
        ) / 1_000_000 + self.searches * SEARCH_USD

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Usage":
        data = data or {}
        known = {f: data.get(f, 0) for f in cls.__dataclass_fields__}
        return cls(**{k: int(v or 0) for k, v in known.items()})


def format_cost(cost: float | None) -> str:
    """Kaina žmogui: labai mažos sumos rodomos centų dalimis, o ne `$0.00`."""
    if cost is None:
        return "kaina nežinoma"
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"
