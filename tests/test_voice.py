import subprocess
import sys
import time
from pathlib import Path

import pytest

from asistentas.config import Voice
from asistentas.voice import (
    CommandTranscriber,
    FasterWhisperTranscriber,
    Recorder,
    VoiceError,
    VoiceInput,
    WhisperCppTranscriber,
    pick_transcriber,
    wait_for_enter,
)

# ---- netikri binarai: leidžia patikrinti visą grandinę be mikrofono -----


def _script(path: Path, body: str) -> Path:
    path.write_text(f"#!/usr/bin/env python3\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def fake_bin(tmp_path, monkeypatch):
    """Katalogas su netikrais `rec` ir `stt`, įdėtas į PATH."""
    binai = tmp_path / "bin"
    binai.mkdir()
    _script(
        binai / "fake-rec",
        "import sys, signal, time\n"
        "out = sys.argv[-1]\n"
        "open(out, 'wb').write(b'RIFF' + b'\\0' * 4000)\n"
        "signal.signal(signal.SIGINT, lambda *a: sys.exit(0))\n"
        "while True: time.sleep(0.02)\n",
    )
    _script(
        binai / "fake-tyla",
        "import sys, signal, time\n"
        "open(sys.argv[-1], 'wb').write(b'RIFF')\n"          # per mažas failas
        "signal.signal(signal.SIGINT, lambda *a: sys.exit(0))\n"
        "while True: time.sleep(0.02)\n",
    )
    _script(
        binai / "fake-luzta",
        "import sys\nsys.stderr.write('nerastas garso įrenginys\\n')\nsys.exit(1)\n",
    )
    _script(binai / "fake-stt", "print('labas rytas')\n")
    _script(binai / "fake-stt-luzta", "import sys\nsys.stderr.write('modelio nėra\\n')\nsys.exit(2)\n")
    monkeypatch.setenv("PATH", f"{binai}:{__import__('os').environ['PATH']}")
    return binai


def settings(**kw) -> Voice:
    return Voice(**{"recorder": "fake-rec", "language": "lt", **kw})


# ---- įrašymo programos parinkimas --------------------------------------


def test_randa_pirma_esama(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x" if name == "arecord" else None)
    assert Recorder("auto").name == "arecord"


def test_nieko_neranda(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    r = Recorder("auto")
    assert r.name is None and r.available is False
    with pytest.raises(VoiceError, match="nerasta"):
        r.argv(Path("/tmp/a.wav"))


def test_nurodyta_programa_gerbiama(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x")
    assert Recorder("ffmpeg").name == "ffmpeg"


def test_irasymo_argumentai(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x")
    argv = Recorder("rec").argv(Path("/tmp/a.wav"))
    assert argv[0] == "rec" and "16000" in argv and argv[-1] == "/tmp/a.wav"
    assert Recorder("arecord").argv(Path("/tmp/a.wav"))[0] == "arecord"


@pytest.mark.parametrize(
    "platforma, saltinis", [("darwin", "avfoundation"), ("linux", "alsa")]
)
def test_ffmpeg_pagal_sistema(monkeypatch, platforma, saltinis):
    """macOS ir Linux garso posistemės skiriasi."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x")
    monkeypatch.setattr(sys, "platform", platforma)
    argv = Recorder("ffmpeg").argv(Path("/tmp/a.wav"))
    assert saltinis in argv
    assert "-nostdin" in argv      # kitaip ffmpeg suvalgytų klaviatūrą


def test_sava_irasymo_komanda(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x")
    argv = Recorder("mano-irasiklis --tyliai").argv(Path("/tmp/a.wav"))
    assert argv == ["mano-irasiklis", "--tyliai", "/tmp/a.wav"]


# ---- atpažinimo varikliai ----------------------------------------------


def test_komandos_pakaitalai():
    argv = CommandTranscriber("stt --lang {kalba} {failas}").argv(Path("/tmp/su tarpu.wav"), "lt")
    assert argv == ["stt", "--lang", "lt", "/tmp/su tarpu.wav"]   # tarpai nesuardo


def test_tuscia_komanda():
    with pytest.raises(VoiceError, match="nenurodyta"):
        CommandTranscriber("  ").argv(Path("/tmp/a.wav"), "lt")


def test_whisper_cpp_argumentai():
    t = WhisperCppTranscriber("whisper-cli", Path("/m/ggml.bin"))
    argv = t.argv(Path("/tmp/a.wav"), "lt", Path("/tmp/a"))
    assert argv[:3] == ["whisper-cli", "-m", "/m/ggml.bin"]
    assert "-l" in argv and "lt" in argv and "-otxt" in argv


def test_whisper_cpp_auto_kalba():
    argv = WhisperCppTranscriber("whisper-cli", Path("/m.bin")).argv(Path("/a.wav"), "auto", Path("/a"))
    assert "-l" not in argv     # tegu nustato pats


def test_whisper_cpp_binaro_paieska(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x" if name == "whisper-cpp" else None)
    assert WhisperCppTranscriber.find_binary("nera-tokio") == "whisper-cpp"
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert WhisperCppTranscriber.find_binary("") is None


def test_faster_whisper_neidiegtas():
    assert FasterWhisperTranscriber.importable() is False


# ---- variklio parinkimas ------------------------------------------------


def test_parenka_komanda_jei_nurodyta():
    t = pick_transcriber(settings(command="stt {failas}"))
    assert isinstance(t, CommandTranscriber)


def test_parenka_whisper_cpp(monkeypatch, tmp_path):
    modelis = tmp_path / "ggml.bin"
    modelis.write_bytes(b"x")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x" if name == "whisper-cli" else None)
    t = pick_transcriber(settings(whisper_model=str(modelis)))
    assert isinstance(t, WhisperCppTranscriber)


def test_nieko_neidiegta():
    assert pick_transcriber(settings()) is None


def test_aiskiai_nurodytas_variklis_be_irangos():
    assert pick_transcriber(settings(engine="whisper.cpp")) is None
    assert pick_transcriber(settings(engine="faster-whisper")) is None


# ---- visa grandinė su netikrais binarais --------------------------------


def test_pilnas_kelias_nuo_mikrofono_iki_teksto(fake_bin):
    voice = VoiceInput(
        settings(),
        transcriber=CommandTranscriber("fake-stt {failas} {kalba}"),
    )
    assert voice.ready is True
    assert voice.capture(wait=lambda: None) == "labas rytas"


def test_irasas_istrinamas_po_atpazinimo(fake_bin):
    matytas = {}

    class Sekantis:
        name = "test"

        def transcribe(self, path, language):
            matytas["kelias"] = Path(path)
            assert path.exists()            # atpažinimo metu dar yra
            return "tekstas"

    VoiceInput(settings(), transcriber=Sekantis()).capture(wait=lambda: None)
    assert not matytas["kelias"].exists()   # po to — nebėra
    assert not matytas["kelias"].parent.exists()


def test_tyla_negrazina_teksto(fake_bin):
    """Nieko nepasakius atpažinimo net nekviečiame — tai kainuoja laiką."""
    class NiekadaNekviečiamas:
        name = "test"

        def transcribe(self, path, language):
            raise AssertionError("neturėjo būti kviečiamas")

    voice = VoiceInput(settings(recorder="fake-tyla"), transcriber=NiekadaNekviečiamas())
    assert voice.capture(wait=lambda: None) == ""


def test_irasymo_klaida_pastebima_is_karto(fake_bin):
    """Jei mikrofonas užimtas, sužinai tuoj pat — o ne prakalbėjęs minutę."""
    def neturi_buti_kvieciamas():
        raise AssertionError("laukėme vartotojo, nors įrašymas jau nulūžo")

    voice = VoiceInput(
        settings(recorder="fake-luzta"), transcriber=CommandTranscriber("fake-stt {failas}")
    )
    with pytest.raises(VoiceError, match="garso įrenginys"):
        voice.capture(wait=neturi_buti_kvieciamas)


def test_kalbek_rodoma_tik_atsidarius_mikrofonui(fake_bin):
    """„Kalbėk" anksčiau laiko reikštų prarastą pirmą žodį."""
    eiga = []
    voice = VoiceInput(settings(), transcriber=CommandTranscriber("fake-stt {failas}"))
    voice.capture(
        wait=lambda: eiga.append("laukiam"),
        on_start=lambda: eiga.append("kalbėk"),
        on_transcribe=lambda: eiga.append("atpažįstu"),
    )
    assert eiga == ["kalbėk", "laukiam", "atpažįstu"]


def test_atpazinimo_klaida_paaiskinama(fake_bin):
    voice = VoiceInput(settings(), transcriber=CommandTranscriber("fake-stt-luzta {failas}"))
    with pytest.raises(VoiceError, match="modelio nėra"):
        voice.capture(wait=lambda: None)


def test_nezinoma_programa(fake_bin):
    voice = VoiceInput(settings(), transcriber=CommandTranscriber("nera-tokios-programos {failas}"))
    with pytest.raises(VoiceError, match="nerasta programa"):
        voice.capture(wait=lambda: None)


def test_nutraukus_irasymas_sustabdomas(fake_bin):
    """Ctrl+C metu įrašymo procesas neturi likti veikti fone."""
    procesai = []
    voice = VoiceInput(settings(), transcriber=CommandTranscriber("fake-stt {failas}"))
    tikras_start = voice.recorder.start

    def sekti(path):
        p = tikras_start(path)
        procesai.append(p)
        return p

    voice.recorder.start = sekti

    def nutraukti():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        voice.capture(wait=nutraukti)
    assert procesai and procesai[0].poll() is not None


def test_neparuosta_grandine_pasako_ko_truksta(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    voice = VoiceInput(Voice())
    assert voice.ready is False
    problemos = " ".join(voice.problems())
    assert "įrašymo" in problemos and "faster-whisper" in problemos
    with pytest.raises(VoiceError):
        voice.capture(wait=lambda: None)


# ---- laukimas -----------------------------------------------------------


def test_laukimas_baigiasi_pagal_laika():
    pradzia = time.monotonic()
    wait_for_enter(1)
    assert 0.5 < time.monotonic() - pradzia < 3


def test_laukimas_baigiasi_paspaudus_enter(monkeypatch, tmp_path):
    ivestis = tmp_path / "stdin"
    ivestis.write_text("\n", encoding="utf-8")
    with ivestis.open() as f:
        monkeypatch.setattr(sys, "stdin", f)
        pradzia = time.monotonic()
        wait_for_enter(30)
        assert time.monotonic() - pradzia < 2      # negrįžo laukti 30 s
