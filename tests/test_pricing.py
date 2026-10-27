import pytest

from hiremarco.meta.pricing import PRICES_PER_MILLION, cost_usd


def test_muse_spark_13_standard_prices():
    # 1M fresh input + 1M output at the 2026-10-26 table
    assert cost_usd("muse-spark-1.3", 1_000_000, 1_000_000) == pytest.approx(1.25 + 4.25)


def test_cached_tokens_are_cheaper_and_bounded():
    full = cost_usd("muse-spark-1.3", 1000, 0)
    cached = cost_usd("muse-spark-1.3", 1000, 0, cached_tokens=1000)
    over = cost_usd("muse-spark-1.3", 1000, 0, cached_tokens=5000)
    assert cached < full
    assert over == cached


def test_unpriced_model_is_a_defect():
    with pytest.raises(KeyError):
        cost_usd("muse-unknown", 1, 1)


def test_every_table_row_has_three_prices():
    for model, prices in PRICES_PER_MILLION.items():
        assert len(prices) == 3, model
