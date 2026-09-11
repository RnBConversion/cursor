import json

import pytest

from asistentas.pricing import Usage
from asistentas.session import Session, Store


def test_pavadinimas_is_pirmo_klausimo():
    s = Session()
    s.add_user("Kiek kainuoja elektra Lietuvoje?\nAntra eilutė")
    s.add_user("antras klausimas")
    assert s.title == "Kiek kainuoja elektra Lietuvoje?"  # tik pirma eilutė


def test_ilgas_pavadinimas_trumpinamas():
    s = Session()
    s.add_user("x" * 200)
    assert len(s.title) == 60


def test_issaugo_ir_uzkrauna(tmp_path):
    store = Store(tmp_path)
    s = Session(model="claude-opus-5")
    s.add_user("labas, ąžuolas")
    s.add_assistant([{"type": "text", "text": "sveikas 👋"}])
    s.usage = Usage(input_tokens=5, searches=1)
    store.save(s)

    atgal = store.load(s.id)
    assert atgal.messages == s.messages          # blokai nepakitę
    assert atgal.usage == s.usage
    assert atgal.model == "claude-opus-5"
    assert atgal.title == "labas, ąžuolas"


def test_failas_neslepia_lietuvisku_raidziu(tmp_path):
    store = Store(tmp_path)
    s = Session()
    s.add_user("ąčęėįšųūž")
    path = store.save(s)
    assert "ąčęėįšųūž" in path.read_text(encoding="utf-8")


def test_irasoma_atomiskai(tmp_path):
    store = Store(tmp_path)
    s = Session()
    s.add_user("klausimas")
    store.save(s)
    store.save(s)
    assert list(tmp_path.glob("*.tmp")) == []     # laikinų failų nelieka


def test_sarasas_naujausi_pirmiau(tmp_path):
    store = Store(tmp_path)
    ids = []
    for i in range(3):
        s = Session(id=f"2026010{i}-000000-aaaa")
        s.add_user(f"klausimas {i}")
        store.save(s)
        ids.append(s.id)
    gauta = [s.id for s in store.list()]
    assert set(gauta) == set(ids)
    assert store.latest().id == gauta[0]
    assert len(store.list(limit=2)) == 2


def test_sugadintas_failas_praleidziamas(tmp_path):
    store = Store(tmp_path)
    s = Session()
    s.add_user("geras")
    store.save(s)
    (tmp_path / "blogas.json").write_text("{ne json", encoding="utf-8")
    assert [x.id for x in store.list()] == [s.id]


def test_nera_sesijos(tmp_path):
    with pytest.raises(FileNotFoundError):
        Store(tmp_path).load("nera-tokios")
    assert Store(tmp_path / "nieko").list() == []
    assert Store(tmp_path / "nieko").latest() is None


def test_id_negali_iseiti_is_katalogo(tmp_path):
    """Sesijos id ateina iš vartotojo — jis neturi pasiekti kitų failų."""
    store = Store(tmp_path)
    kelias = store._path("../../etc/passwd")
    assert kelias.parent == tmp_path
    with pytest.raises(ValueError):
        store._path("../..")


def test_nutraukto_klausimo_pasalinimas():
    s = Session()
    s.add_user("pirmas")
    s.add_assistant([{"type": "text", "text": "atsakymas"}])
    s.add_user("antras")
    s.add_system("Šiandien 2026-09-11.")
    s.drop_last_user()
    assert [m["role"] for m in s.messages] == ["user", "assistant"]


def test_pasalinimas_tusciame_pokalbyje():
    s = Session()
    s.add_user("vienintelis")
    s.drop_last_user()
    assert s.messages == []


def test_senas_formatas_neuzmuša(tmp_path):
    (tmp_path / "sena.json").write_text(json.dumps({"id": "sena"}), encoding="utf-8")
    s = Store(tmp_path).load("sena")
    assert s.messages == [] and s.usage == Usage()
