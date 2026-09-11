import pytest

from asistentas import lt


@pytest.mark.parametrize(
    "n, laukiama",
    [
        (0, "0 paieškų"),
        (1, "1 paieška"),
        (2, "2 paieškos"),
        (9, "9 paieškos"),
        (10, "10 paieškų"),
        (11, "11 paieškų"),
        (19, "19 paieškų"),
        (20, "20 paieškų"),
        (21, "21 paieška"),
        (22, "22 paieškos"),
        (101, "101 paieška"),
        (111, "111 paieškų"),
        (1000, "1 000 paieškų"),
    ],
)
def test_daugiskaita(n, laukiama):
    assert lt.searches(n) == laukiama


def test_zetonai_ir_klausimai():
    assert lt.tokens(1) == "1 žetonas"
    assert lt.tokens(2316) == "2 316 žetonų"
    assert lt.questions(3) == "3 klausimai"


def test_skaiciaus_formatas():
    assert lt.number(1234567) == "1 234 567"
