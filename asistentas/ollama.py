"""Ollama variklis: modeliai tavo Mac'e arba Ollama debesyje.

Ollama kalba OpenAI suderinama kalba, o šis projektas — Anthropic. Čia ir
gyvena vertimas tarp jų: pokalbio istorija visada saugoma Anthropic blokais
(kad sesijos liktų vienodos ir jas būtų galima tęsti kitu varikliu), o prieš
siunčiant paverčiama OpenAI formatu ir atgal.

Ko Ollama pusėje nėra ir nebus: paieškos internete, MCP serverių ir prompto
talpyklos — tai Anthropic serverių paslaugos. Atmintis ir failų įrankiai
veikia abiem atvejais, nes tai paprastos funkcijos tavo kompiuteryje.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from types import SimpleNamespace

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 900  # lokalus modelis gali galvoti ilgai

FINISH_REASONS = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


class OllamaError(Exception):
    """Klaida, kurią rodome lietuviškai."""


# ---- atsakymas, atrodantis kaip Anthropic žinutė ------------------------


class LocalUsage:
    """Tiek laukų, kiek tikisi pricing.Usage."""

    def __init__(self, input_tokens: int = 0, output_tokens: int = 0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0
        self.server_tool_use = None


class LocalMessage:
    """Ollama atsakymas, apsirengęs Anthropic žinutės drabužiais.

    Taip visas likęs kodas — istorija, įrankių ciklas, sesijų saugojimas —
    veikia nepakeistas, nesvarbu, kuris variklis atsakė.
    """

    def __init__(self, blocks: list[dict], stop_reason: str, usage: LocalUsage):
        self._blocks = blocks
        self.content = [SimpleNamespace(**block) for block in blocks]
        self.stop_reason = stop_reason
        self.usage = usage
        self.stop_details = None

    def to_dict(self, mode: str = "python") -> dict:
        return {"content": self._blocks}


# ---- vertimas į OpenAI formatą ------------------------------------------


def to_openai_messages(system_text: str, messages: list[dict]) -> list[dict]:
    """Anthropic istorija -> OpenAI žinutės."""
    out: list[dict] = []
    if system_text:
        out.append({"role": "system", "content": system_text})

    for message in messages:
        role = message.get("role")
        content = message.get("content")

        if role == "system":
            out.append({"role": "system", "content": _plain(content)})
            continue

        if role == "user":
            if isinstance(content, str):
                out.append({"role": "user", "content": content})
                continue
            # Įrankių rezultatai: Anthropic juos deda į vieną user žinutę,
            # OpenAI nori po atskirą `tool` žinutę kiekvienam.
            others = []
            for block in content or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    out.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": _plain(block.get("content")),
                    })
                else:
                    others.append(block)
            if others:
                out.append({"role": "user", "content": _plain(others)})
            continue

        if role == "assistant":
            text_parts, calls = [], []
            for block in content or []:
                if not isinstance(block, dict):
                    continue
                kind = block.get("type")
                if kind == "text":
                    text_parts.append(block.get("text", ""))
                elif kind == "tool_use":
                    calls.append({
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                        },
                    })
                # thinking, server_tool_use, web_search_tool_result — praleidžiam:
                # kitas variklis jų vis tiek nesupranta.
            entry: dict = {"role": "assistant", "content": "".join(text_parts)}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)

    return out


def _plain(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict):
            parts.append(block.get("text") or block.get("content") or "")
        else:
            parts.append(str(block))
    return "\n".join(p for p in parts if p)


MEMORY_FUNCTION = {
    "type": "function",
    "function": {
        "name": "memory",
        "description": (
            "Long-term memory across conversations. Files live under /memories. "
            "Use `view` to check what you already know before answering, and "
            "`create` or `str_replace` to record lasting facts about the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["view", "create", "str_replace", "insert", "delete", "rename"],
                },
                "path": {"type": "string", "description": "Path starting with /memories"},
                "file_text": {"type": "string", "description": "Contents for `create`."},
                "old_str": {"type": "string"},
                "new_str": {"type": "string"},
                "insert_line": {"type": "integer"},
                "insert_text": {"type": "string"},
                "old_path": {"type": "string"},
                "new_path": {"type": "string"},
            },
            "required": ["command"],
        },
    },
}


def to_openai_tools(tools: list[dict]) -> list[dict]:
    """Anthropic įrankiai -> OpenAI funkcijos. Serveriniai praleidžiami."""
    out = []
    for tool in tools:
        kind = tool.get("type")
        if kind == "memory_20250818":
            out.append(MEMORY_FUNCTION)
        elif kind is None and "input_schema" in tool:
            out.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["input_schema"],
                },
            })
        # web_search_*, mcp_toolset — Anthropic serverių paslaugos, čia jų nėra.
    return out


# ---- variklis -----------------------------------------------------------


class OllamaBackend:
    name = "ollama"
    server_tools = False       # nei paieškos, nei MCP
    prompt_caching = False

    def __init__(self, settings):
        self.settings = settings

    @property
    def local(self) -> bool:
        address = self.settings.address
        return "localhost" in address or "127.0.0.1" in address

    @property
    def model(self) -> str:
        return self.settings.model

    def _headers(self) -> dict:
        import os

        headers = {"Content-Type": "application/json"}
        token = os.environ.get(self.settings.key_env or "") if self.settings.key_env else ""
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def payload(self, assistant) -> dict:
        system_text = assistant.system_blocks()[0]["text"]
        body: dict = {
            "model": self.settings.model,
            "messages": to_openai_messages(system_text, assistant.session.messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        tools = to_openai_tools(assistant.tools())
        if tools:
            body["tools"] = tools
        return body

    def stream(self, assistant, turn, renderer) -> LocalMessage:
        body = json.dumps(self.payload(assistant)).encode("utf-8")
        url = self.settings.address.rstrip("/") + "/v1/chat/completions"
        request = urllib.request.Request(url, data=body, headers=self._headers())
        try:
            response = urllib.request.urlopen(request, timeout=READ_TIMEOUT)
        except urllib.error.HTTPError as e:
            raise OllamaError(_http_error(e, self.settings)) from e
        except urllib.error.URLError as e:
            raise OllamaError(
                f"Ollama neatsiliepia ties {self.settings.address} "
                f"({e.reason}). Ar ji paleista? — `ollama serve`"
            ) from e
        with response:
            return self._read_stream(response, assistant, turn, renderer)

    def _read_stream(self, response, assistant, turn, renderer) -> LocalMessage:
        text_parts: list[str] = []
        calls: dict[int, dict] = {}
        finish = "end_turn"
        usage = LocalUsage()
        thinking_shown = False

        for raw in response:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue

            if chunk.get("usage"):
                usage = LocalUsage(
                    int(chunk["usage"].get("prompt_tokens") or 0),
                    int(chunk["usage"].get("completion_tokens") or 0),
                )

            for choice in chunk.get("choices") or []:
                delta = choice.get("delta") or {}

                reasoning = delta.get("reasoning_content") or delta.get("thinking") or ""
                if reasoning and assistant.config.show_thinking:
                    renderer.thinking(reasoning)
                    thinking_shown = True

                piece = delta.get("content") or ""
                if piece:
                    if thinking_shown:
                        renderer.thinking_end()
                        thinking_shown = False
                    text_parts.append(piece)
                    turn.text += piece
                    renderer.feed(piece)

                for call in delta.get("tool_calls") or []:
                    index = int(call.get("index") or 0)
                    slot = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if call.get("id"):
                        slot["id"] = call["id"]
                    function = call.get("function") or {}
                    if function.get("name"):
                        slot["name"] = function["name"]
                    if function.get("arguments"):
                        slot["arguments"] += function["arguments"]

                if choice.get("finish_reason"):
                    finish = FINISH_REASONS.get(choice["finish_reason"], "end_turn")

        if thinking_shown:
            renderer.thinking_end()

        blocks: list[dict] = []
        if any(text_parts):
            blocks.append({"type": "text", "text": "".join(text_parts)})
        for index in sorted(calls):
            slot = calls[index]
            if not slot["name"]:
                continue
            blocks.append({
                "type": "tool_use",
                "id": slot["id"] or f"call_{index}",
                "name": slot["name"],
                "input": _arguments(slot["arguments"]),
            })
        if blocks and blocks[-1]["type"] == "tool_use":
            finish = "tool_use"
        return LocalMessage(blocks, finish, usage)


def _arguments(raw: str) -> dict:
    """Modelio sugeneruoti argumentai. Netvarkingi — grąžinam tuščius,
    o įrankis pats pasiskųs ir modelis pabandys iš naujo."""
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _http_error(error, settings) -> str:
    try:
        detail = json.loads(error.read().decode("utf-8", "replace"))
        message = detail.get("error", {}).get("message") or detail.get("error") or ""
    except (json.JSONDecodeError, OSError, AttributeError):
        message = ""
    if error.code == 404:
        return f"Ollama nerado modelio `{settings.model}` — `ollama pull {settings.model}`"
    if error.code in (401, 403):
        return (
            f"Ollama atmetė raktą. Debesiui reikia: export {settings.key_env}=..."
        )
    return f"Ollama klaida {error.code}: {message or 'nežinoma'}"
