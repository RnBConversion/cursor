from types import SimpleNamespace as NS

import pytest

from asistentas.memory import MemoryError, MemoryStore


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "atmintis")


def cmd(command, **kw):
    return NS(command=command, **kw)


def test_irankio_aprasas(store):
    assert store.to_dict() == {"type": "memory_20250818", "name": "memory"}


def test_irasymas_ir_skaitymas(store):
    store.create(cmd("create", path="/memories/apie.md", file_text="Vardas: Rolandas\n"))
    assert "Vardas: Rolandas" in store.view(cmd("view", path="/memories/apie.md", view_range=None))
    assert "/memories/apie.md" in store.view(cmd("view", path="/memories", view_range=None))


def test_tuscia_atmintis(store):
    assert "tuščia" in store.view(cmd("view", path="/memories", view_range=None))


def test_eiluciu_ruozas(store):
    store.create(cmd("create", path="/memories/a.md", file_text="a\nb\nc\nd\n"))
    rodinys = store.view(cmd("view", path="/memories/a.md", view_range=[2, 3]))
    assert "b" in rodinys and "c" in rodinys and "d" not in rodinys


def test_pakeitimas(store):
    store.create(cmd("create", path="/memories/a.md", file_text="mėgsta kavą\n"))
    store.str_replace(cmd("str_replace", path="/memories/a.md", old_str="kavą", new_str="arbatą"))
    assert "arbatą" in store.view(cmd("view", path="/memories/a.md", view_range=None))


def test_pakeitimas_kai_tekstas_kartojasi(store):
    store.create(cmd("create", path="/memories/a.md", file_text="x\nx\n"))
    with pytest.raises(MemoryError, match="kartojasi"):
        store.str_replace(cmd("str_replace", path="/memories/a.md", old_str="x", new_str="y"))


def test_pakeitimas_kai_teksto_nera(store):
    store.create(cmd("create", path="/memories/a.md", file_text="x\n"))
    with pytest.raises(MemoryError, match="nėra"):
        store.str_replace(cmd("str_replace", path="/memories/a.md", old_str="z", new_str="y"))


def test_iterpimas(store):
    store.create(cmd("create", path="/memories/a.md", file_text="pirma\ntrecia\n"))
    store.insert(cmd("insert", path="/memories/a.md", insert_line=1, insert_text="antra"))
    rodinys = store.view(cmd("view", path="/memories/a.md", view_range=None))
    assert rodinys.index("pirma") < rodinys.index("antra") < rodinys.index("trecia")


def test_iterpimas_uz_ribu(store):
    store.create(cmd("create", path="/memories/a.md", file_text="viena\n"))
    with pytest.raises(MemoryError, match="už ribų"):
        store.insert(cmd("insert", path="/memories/a.md", insert_line=99, insert_text="x"))


def test_trynimas_ir_pervadinimas(store):
    store.create(cmd("create", path="/memories/a.md", file_text="x"))
    store.rename(cmd("rename", old_path="/memories/a.md", new_path="/memories/b/c.md"))
    assert store.files() == [("/memories/b/c.md", 1)]
    store.delete(cmd("delete", path="/memories/b"))
    assert store.files() == []


def test_visos_atminties_istrinti_negalima(store):
    store.create(cmd("create", path="/memories/a.md", file_text="x"))
    with pytest.raises(MemoryError, match="negalima"):
        store.delete(cmd("delete", path="/memories"))


def test_pervadinti_ant_esamo_negalima(store):
    store.create(cmd("create", path="/memories/a.md", file_text="x"))
    store.create(cmd("create", path="/memories/b.md", file_text="y"))
    with pytest.raises(MemoryError, match="jau yra"):
        store.rename(cmd("rename", old_path="/memories/a.md", new_path="/memories/b.md"))


@pytest.mark.parametrize(
    "kelias",
    [
        "/memories/../../../etc/passwd",
        "/memories/../slaptas",
        "/etc/passwd",
        "memories/x",
        "",
        "/kitas/failas",
    ],
)
def test_uz_atminties_ribu_neiseina(store, kelias):
    """Kelius siūlo modelis — nė vienas neturi pasiekti kitų failų."""
    with pytest.raises(MemoryError):
        store._resolve(kelias)


def test_gilus_kelias_viduje_leidziamas(store):
    store.create(cmd("create", path="/memories/darbas/projektai/x.md", file_text="ok"))
    assert store.files() == [("/memories/darbas/projektai/x.md", 2)]


def test_visas_turinys_zmogui(store):
    store.create(cmd("create", path="/memories/a.md", file_text="faktas"))
    tekstas = store.read_all()
    assert "/memories/a.md" in tekstas and "faktas" in tekstas


def test_nesamo_failo_skaitymas(store):
    with pytest.raises(MemoryError, match="nerastas"):
        store.view(cmd("view", path="/memories/nera.md", view_range=None))


def test_komandos_isvedimas_per_call(store):
    """Modelis kviečia per `call` su žodynu — taip, kaip ateina iš API."""
    assert "įrašyta" in store.call(
        {"command": "create", "path": "/memories/a.md", "file_text": "x"}
    )
