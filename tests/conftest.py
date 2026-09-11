"""Netikras API klientas — testai neturi liesti tinklo ir nekainuoja nė cento."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anthropic.types.beta import BetaMessage  # noqa: E402


def text_delta(text: str):
    return SimpleNamespace(
        type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text)
    )


def thinking_delta(text: str):
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="thinking_delta", thinking=text),
    )


def search_events(query: str):
    """Įvykiai, kuriuos siunčia serverinė paieška."""
    return [
        SimpleNamespace(
            type="content_block_start",
            content_block=SimpleNamespace(type="server_tool_use", name="web_search"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"query": "'),
        ),
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="input_json_delta", partial_json=query + '"}'),
        ),
        SimpleNamespace(type="content_block_stop"),
    ]


def message(
    *,
    text: str = "",
    stop_reason: str = "end_turn",
    content: list | None = None,
    usage: dict | None = None,
    stop_details: dict | None = None,
) -> BetaMessage:
    """Tikras BetaMessage objektas — taip testuojame tą patį kelią kaip gyvenime."""
    blocks = content if content is not None else ([{"type": "text", "text": text}] if text else [])
    data = {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5",
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "content": blocks,
        "usage": {"input_tokens": 10, "output_tokens": 5, **(usage or {})},
    }
    if stop_details:
        data["stop_details"] = stop_details
    return BetaMessage.model_validate(data)


class FakeStream:
    def __init__(self, events, final):
        self._events = events
        self._final = final
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._final


class FakeMessages:
    def __init__(self, turns):
        # turns: sąrašas (įvykiai, galutinė žinutė) arba išimtis
        self._turns = list(turns)
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        if not self._turns:
            raise AssertionError("netikėtas papildomas API iškvietimas")
        turn = self._turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        events, final = turn
        return FakeStream(events, final)


class FakeClient:
    def __init__(self, *turns):
        self.messages = FakeMessages(turns)
        self.beta = SimpleNamespace(messages=self.messages)

    @property
    def calls(self):
        return self.messages.calls


class ApiError(Exception):
    """Panaši į anthropic.BadRequestError: turi status_code ir message."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@pytest.fixture
def home(tmp_path) -> Path:
    return tmp_path / "asistentas"


@pytest.fixture
def cfg(home):
    from asistentas import config

    return config.load(home=home)
