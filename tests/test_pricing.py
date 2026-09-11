from types import SimpleNamespace

from asistentas.pricing import PRICES, Usage, format_cost


def test_opus5_kaina():
    """1M įvesties + 1M išvesties = 5 + 25 dolerio."""
    assert Usage(input_tokens=1_000_000, output_tokens=1_000_000).cost("claude-opus-5") == 30.0


def test_talpykla_pigiau_nei_ivestis():
    skaitymas = Usage(cache_read_tokens=1_000_000).cost("claude-opus-5")
    irasymas = Usage(cache_write_tokens=1_000_000).cost("claude-opus-5")
    ivestis = Usage(input_tokens=1_000_000).cost("claude-opus-5")
    assert skaitymas == 0.5          # 10 % įvesties kainos
    assert irasymas == 6.25          # 125 % įvesties kainos
    assert skaitymas < ivestis < irasymas


def test_paieskos_kaina():
    assert Usage(searches=1000).cost("claude-opus-5") == 10.0


def test_nezinomas_modelis_negriauna():
    assert Usage(input_tokens=100).cost("nera-tokio-modelio") is None
    assert format_cost(None) == "kaina nežinoma"


def test_visi_modeliai_turi_abi_kainas():
    for model, price in PRICES.items():
        assert len(price) == 2 and all(p > 0 for p in price), model


def test_sudetis():
    bendra = Usage(input_tokens=1, searches=1) + Usage(output_tokens=2, searches=2)
    assert (bendra.input_tokens, bendra.output_tokens, bendra.searches) == (1, 2, 3)


def test_prideda_api_atsakyma():
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=20,
        cache_read_input_tokens=30,
        cache_creation_input_tokens=40,
        server_tool_use=SimpleNamespace(web_search_requests=2),
    )
    u = Usage().add_message(usage)
    assert (u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens) == (10, 20, 30, 40)
    assert u.searches == 2
    assert u.total_tokens == 100


def test_truksta_lauku_arba_nera_naudojimo():
    """API laukai gali būti None arba jų gali nebūti — neturi lūžti."""
    Usage().add_message(SimpleNamespace(input_tokens=None, server_tool_use=None))
    Usage().add_message(None)
    assert Usage().add_message(SimpleNamespace()).total_tokens == 0


def test_issaugojimas_ir_atstatymas():
    u = Usage(input_tokens=1, output_tokens=2, cache_read_tokens=3, cache_write_tokens=4, searches=5)
    assert Usage.from_dict(u.to_dict()) == u
    assert Usage.from_dict(None) == Usage()
    assert Usage.from_dict({"input_tokens": 7, "nereikalingas": "x"}).input_tokens == 7


def test_kainos_formatas():
    assert format_cost(0.0001234) == "$0.0001"   # centų dalys matomos
    assert format_cost(1.5) == "$1.50"
