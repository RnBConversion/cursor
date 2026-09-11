"""Lietuviški skaičiai ir daugiskaita.

„1 paieška", „2 paieškos", „11 paieškų" — kitaip įrankis skamba verstinis.
"""

from __future__ import annotations


def plural(n: int, one: str, few: str, many: str) -> str:
    """Parenka formą pagal lietuvių kalbos taisyklę."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one          # 1, 21, 31 ... paieška
    if 2 <= n % 10 <= 9 and not 11 <= n % 100 <= 19:
        return few          # 2-9, 22-29 ... paieškos
    return many             # 0, 10-20, 11-19 ... paieškų


def number(n: int) -> str:
    """Tūkstančiai atskiriami tarpu: 2 316."""
    return f"{int(n):,}".replace(",", " ")


def count(n: int, one: str, few: str, many: str) -> str:
    return f"{number(n)} {plural(n, one, few, many)}"


def tokens(n: int) -> str:
    return count(n, "žetonas", "žetonai", "žetonų")


def searches(n: int) -> str:
    return count(n, "paieška", "paieškos", "paieškų")


def questions(n: int) -> str:
    return count(n, "klausimas", "klausimai", "klausimų")
