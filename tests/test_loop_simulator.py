"""Loop simulator: USD-flow accounting, floors, buy-back gating, ETH special case."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.config_loader import BotConfig, ChainConfig, TokenConfig
from src.scanner.loop_simulator import simulate_loop
from src.scanner.routes import LOOP1_OUTBOUND, LOOP2_INBOUND, LOOP3_CROSS, LoopSpec

TOKEN = TokenConfig(
    symbol="VNXAU",
    decimals=18,
    chain_decimals={"solana": 9},
    chains={"base": "0xb", "ethereum": "0xe", "solana": "solV", "vnx": "VNXAU"},
)


def _chain(key: str, tier: str, *, vnx: bool = False) -> ChainConfig:
    kwargs = dict(
        key=key, name=key.title(), chain_id=0 if vnx else 1, enabled=True,
        bridge_verified=True, quote_tier=tier, hub_stable="USDC", hub_token="USDC",
        hub_decimals=6, rpc_env="RPC",
    )
    if vnx:
        kwargs["chain_type"] = "vnx"
    return ChainConfig(**kwargs)


CHAINS = {
    "base": _chain("base", "aggregator"),
    "ethereum": _chain("ethereum", "aggregator"),
    "solana": _chain("solana", "jupiter"),
    "vnx": _chain("vnx", "vnx", vnx=True),
}


def _cfg() -> BotConfig:
    return BotConfig(
        poll_interval_sec=60, min_profit_usd=5, min_trade_vnxau=0.4, max_trade_vnxau=2000,
        sizing_coarse_step=100, max_sizing_quotes=5, probe_sizes=[40], slippage_bps=50,
        quote_freshness_sec=30, peg_min=0.98, peg_max=1.02, vnx_bridge_poll_sec=30,
        vnx_bridge_timeout_sec=3600, base_gas_usd_estimate=0.25, solana_fee_usd_estimate=0.05,
        vnx_bridge_fee_usd=1.0, vnx_platform_fee_usd=0.5, wormhole_bridge_fee_usd=0.5,
        enable_vnx_arb_routes=True, enable_vnx_cctp_routes=True, indirect_route_premium_usd=5.0,
        eth_gas_usd_estimate=2.0, platform_vnxau_only=True, treasury_vnxau_home="platform",
        jit_withdraw=True,
    )


def _mocks(sell_px, buy_px):
    async def fake_sell(client, chain, token, chain_key, amount_in):
        dec = token.chain_decimals.get(chain_key, token.decimals)
        size = amount_in / 10**dec
        return SimpleNamespace(amount_out=int(size * sell_px[chain_key] * 10**chain.hub_decimals), provider="sell")

    async def fake_buy(client, chain, token, chain_key, stable_amount, *, is_buyback=False):
        assert is_buyback, "buy-back legs must pass is_buyback=True"
        usd = stable_amount / 10**chain.hub_decimals
        dec = token.chain_decimals.get(chain_key, token.decimals)
        return SimpleNamespace(amount_out=int((usd / buy_px[chain_key]) * 10**dec), provider="buy")

    return fake_sell, fake_buy


async def _run(loop, *, sell_px, buy_px, ref_bid, size=100.0):
    fake_sell, fake_buy = _mocks(sell_px, buy_px)
    with (
        patch("src.scanner.loop_simulator.sell_token_for_stable", new=fake_sell),
        patch("src.scanner.loop_simulator.buy_token_with_stable", new=fake_buy),
        patch("src.scanner.loop_simulator._platform_ref_price", new=AsyncMock(return_value=(ref_bid, ref_bid))),
        patch("src.scanner.loop_simulator._bridge_fee_usd", new=AsyncMock(return_value=0.3)),
        patch("src.scanner.loop_simulator.min_deposit_usdc", return_value=20.0),
    ):
        return await simulate_loop(AsyncMock(), CHAINS, TOKEN, _cfg(), loop, size)


@pytest.mark.asyncio
async def test_loop1_base_profitable():
    sim = await _run(LoopSpec(LOOP1_OUTBOUND, "VNXAU", "base"), sell_px={"base": 1.45}, buy_px={"vnx": 1.30}, ref_bid=1.30)
    assert sim.error is None and sim.profitable and sim.token_out > sim.size


@pytest.mark.asyncio
async def test_loop1_eth_skips_bridge():
    """ETH is the hub: Loop 1 on ETH has no bridge leg."""
    sim = await _run(LoopSpec(LOOP1_OUTBOUND, "VNXAU", "ethereum"), sell_px={"ethereum": 1.45}, buy_px={"vnx": 1.30}, ref_bid=1.30)
    assert sim.error is None and sim.profitable
    assert [leg for leg in sim.legs if leg.kind == "bridge_stable"] == []


@pytest.mark.asyncio
async def test_loop2_eth_skips_bridge():
    sim = await _run(LoopSpec(LOOP2_INBOUND, "VNXAU", "ethereum"), sell_px={"vnx": 1.45}, buy_px={"ethereum": 1.30}, ref_bid=1.45)
    assert sim.error is None and sim.profitable
    assert [leg for leg in sim.legs if leg.kind == "bridge_stable"] == []


@pytest.mark.asyncio
async def test_loop3_base_to_solana_profitable():
    sim = await _run(LoopSpec(LOOP3_CROSS, "VNXAU", "base", "solana"), sell_px={"base": 1.45}, buy_px={"solana": 1.30}, ref_bid=1.40)
    assert sim.error is None and sim.profitable
    assert len([leg for leg in sim.legs if leg.kind == "bridge_stable"]) == 1


@pytest.mark.asyncio
async def test_size_below_min_order():
    sim = await _run(LoopSpec(LOOP1_OUTBOUND, "VNXAU", "base"), sell_px={"base": 1.45}, buy_px={"vnx": 1.30}, ref_bid=1.30, size=0.1)
    assert not sim.floors_ok and "min order" in (sim.error or "")
