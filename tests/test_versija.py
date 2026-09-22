from asistentas import MIN_PYTHON, check_python


def test_naujas_python_tinka():
    assert check_python((3, 11)) == ""
    assert check_python((3, 13)) == ""
    assert check_python((4, 0)) == ""


def test_senas_python_paaiskinamas_zmoniskai():
    """macOS sisteminis python3 tebėra 3.9 — tai dažniausia diegimo kliūtis."""
    klaida = check_python((3, 9))
    assert "3.9" in klaida and "3.11" in klaida
    assert "brew install python" in klaida     # pasakome, ką daryti
    assert "venv" in klaida


def test_tikrina_ir_ilgesni_version_info():
    assert check_python((3, 9, 6, "final", 0)) != ""
    assert MIN_PYTHON == (3, 11)
