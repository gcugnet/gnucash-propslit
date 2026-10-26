import random
from fractions import Fraction

import pytest

from propsplit.split_math import (
    format_amount,
    format_percent,
    from_shares,
    parse_amount,
    parse_percent,
    scale,
    shares,
)


def test_scale_half_half():
    # Compte commun -90 → compagne 45 / courses 45 ; on saisit 110.
    assert scale([-9000, 4500, 4500], 0, -11000) == [-11000, 5500, 5500]


def test_scale_odd_cent_goes_to_first_on_tie():
    assert scale([-1000, 500, 500], 0, -1001) == [-1001, 501, 500]


def test_scale_anchor_not_first():
    assert scale([4500, -9000, 4500], 1, -11000) == [5500, -11000, 5500]


def test_scale_three_way():
    result = scale([-3000, 1000, 1000, 1000], 0, -10000)
    assert result == [-10000, 3334, 3333, 3333]


def test_scale_cent_goes_to_largest_remainder():
    # 70/30 sur 10,01 : 7,007 → 7,01 et 3,003 → 3,00 ; la somme tombe juste.
    assert scale([-1000, 700, 300], 0, -1001) == [-1001, 701, 300]


def test_scale_mixed_signs():
    # Une remise dans la transaction modèle garde son signe.
    result = scale([-9000, 10000, -1000], 0, -18000)
    assert result == [-18000, 20000, -2000]


def test_scale_two_splits_matches_gnucash_behaviour():
    assert scale([-2550, 2550], 0, -3999) == [-3999, 3999]


def test_scale_random_always_balanced():
    rng = random.Random(42)
    for _ in range(2000):
        counterparts = [rng.randint(1, 50000) for _ in range(rng.randint(1, 5))]
        values = [-sum(counterparts)] + counterparts
        new = -rng.randint(1, 100000)
        result = scale(values, 0, new)
        assert sum(result) == 0
        assert result[0] == new
        assert all(r >= 0 for r in result[1:])


def test_scale_rejects_zero_anchor():
    with pytest.raises(ValueError, match="nul"):
        scale([0, 100, -100], 0, -500)


def test_scale_rejects_unbalanced_template():
    with pytest.raises(ValueError, match="équilibrée"):
        scale([-9000, 4500], 0, -100)


def test_shares():
    assert shares([-9000, 4500, 4500], 0) == [-1, Fraction(1, 2), Fraction(1, 2)]


def test_from_shares_half_half():
    assert from_shares(-1001, [Fraction(1, 2), Fraction(1, 2)]) == [-1001, 501, 500]


def test_from_shares_rejects_incomplete():
    with pytest.raises(ValueError, match="100 %"):
        from_shares(-1000, [Fraction(1, 2), Fraction(1, 4)])


@pytest.mark.parametrize(
    "text, expected",
    [("110", 11000), ("12,5", 1250), ("1 234.56", 123456), ("0,01", 1), ("-3", -300)],
)
def test_parse_amount(text, expected):
    assert parse_amount(text, 100) == expected


@pytest.mark.parametrize("text", ["abc", "1,234", ""])
def test_parse_amount_rejects(text):
    with pytest.raises(ValueError):
        parse_amount(text, 100)


def test_parse_percent():
    assert parse_percent("50") == Fraction(1, 2)
    assert parse_percent("33,33 %") == Fraction(3333, 10000)


def test_format():
    assert format_amount(-123450, 100) == "-1 234,50"
    assert format_amount(5, 100) == "0,05"
    assert format_amount(7, 1) == "7"
    assert format_percent(Fraction(1, 2)) == "50 %"
    assert format_percent(Fraction(1, 3)) == "33,33 %"
