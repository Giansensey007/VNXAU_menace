"""Tests for one-time infinite approvals (no per-trade approve in swap hot path)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from src.execution.token_approvals import (
    MAX_UINT256,
    check_allowance,
    collect_approval_targets,
    is_infinite_allowance,
)
from src.config_loader import load_bridge_config, load_chains, load_tokens


def test_is_infinite_allowance():
    assert is_infinite_allowance(MAX_UINT256)
    assert not is_infinite_allowance(10**18)


def test_check_allowance_ok_when_max():
    w3 = MagicMock()
    w3.eth.contract.return_value.functions.allowance.return_value.call.return_value = MAX_UINT256
    assert check_allowance(w3, "0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40, 10**18) is None


def test_base_swap_does_not_call_approve_when_allowance_max():
    os.environ["BASE_PRIVATE_KEY"] = "0x" + "11" * 32
    from src.execution.base import BaseExecutor

    mock_w3 = MagicMock()
    mock_w3.is_connected.return_value = True
    mock_w3.eth.get_transaction_count.return_value = 0
    mock_w3.eth.gas_price = 1
    mock_router = MagicMock()
    mock_w3.eth.contract.side_effect = lambda address, abi: (
        mock_router if "exactInput" in str(abi) else MagicMock()
    )
    mock_router.functions.exactInputSingle.return_value.build_transaction.return_value = {"to": "0xrouter"}

    with patch("src.execution.base.connect_base_web3", return_value=mock_w3):
        with patch("src.execution.token_approvals.check_allowance", return_value=None) as mock_check:
            ex = BaseExecutor(load_chains()["base"])
            ex._build_and_send = MagicMock(return_value="0xswap")
            ex.swap_exact_input(
                "0x" + "a" * 40,
                "0x" + "b" * 40,
                10**18,
                1,
            )
    mock_check.assert_called_once()


def test_collect_approval_targets_vnxau():
    chains = load_chains()
    token = load_tokens()["VNXAU"]
    bridge = load_bridge_config()
    targets = collect_approval_targets(chains, token, bridge)
    eth_targets = [t for t in targets if t.chain_key == "ethereum"]
    assert any("Kyber" in t.label for t in eth_targets)
    assert any(t.token == token.chains["ethereum"] for t in eth_targets)
