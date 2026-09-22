"""Ollama variklis — tikrinamas su tikru vietiniu HTTP serveriu.

Netikras klientas čia netiktų: svarbiausia dalis yra pats SSE srautas ir
vertimas tarp Anthropic bei OpenAI formatų, o tai matyti tik per lizdą.
"""

import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from asistentas.agent import Assistant
from asistentas.config import Ollama
from asistentas.ollama import (
    OllamaBackend,
    OllamaError,
    to_openai_messages,
    to_openai_tools,
)
from asistentas.render import Colors, MarkdownStream
from asistentas.session import Session


# ---- vertimas -----------------------------------------------------------


def test_istorija_verciama_i_openai_formata():
    zinutes = [
        {"role": "user", "content": "labas"},
        {"role": "system", "content": "Šiandien 2026-09-21."},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "slapta"},
            {"type": "text", "text": "Tikrinu"},
            {"type": "tool_use", "id": "t1", "name": "memory", "input": {"command": "view"}},
        ]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "tuščia"}]},
    ]
    out = to_openai_messages("Tu esi asistentas.", zinutes)
    assert [m["role"] for m in out] == ["system", "user", "system", "assistant", "tool"]
    assert out[3]["tool_calls"][0]["function"]["name"] == "memory"
    assert json.loads(out[3]["tool_calls"][0]["function"]["arguments"]) == {"command": "view"}
    assert out[4]["tool_call_id"] == "t1"
    assert "slapta" not in json.dumps(out)      # mąstymo blokai nekeliauja


def test_keli_irankiu_rezultatai_isskaidomi():
    """Anthropic juos deda į vieną žinutę, OpenAI nori po atskirą."""
    zinutes = [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "a", "content": "1"},
        {"type": "tool_result", "tool_use_id": "b", "content": "2"},
    ]}]
    out = to_openai_messages("", zinutes)
    assert [m["role"] for m in out] == ["tool", "tool"]


def test_serveriniai_irankiai_nesiunciami():
    """Paieška ir MCP vyksta Anthropic serveriuose — Ollama jų nesupranta."""
    irankiai = to_openai_tools([
        {"type": "web_search_20260209", "name": "web_search"},
        {"type": "mcp_toolset", "mcp_server_name": "gmail"},
        {"type": "memory_20250818", "name": "memory"},
        {"name": "read_file", "description": "d", "input_schema": {"type": "object"}},
    ])
    assert [t["function"]["name"] for t in irankiai] == ["memory", "read_file"]
    assert all(t["type"] == "function" for t in irankiai)


def test_atminties_funkcija_turi_visas_komandas():
    schema = to_openai_tools([{"type": "memory_20250818", "name": "memory"}])[0]
    komandos = schema["function"]["parameters"]["properties"]["command"]["enum"]
    assert set(komandos) == {"view", "create", "str_replace", "insert", "delete", "rename"}


