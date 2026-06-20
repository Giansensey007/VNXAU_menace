import os
from unittest.mock import patch

import pytest

from src.vnx.deposits import (
    check_deposit_amount,
    check_usdc_deposit_amount,
    min_deposit_usdc,
    min_deposit_vnxau,
)


def test_base_vnxau_default_minimum_is_5():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VNX_MIN_DEPOSIT_VNXAU_BASE", None)
        assert min_deposit_vnxau("BASE") == 5.0


def test_sol_vnxau_default_minimum_is_5():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VNX_MIN_DEPOSIT_VNXAU_SOL", None)
        assert min_deposit_vnxau("SOL") == 5.0


@pytest.mark.parametrize("blockchain", ["BASE", "SOL"])
@pytest.mark.parametrize("amount", [4.99, 1.0, 0.5])
def test_check_vnxau_deposit_amount_rejects_below_base_sol_minimum(blockchain: str, amount: float):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop(f"VNX_MIN_DEPOSIT_VNXAU_{blockchain}", None)
        err = check_deposit_amount(blockchain, amount)
    assert err is not None
    assert "5.00" in err
    assert "cumulative" in err.lower()


@pytest.mark.parametrize("blockchain", ["BASE", "SOL"])
@pytest.mark.parametrize("amount", [5.0, 5.01, 10.0])
def test_check_vnxau_deposit_amount_accepts_at_or_above_base_sol_minimum(
    blockchain: str, amount: float
):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop(f"VNX_MIN_DEPOSIT_VNXAU_{blockchain}", None)
        assert check_deposit_amount(blockchain, amount) is None


def test_eth_usdc_default_minimum_is_20():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VNX_MIN_DEPOSIT_USDC_ETH", None)
        assert min_deposit_usdc("ETH") == 20.0


def test_min_deposit_usdc_eth_env_override():
    with patch.dict(os.environ, {"VNX_MIN_DEPOSIT_USDC_ETH": "25"}):
        assert min_deposit_usdc("ETH") == 25.0


@pytest.mark.parametrize(
    "amount",
    [19.99, 11.64, 5.0, 0.5],
)
def test_check_usdc_deposit_amount_rejects_below_eth_minimum(amount: float):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VNX_MIN_DEPOSIT_USDC_ETH", None)
        err = check_usdc_deposit_amount("ETH", amount)
    assert err is not None
    assert "20.00" in err
    assert "cumulative" in err.lower()


@pytest.mark.parametrize(
    "amount",
    [20.0, 20.01, 50.0],
)
def test_check_usdc_deposit_amount_accepts_at_or_above_eth_minimum(amount: float):
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VNX_MIN_DEPOSIT_USDC_ETH", None)
        assert check_usdc_deposit_amount("ETH", amount) is None
