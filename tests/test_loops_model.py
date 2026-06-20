"""Platform-first loop model: same-asset round trips (Loop 1/2/3).

VNXAU special case: ETH is itself a trading chain, so Loop 1/Loop 2 with the ETH
leg need no hub bridge (USDC already settles on ETH).
"""

from __future__ import annotations

from src.config_loader import TokenConfig
from src.scanner.routes import (
    LOOP1_OUTBOUND,
    LOOP2_INBOUND,
    LOOP3_CROSS,
    LoopSpec,
    StepKind,
    active_loops,
    bridge_mechanism,
)

TOKEN = TokenConfig(
    symbol="VNXAU",
    decimals=18,
    chains={"base": "0xb", "ethereum": "0xe", "solana": "solV", "vnx": "VNXAU"},
)


def _loops():
    return active_loops(token=TOKEN)


def _by_family(family: str) -> list[LoopSpec]:
    return [loop for loop in _loops() if loop.family == family]


def test_loop_counts_for_vnxau():
    loops = _loops()
    assert len(loops) == 12  # L1=3, L2=3, L3=6 for {base, ethereum, solana}
    assert len(_by_family(LOOP1_OUTBOUND)) == 3
    assert len(_by_family(LOOP2_INBOUND)) == 3
    assert len(_by_family(LOOP3_CROSS)) == 6


def test_loop1_eth_has_no_hub_bridge():
    """ETH is the hub: selling VNXAU on ETH already yields ETH USDC."""
    loop = LoopSpec(LOOP1_OUTBOUND, "VNXAU", "ethereum")
    kinds = [s.kind for s in loop.steps()]
    assert kinds == [
        StepKind.WITHDRAW_TOKEN,
        StepKind.SELL_TOKEN_ONCHAIN,
        StepKind.VNX_USDC_DEPOSIT,
        StepKind.PLATFORM_BUYBACK,
    ]
    assert loop.bridge_legs == ()


def test_loop2_eth_has_no_hub_bridge():
    loop = LoopSpec(LOOP2_INBOUND, "VNXAU", "ethereum")
    kinds = [s.kind for s in loop.steps()]
    assert kinds == [
        StepKind.PLATFORM_SELL_TOKEN,
        StepKind.WITHDRAW_USDC,
        StepKind.ONCHAIN_BUYBACK,
        StepKind.VNX_TOKEN_DEPOSIT,
    ]
    assert loop.bridge_legs == ()


def test_loop1_base_bridges_to_eth_via_cctp():
    loop = LoopSpec(LOOP1_OUTBOUND, "VNXAU", "base")
    assert loop.bridge_legs[0].bridge_to == "ethereum"
    assert loop.bridge_legs[0].mechanism == "cctp"


def test_loop3_eth_pairs_use_cctp():
    assert LoopSpec(LOOP3_CROSS, "VNXAU", "base", "ethereum").bridge_legs[0].mechanism == "cctp"
    assert LoopSpec(LOOP3_CROSS, "VNXAU", "ethereum", "solana").bridge_legs[0].mechanism == "cctp"
    assert bridge_mechanism("base", "solana") == "cctp"


def test_every_loop_is_same_asset_round_trip():
    for loop in _loops():
        steps = loop.steps()
        assert steps[-1].kind in (StepKind.PLATFORM_BUYBACK, StepKind.VNX_TOKEN_DEPOSIT)
        buybacks = [s for s in steps if s.is_buyback]
        assert len(buybacks) == 1
        for s in steps:
            if s.kind in (StepKind.PLATFORM_BUYBACK, StepKind.ONCHAIN_BUYBACK):
                assert s.is_buyback
