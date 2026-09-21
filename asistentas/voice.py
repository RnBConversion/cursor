"""Balso įvestis: įrašo, ką pasakei, ir paverčia tekstu.

Du nepriklausomi dalykai, kurių reikia tavo kompiuteryje:

  1. įrašymo programa — sox (`rec`), arecord, pw-record arba ffmpeg;
  2. atpažinimo variklis — faster-whisper (paprasčiausia), whisper.cpp
     arba bet kokia tavo komanda.

Nė vienas jų nėra šio projekto priklausomybė: ko nėra, to ir neprašome,
o `/balsas` pasako, ko konkrečiai trūksta ir kaip įsidiegti.

Garsas niekur nekeliauja: įrašas guli laikiname faile, atpažįstamas tavo
kompiuteryje ir iš karto ištrinamas. Į Anthropic API išeina tik tekstas.
"""

from __future__ import annotations

import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

RATE = "16000"          # Whisper modeliai dirba su 16 kHz mono
MIN_WAV_BYTES = 2000    # mažesnis failas — tyla arba nepavykęs įrašas
STOP_GRACE = 5          # kiek laukti, kol įrašymo programa tvarkingai baigs
START_GRACE = 3.0       # kiek laukti, kol mikrofonas realiai atsidarys
TRANSCRIBE_TIMEOUT = 600


class VoiceError(Exception):
    """Klaida, kurią rodome vartotojui lietuviškai."""


# ---- įrašymas ----------------------------------------------------------


def _ffmpeg_argv(path: Path) -> list[str]:
    # Garso šaltinis skiriasi pagal sistemą: macOS — avfoundation, Linux — ALSA.
    if sys.platform == "darwin":
        source, device = "avfoundation", ":0"
    else:
        source, device = "alsa", "default"
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", source, "-i", device, "-ar", RATE, "-ac", "1", "-y", str(path),
    ]


RECORDERS: dict[str, object] = {
    "rec": lambda p: ["rec", "-q", "-r", RATE, "-c", "1", "-b", "16", str(p)],
    "sox": lambda p: ["sox", "-d", "-q", "-r", RATE, "-c", "1", "-b", "16", str(p)],
    "arecord": lambda p: ["arecord", "-q", "-f", "S16_LE", "-r", RATE, "-c", "1", str(p)],
    "pw-record": lambda p: ["pw-record", "--rate", RATE, "--channels", "1", str(p)],
    "ffmpeg": _ffmpeg_argv,
}

# Eilės tvarka: pirma paprasčiausi, ffmpeg — paskutinis (jam reikia žinoti
# sistemos garso posistemę).
RECORDER_ORDER = ("rec", "sox", "arecord", "pw-record", "ffmpeg")

INSTALL_HINTS = {
    "darwin": "brew install sox",
    "linux": "sudo apt install sox   (arba: dnf install sox)",
}


