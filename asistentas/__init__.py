"""Asmeninis AI asistentas terminale."""

import sys

__version__ = "0.1.0"

# Žemiau 3.11 neveiks: naudojamas `tomllib` iš standartinės bibliotekos.
MIN_PYTHON = (3, 11)


def check_python(version=None) -> str:
    """Klaidos tekstas, jei Python per senas. Kitaip — tuščia eilutė.

    macOS sisteminis `python3` tebėra 3.9, tad be šio patikrinimo žmogus
    gautų arba `ModuleNotFoundError: tomllib`, arba pip klaidą apie
    `setup.py` — nė viena iš jų nepasako, kas iš tikrųjų negerai.
    """
    version = tuple(version or sys.version_info[:2])[:2]
    if version >= MIN_PYTHON:
        return ""
    return (
        f"asistentas reikia Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} ar naujesnio "
        f"(dabar {version[0]}.{version[1]}).\n"
        "  macOS:  brew install python && exec zsh\n"
        "  paskui: rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -e ."
    )


_problem = check_python()
if _problem:  # pragma: no cover — patikrinta per check_python()
    raise SystemExit(_problem)