# ---- netikras Ollama serveris -------------------------------------------


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.requests.append({"path": self.path, "body": body, "headers": dict(self.headers)})
        status, chunks = self.server.scripts.pop(0)
        if status != 200:
            payload = json.dumps({"error": {"message": "nepavyko"}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args):
        pass


@pytest.fixture
def serveris():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.requests, httpd.scripts = [], []
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    httpd.address = f"http://127.0.0.1:{httpd.server_port}"
    yield httpd
    httpd.shutdown()


def tekstas(*dalys, finish="stop"):
    chunks = [{"choices": [{"delta": {"content": d}}]} for d in dalys]
    chunks.append({"choices": [{"delta": {}, "finish_reason": finish}]})
    chunks.append({"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 8}})
    return (200, chunks)


def irankio_kvietimas(name, args_dalys, call_id="call_1"):
    chunks = [{"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": call_id, "function": {"name": name, "arguments": ""}}
    ]}}]}]
    for dalis in args_dalys:
        chunks.append({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": dalis}}
        ]}}]})
    chunks.append({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
    return (200, chunks)


def backend(serveris, **kw):
    return OllamaBackend(Ollama(address=serveris.address, model="qwen3:32b", **kw))


def renderer():
    return MarkdownStream(Colors(False), out=io.StringIO(), err=io.StringIO())


def assistant(cfg, serveris, session=None, **kw):
    return Assistant(
        cfg.with_(provider="ollama"),
        session or Session(),
        backend=backend(serveris, **kw),
    )


# ---- tikras srautas -----------------------------------------------------


def test_atsakymas_ateina_srautu(cfg, serveris):
    serveris.scripts.append(tekstas("La", "bas", ", Rolandai."))
    s = Session()
    r = renderer()
    turn = assistant(cfg, serveris, s).ask("sveikas", r)

    assert turn.text == "Labas, Rolandai."
    assert r.out.getvalue().strip() == "Labas, Rolandai."
    assert turn.usage.input_tokens == 120 and turn.usage.output_tokens == 8
    assert s.messages[-1] == {"role": "assistant", "content": [{"type": "text", "text": "Labas, Rolandai."}]}


def test_uzklausa_atitinka_ollama_protokola(cfg, serveris):
    serveris.scripts.append(tekstas("ok"))
    assistant(cfg, serveris).ask("labas", renderer())
    uzklausa = serveris.requests[0]
    assert uzklausa["path"] == "/v1/chat/completions"
    assert uzklausa["body"]["model"] == "qwen3:32b"
    assert uzklausa["body"]["stream"] is True
    assert uzklausa["body"]["messages"][0]["role"] == "system"
    # Anthropic dalykų čia būti negali
    assert "thinking" not in uzklausa["body"] and "cache_control" not in uzklausa["body"]


def test_irankis_ivykdomas_ir_pokalbis_tesiasi(cfg, serveris):
    """Visas ciklas: modelis prašo atminties, mes įvykdome, jis atsako."""
    serveris.scripts.append(
        irankio_kvietimas("memory", ['{"command": "cre', 'ate", "path": "/memories/apie.md",',
                                     ' "file_text": "Vardas: R"}'])
    )
    serveris.scripts.append(tekstas("Įsiminiau."))
    s = Session()
    r = renderer()
    turn = assistant(cfg.with_(memory=True), serveris, s).ask("įsimink mano vardą", r)

    assert turn.tool_calls == 1 and turn.text == "Įsiminiau."
    assert (cfg.memory_dir / "apie.md").read_text(encoding="utf-8") == "Vardas: R"
    # istorija lieka Anthropic formatu — sesiją galima tęsti ir su Claude
    assert [m["role"] for m in s.messages][-3:] == ["assistant", "user", "assistant"]
    assert s.messages[-3]["content"][0]["type"] == "tool_use"
    assert s.messages[-2]["content"][0]["type"] == "tool_result"
    # antroje užklausoje modelis mato įrankio rezultatą
    assert serveris.requests[1]["body"]["messages"][-1]["role"] == "tool"


def test_sugadinti_argumentai_negriauna_pokalbio(cfg, serveris):
    """Mažesni modeliai kartais sugeneruoja ne JSON — turi atsigauti."""
    serveris.scripts.append(irankio_kvietimas("memory", ["{netvarkinga"]))
    serveris.scripts.append(tekstas("Atsiprašau."))
    turn = assistant(cfg, serveris).ask("x", renderer())
    assert turn.text == "Atsiprašau."


def test_raktas_siunciamas_tik_debesiui(cfg, serveris, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "slaptas")
    serveris.scripts.append(tekstas("ok"))
    assistant(cfg, serveris).ask("labas", renderer())
    assert serveris.requests[0]["headers"].get("Authorization") == "Bearer slaptas"

    monkeypatch.delenv("OLLAMA_API_KEY")
    serveris.scripts.append(tekstas("ok"))
    assistant(cfg, serveris).ask("labas", renderer())
    assert "Authorization" not in serveris.requests[1]["headers"]


# ---- klaidos ------------------------------------------------------------


def test_nera_modelio(cfg, serveris):
    serveris.scripts.append((404, []))
    with pytest.raises(OllamaError, match="ollama pull qwen3:32b"):
        assistant(cfg, serveris).ask("labas", renderer())


def test_blogas_raktas(cfg, serveris):
    serveris.scripts.append((401, []))
    with pytest.raises(OllamaError, match="OLLAMA_API_KEY"):
        assistant(cfg, serveris).ask("labas", renderer())


def test_ollama_nepaleista(cfg):
    """Dažniausia klaida — pamiršta paleisti. Žinutė turi tai pasakyti."""
    b = OllamaBackend(Ollama(address="http://127.0.0.1:1", model="x"))
    a = Assistant(cfg.with_(provider="ollama"), Session(), backend=b)
    with pytest.raises(OllamaError, match="ollama serve"):
        a.ask("labas", renderer())


# ---- ko Ollama pusėje nėra ----------------------------------------------


def test_be_paieskos_ir_mcp(cfg, serveris):
    su_mcp = cfg.with_(
        provider="ollama",
        mcp_servers=({"pavadinimas": "gmail", "url": "https://x.lt", "token_env": None},),
    )
    a = Assistant(su_mcp, Session(), backend=backend(serveris))
    assert a.search_available is False
    assert [t.get("name") or t.get("type") for t in a.tools()] == ["memory"]
    assert "Interneto neturi" in a.system_blocks()[0]["text"]


def test_lokalus_modelis_atpazistamas(serveris):
    assert backend(serveris).local is True
    assert OllamaBackend(Ollama(address="https://ollama.com")).local is False