class Recorder:
    """Paleidžia įrašymo programą ir tvarkingai ją sustabdo."""

    def __init__(self, name: str = "auto"):
        self.name = self._pick(name)

    @staticmethod
    def _pick(name: str) -> str | None:
        if name and name != "auto":
            return name if shutil.which(name.split()[0]) else None
        for candidate in RECORDER_ORDER:
            if shutil.which(candidate):
                return candidate
        return None

    @property
    def available(self) -> bool:
        return self.name is not None

    def argv(self, path: Path) -> list[str]:
        if self.name is None:
            raise VoiceError("įrašymo programos nerasta")
        builder = RECORDERS.get(self.name)
        if builder is None:
            # Nežinoma programa iš nustatymų — perduodame kaip yra.
            return [*shlex.split(self.name), str(path)]
        return builder(path)  # type: ignore[operator]

    def start(self, path: Path) -> subprocess.Popen:
        # stdin uždaromas sąmoningai: ffmpeg antraip suvalgytų klaviatūrą,
        # ir „Enter — baigti" nustotų veikti.
        return subprocess.Popen(
            self.argv(path),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def stop(self, process: subprocess.Popen) -> None:
        """SIGINT, kad programa spėtų užbaigti WAV antraštę."""
        if process.poll() is not None:
            return
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                process.send_signal(sig)
                process.wait(timeout=STOP_GRACE)
                return
            except subprocess.TimeoutExpired:
                continue
            except (ProcessLookupError, OSError):
                return
        process.kill()
        try:
            process.wait(timeout=STOP_GRACE)
        except subprocess.TimeoutExpired:
            pass


# ---- atpažinimas -------------------------------------------------------


WHISPER_CPP_BINARIES = ("whisper-cli", "whisper-cpp", "whisper.cpp", "main")


@dataclass
class CommandTranscriber:
    """Bet kokia tavo komanda: {failas} ir {kalba} pakeičiami."""

    template: str
    name: str = "komanda"

    def argv(self, path: Path, language: str) -> list[str]:
        if not self.template.strip():
            raise VoiceError("balso komanda nenurodyta")
        return [
            token.replace("{failas}", str(path)).replace("{kalba}", language)
            for token in shlex.split(self.template)
        ]

    def transcribe(self, path: Path, language: str) -> str:
        done = _run(self.argv(path, language))
        return done.stdout.strip()


@dataclass
class WhisperCppTranscriber:
    """whisper.cpp — greita ir be Python priklausomybių."""

    binary: str
    model: Path
    name: str = "whisper.cpp"

    @staticmethod
    def find_binary(preferred: str = "") -> str | None:
        for candidate in (preferred, *WHISPER_CPP_BINARIES):
            if candidate and shutil.which(candidate):
                return candidate
        return None

    def argv(self, path: Path, language: str, prefix: Path) -> list[str]:
        argv = [self.binary, "-m", str(self.model), "-f", str(path), "-nt",
                "-otxt", "-of", str(prefix)]
        if language and language != "auto":
            argv += ["-l", language]
        return argv

    def transcribe(self, path: Path, language: str) -> str:
        prefix = path.with_suffix("")
        _run(self.argv(path, language, prefix))
        result = prefix.with_suffix(".txt")
        if not result.exists():
            raise VoiceError("whisper.cpp negrąžino teksto")
        return result.read_text(encoding="utf-8", errors="replace").strip()


@dataclass
class FasterWhisperTranscriber:
    """faster-whisper — `pip install faster-whisper`, modelis parsiunčiamas pats."""

    model_name: str = "large-v3"
    name: str = "faster-whisper"

    def __post_init__(self):
        self._model = None

    @staticmethod
    def importable() -> bool:
        from importlib.util import find_spec

        try:
            return find_spec("faster_whisper") is not None
        except (ImportError, ValueError):
            return False

    def transcribe(self, path: Path, language: str) -> str:
        if self._model is None:
            from faster_whisper import WhisperModel

            # Modelis lieka atmintyje — antras klausimas atpažįstamas greičiau.
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        segments, _info = self._model.transcribe(
            str(path), language=None if language == "auto" else language
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=TRANSCRIBE_TIMEOUT
        )
    except FileNotFoundError as e:
        raise VoiceError(f"nerasta programa `{argv[0]}`") from e
    except subprocess.TimeoutExpired as e:
        raise VoiceError("atpažinimas užtruko per ilgai") from e
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        raise VoiceError(f"{argv[0]}: {detail[-1] if detail else 'klaida'}")
    return done


def pick_transcriber(settings) -> object | None:
    """Parenka variklį pagal nustatymus arba pagal tai, kas įdiegta."""
    engine = (settings.engine or "auto").lower()
    model = Path(settings.whisper_model).expanduser() if settings.whisper_model else None

    if engine in ("komanda", "command"):
        return CommandTranscriber(settings.command)
    if engine in ("whisper.cpp", "whisper-cpp", "whispercpp"):
        binary = WhisperCppTranscriber.find_binary(settings.whisper_binary)
        if binary and model:
            return WhisperCppTranscriber(binary, model)
        return None
    if engine in ("faster-whisper", "faster_whisper"):
        return FasterWhisperTranscriber(settings.model) if FasterWhisperTranscriber.importable() else None

    if settings.command.strip():
        return CommandTranscriber(settings.command)
    binary = WhisperCppTranscriber.find_binary(settings.whisper_binary)
    if binary and model and model.exists():
        return WhisperCppTranscriber(binary, model)
    if FasterWhisperTranscriber.importable():
        return FasterWhisperTranscriber(settings.model)
    return None


def _await_start(process: subprocess.Popen, audio: Path, timeout: float = START_GRACE) -> None:
    """Laukia, kol įrašymo programa pradės rašyti failą arba nulūš."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return
        try:
            if audio.exists() and audio.stat().st_size > 0:
                return
        except OSError:
            pass
        time.sleep(0.02)


def _stderr_tail(process: subprocess.Popen) -> str:
    """Paskutinė klaidos eilutė iš jau pasibaigusio proceso."""
    if process.stderr is None or process.poll() is None:
        return ""
    try:
        text = process.stderr.read().decode("utf-8", "replace").strip()
    except (OSError, ValueError):
        return ""
    return text.splitlines()[-1] if text else ""


def wait_for_enter(max_seconds: int) -> None:
    """Laukia Enter paspaudimo arba kol baigsis laikas.

    Per `select`, o ne `input()`: kitaip įrašymo nebūtų galima nutraukti
    laiku ir ilgas kalbėjimas užrakintų terminalą.
    """
    import select
    import time

    deadline = time.monotonic() + max_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        try:
            ready, _, _ = select.select([sys.stdin], [], [], min(remaining, 0.5))
        except (OSError, ValueError):  # stdin ne failas (pvz. testuose)
            time.sleep(min(remaining, 0.2))
            continue
        if ready:
            sys.stdin.readline()
            return


# ---- viskas kartu ------------------------------------------------------


class VoiceInput:
    """Įrašo ir atpažįsta vieną pasakymą."""

    def __init__(self, settings, recorder=None, transcriber=None):
        self.settings = settings
        self.recorder = recorder if recorder is not None else Recorder(settings.recorder)
        self._transcriber = transcriber if transcriber is not None else pick_transcriber(settings)

    @property
    def transcriber(self):
        return self._transcriber

    @property
    def ready(self) -> bool:
        return self.recorder.available and self._transcriber is not None

    def problems(self) -> list[str]:
        """Ko trūksta — su konkrečia įdiegimo komanda."""
        missing = []
        if not self.recorder.available:
            hint = INSTALL_HINTS.get(sys.platform, INSTALL_HINTS["linux"])
            missing.append(f"įrašymo programos (sox, arecord arba ffmpeg) — {hint}")
        if self._transcriber is None:
            missing.append("atpažinimo variklio — pip install faster-whisper")
        return missing

    def capture(self, wait, on_start=None, on_transcribe=None) -> str:
        """Įrašo, kol `wait()` grįžta, ir grąžina atpažintą tekstą."""
        if not self.ready:
            raise VoiceError("; ".join(self.problems()))

        with tempfile.TemporaryDirectory(prefix="asistentas-balsas-") as tmp:
            audio = Path(tmp) / "iraso.wav"
            process = self.recorder.start(audio)
            try:
                # Kviesti „kalbėk" anksčiau, nei atsidaro mikrofonas, reikštų
                # prarastą pirmą žodį: sox ir ffmpeg pasileidžia ne iš karto.
                _await_start(process, audio)
                if process.poll() is not None:
                    raise VoiceError(f"įrašymas nepavyko: {_stderr_tail(process)}")
                if on_start:
                    on_start()
                wait()
            finally:
                self.recorder.stop(process)

            if audio.exists() and audio.stat().st_size >= MIN_WAV_BYTES and on_transcribe:
                on_transcribe()
            if not audio.exists() or audio.stat().st_size < MIN_WAV_BYTES:
                if process.returncode not in (0, -signal.SIGINT, -signal.SIGTERM):
                    tail = _stderr_tail(process)
                    if tail:
                        raise VoiceError(f"įrašymas nepavyko: {tail}")
                return ""
            return self._transcriber.transcribe(audio, self.settings.language)
