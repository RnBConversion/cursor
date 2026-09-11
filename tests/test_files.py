import pytest

from asistentas.files import FileTools, FileToolError


@pytest.fixture
def uzrasai(tmp_path):
    root = tmp_path / "uzrasai"
    (root / "darbas").mkdir(parents=True)
    (root / "receptai.md").write_text("# Cepelinai\nBulvės ir mėsa.\n", encoding="utf-8")
    (root / "darbas" / "planas.md").write_text("Projektas X\nTerminas: spalio 1 d.\n", encoding="utf-8")
    (root / ".slaptas").mkdir()
    (root / ".slaptas" / "raktas.txt").write_text("nerodyti", encoding="utf-8")
    (tmp_path / "kitur.txt").write_text("ne tavo reikalas", encoding="utf-8")
    return root


@pytest.fixture
def tools(uzrasai):
    return FileTools([uzrasai])


def test_be_katalogu_irankiu_nera(tmp_path):
    tuscias = FileTools([])
    assert tuscias.enabled is False
    assert tuscias.definitions() == []
    assert tuscias.handles("read_file") is False


def test_nesamas_katalogas_praleidziamas(tmp_path, uzrasai):
    t = FileTools([uzrasai, tmp_path / "neprijungtas-diskas"])
    assert t.enabled is True and len(t.roots) == 1
    assert len(t.configured) == 2      # bet nustatymuose matomi abu


def test_aprasai_pasako_kur_leidziama(tools, uzrasai):
    aprasai = tools.definitions()
    assert [d["name"] for d in aprasai] == ["list_files", "search_files", "read_file"]
    assert str(uzrasai) in aprasai[0]["description"]


def test_sarasas(tools):
    isvestis = tools.list_files()
    assert "receptai.md" in isvestis and "darbas/planas.md" in isvestis
    assert "raktas.txt" not in isvestis     # paslėpti katalogai praleidžiami


def test_sarasas_su_sablonu(tools):
    assert "receptai.md" in tools.list_files(pattern="*.md")
    assert "(failų nerasta)" == tools.list_files(pattern="*.pdf")


def test_paieska(tools):
    rezultatas = tools.search_files("terminas")
    assert "darbas/planas.md:2" in rezultatas
    assert "spalio 1 d." in rezultatas


def test_paieska_neranda(tools):
    assert "nieko nerasta" in tools.search_files("vienaragis")


def test_tuscia_uzklausa(tools):
    with pytest.raises(FileToolError, match="tuščia"):
        tools.search_files("   ")


def test_skaitymas(tools):
    assert "Cepelinai" in tools.read_file("receptai.md")


def test_skaitymas_puslapiais(uzrasai):
    (uzrasai / "ilgas.txt").write_text("\n".join(f"eilute {i}" for i in range(1, 1001)), encoding="utf-8")
    tools = FileTools([uzrasai])
    pirmas = tools.read_file("ilgas.txt")
    assert "eilute 1" in pirmas and "eilute 999" not in pirmas
    assert "start_line=401" in pirmas
    antras = tools.read_file("ilgas.txt", start_line=401)
    assert "eilute 401" in antras


def test_didelis_failas_neskaitomas(uzrasai):
    (uzrasai / "didelis.txt").write_text("x" * 5000, encoding="utf-8")
    tools = FileTools([uzrasai], max_file_bytes=1000)
    with pytest.raises(FileToolError, match="per didelis"):
        tools.read_file("didelis.txt")


def test_dvejetainis_failas_neskaitomas(uzrasai):
    (uzrasai / "paveiksliukas.png").write_bytes(b"\x89PNG\x00\x00binary")
    with pytest.raises(FileToolError, match="dvejetainis"):
        FileTools([uzrasai]).read_file("paveiksliukas.png")


def test_katalogo_neskaitome(tools):
    with pytest.raises(FileToolError, match="katalogas"):
        tools.read_file("darbas")


@pytest.mark.parametrize(
    "kelias",
    ["/etc/passwd", "../kitur.txt", "../../etc/hosts", "~/.ssh/id_rsa", "darbas/../../kitur.txt"],
)
def test_uz_katalogu_ribu_neiseina(tools, kelias):
    """Kelią siūlo modelis — jis neturi pasiekti nieko, ko neleidai."""
    with pytest.raises(FileToolError, match="nepasiekiamas"):
        tools.read_file(kelias)


def test_simbolines_nuorodos_neapgauna(tmp_path, uzrasai):
    (uzrasai / "nuoroda").symlink_to(tmp_path / "kitur.txt")
    with pytest.raises(FileToolError, match="nepasiekiamas"):
        FileTools([uzrasai]).read_file("nuoroda")


def test_paieska_nezvelgia_i_dvejetainius(uzrasai):
    (uzrasai / "duomenys.bin").write_bytes(b"\x00terminas\x00")
    assert "duomenys.bin" not in FileTools([uzrasai]).search_files("terminas")


def test_vykdymas_per_bendra_ijeiga(tools):
    assert "Cepelinai" in tools.call("read_file", {"path": "receptai.md"})
    assert "planas.md" in tools.call("list_files", {})
    with pytest.raises(FileToolError, match="nežinomas"):
        tools.call("kazkas", {})


def test_paaiskinimas_vartotojui(tools):
    assert "receptai.md" in tools.describe("read_file", {"path": "receptai.md"})
    assert "kava" in tools.describe("search_files", {"query": "kava"})
