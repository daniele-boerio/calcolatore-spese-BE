"""I soldi sul BE sono `Decimal` quantizzati a 2 decimali (vedi BE/CLAUDE.md).

Questi test bloccano quel contratto sugli schemi dei conti: ogni importo che
entra viene arrotondato al centesimo, i campi opzionali None restano None.
"""

from decimal import Decimal

import pytest

from schemas.conto import ContoBase, ContoUpdate


def _conto(**kwargs) -> ContoBase:
    data = {"nome": "Test", "saldo": "0.00"}
    data.update(kwargs)
    return ContoBase(**data)


class TestContoMoneyQuantization:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("10.1", "10.10"),
            ("7", "7.00"),
            ("10.999", "11.00"),  # arrotonda al centesimo superiore
            ("2.344", "2.34"),  # arrotonda al centesimo inferiore
            ("-2.5", "-2.50"),
        ],
    )
    def test_saldo_quantized_to_two_decimals(self, raw, expected):
        c = _conto(saldo=raw)
        assert c.saldo == Decimal(expected)
        # Esattamente due cifre decimali.
        assert c.saldo.as_tuple().exponent == -2

    def test_optional_money_fields_none_stay_none(self):
        c = _conto(saldo="1.00", budget_obiettivo=None, soglia_minima=None)
        assert c.budget_obiettivo is None
        assert c.soglia_minima is None

    def test_optional_money_field_quantized_when_present(self):
        c = _conto(saldo="1.00", budget_obiettivo="99.9")
        assert c.budget_obiettivo == Decimal("99.90")
        assert c.budget_obiettivo.as_tuple().exponent == -2


class TestContoUpdateMoneyQuantization:
    def test_unset_saldo_is_none(self):
        u = ContoUpdate(nome="X")
        assert u.saldo is None

    def test_saldo_quantized(self):
        u = ContoUpdate(saldo="15.5")
        assert u.saldo == Decimal("15.50")
        assert u.saldo.as_tuple().exponent == -2
