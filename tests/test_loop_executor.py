"""LoopExecutor: dry-run step dispatch for Loop 1/2/3, ETH-hub case + live gating."""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config_loader import BotConfig, ChainConfig, TokenConfig
from src.execution.loop_executor import LoopExecutor, LoopRecord, LoopState
from src.scanner.loop_simulator import LoopLeg, LoopSimulation
from src.scanner.routes import LOOP1_OUTBOUND, LOOP2_INBOUND, LOOP3_CROSS, LoopSpec

MOD = "src.execution.loop_executor"

TOKEN = TokenConfig(
    symbol="VNXAU",
    decimals=18,
    chain_decimals={"solana": 9},
    chains={"base": "0xb", "ethereum": "0xe", "solana": "solV", "vnx": "VNXAU"},
)


def _chain(key: str, *, vnx: bool = False) -> ChainConfig:
    kwargs = dict(
        key=key, name=key.title(), chain_id=0 if vnx else 1, enabled=True,
        bridge_verified=True, quote_tier="aggregator", hub_stable="USDC",
        hub_token="USDC", hub_decimals=6, rpc_env="RPC",
    )
    if vnx:
        kwargs["chain_type"] = "vnx"
    return ChainConfig(**kwargs)


CHAINS = {
    "base": _chain("base"),
    "ethereum": _chain("ethereum"),
    "solana": _chain("solana"),
    "vnx": _chain("vnx", vnx=True),
}


def _cfg(*, enable_loop_executor: bool = False) -> BotConfig:
    return BotConfig(
        poll_interval_sec=60, min_profit_usd=5, min_trade_vnxau=0.4, max_trade_vnxau=2000,
        sizing_coarse_step=100, max_sizing_quotes=5, probe_sizes=[40], slippage_bps=50,
        quote_freshness_sec=30, peg_min=0.98, peg_max=1.02, vnx_bridge_poll_sec=30,
        vnx_bridge_timeout_sec=3600, base_gas_usd_estimate=0.25, solana_fee_usd_estimate=0.05,
        vnx_bridge_fee_usd=1.0, vnx_platform_fee_usd=0.5, wormhole_bridge_fee_usd=0.5,
        enable_vnx_arb_routes=True, enable_vnx_cctp_routes=True, indirect_route_premium_usd=5.0,
        eth_gas_usd_estimate=2.0, platform_vnxau_only=True, treasury_vnxau_home="platform",
        jit_withdraw=True, enable_loop_executor=enable_loop_executor,
    )


def _bridge_ok():
    return SimpleNamespace(
        success=True, dry_run=True, source_tx="0xsrc", dest_tx="0xdst", direction="x", error=None,
        amount_usdc=100.0,
    )


def _sim(loop: LoopSpec, *, size: float, token_out: float, legs: list[LoopLeg],
         profitable: bool = True, error: str | None = None) -> LoopSimulation:
    sim = LoopSimulation(loop_key=loop.key, family=loop.family, token="VNXAU", size=size)
    sim.token_out = token_out
    sim.net_token = token_out - size
    sim.ref_price = 1.0
    sim.net_profit_usd = sim.net_token * 1.0
    sim.profitable = profitable
    sim.floors_ok = profitable
    sim.legs = legs
    sim.error = error
    return sim


def _evm_mock():
    m = MagicMock()
    m.swap_exact_input.return_value = "0xevmswap"
    m.transfer_erc20.return_value = "0xevmtransfer"
    m.balance_erc20.return_value = 10 ** 40
    m.address = "0xEvmAddr"
    return m


def _apply(stack: ExitStack, sim: LoopSimulation, *, dry_run: bool = True) -> None:
    sol = MagicMock()
    sol.swap = AsyncMock(return_value="solswap")
    sol.transfer_spl.return_value = "soltransfer"

    vnxb = MagicMock()
    vnxb.bridge_vnxau = AsyncMock(
        return_value=SimpleNamespace(
            success=True, quantity=None, deposit_tx="0xdep", withdraw_txids=["0xwd"],
            dry_run=True, error=None,
        )
    )
    usdcb = MagicMock()
    usdcb.withdraw_usdc = AsyncMock(
        return_value=SimpleNamespace(success=True, withdraw_txids=["0xu"], dry_run=True, error=None)
    )
    cctp = MagicMock()
    for name in (
        "bridge_usdc_sol_to_eth", "bridge_usdc_eth_to_sol", "bridge_usdc_base_to_eth",
        "bridge_usdc_eth_to_base", "bridge_usdc_base_to_sol", "bridge_usdc_sol_to_base",
    ):
        setattr(cctp, name, AsyncMock(return_value=_bridge_ok()))

    stack.enter_context(patch(f"{MOD}.simulate_loop", new=AsyncMock(return_value=sim)))
    stack.enter_context(patch(f"{MOD}.is_dry_run", new=MagicMock(return_value=dry_run)))
    stack.enter_context(patch(f"{MOD}.log_cycle_step", new=MagicMock()))
    stack.enter_context(patch(f"{MOD}.BaseExecutor", new=MagicMock(return_value=_evm_mock())))
    stack.enter_context(patch(f"{MOD}.EthereumExecutor", new=MagicMock(return_value=_evm_mock())))
    stack.enter_context(patch(f"{MOD}.SolanaExecutor", new=MagicMock(return_value=sol)))
    stack.enter_context(patch(f"{MOD}.VnxBridge", new=MagicMock(return_value=vnxb)))
    stack.enter_context(patch(f"{MOD}.VnxUsdcBridge", new=MagicMock(return_value=usdcb)))
    stack.enter_context(patch(f"{MOD}.CircleCctpBridge", new=MagicMock(return_value=cctp)))
    stack.enter_context(
        patch(f"{MOD}.platform_sell_vnxau", new=AsyncMock(
            return_value=SimpleNamespace(success=True, quantity=100, price=1.0, ordid="1", ordstatus="2", dry_run=True, error=None)))
    )
    stack.enter_context(
        patch(f"{MOD}.platform_buy_vnxau", new=AsyncMock(
            return_value=SimpleNamespace(success=True, quantity=110, price=1.0, ordid="2", ordstatus="2", dry_run=True, error=None)))
    )
    stack.enter_context(patch(f"{MOD}.eth_usdc_to_vnx", new=AsyncMock(return_value={"success": True, "deposit_tx": "0xeth"})))
    stack.enter_context(patch(f"{MOD}.validate_eth_usdc_vnx_deposit", new=MagicMock(return_value=None)))


async def _run(loop, sim, *, dry_run=True, enable=False, force=False):
    ex = LoopExecutor(CHAINS, TOKEN, _cfg(enable_loop_executor=enable))
    with ExitStack() as stack:
        _apply(stack, sim, dry_run=dry_run)
        return await ex.run_loop(MagicMock(), loop, sim.size, force_execute=force)


def _l1_legs_with_bridge(chain):
    return [
        LoopLeg("sell_onchain", chain, "", 145.0),
        LoopLeg("bridge_stable", chain, "", 143.0),
        LoopLeg("vnx_usdc_deposit", "ethereum", "", 140.0),
        LoopLeg("platform_buyback", "vnx", "", 140.0),
    ]


def _l1_legs_eth():  # ETH-as-hub: no bridge leg
    return [
        LoopLeg("sell_onchain", "ethereum", "", 145.0),
        LoopLeg("vnx_usdc_deposit", "ethereum", "", 142.0),
        LoopLeg("platform_buyback", "vnx", "", 142.0),
    ]


@pytest.mark.asyncio
async def test_loop1_base_uses_cctp_to_hub():
    loop = LoopSpec(LOOP1_OUTBOUND, "VNXAU", "base")
    sim = _sim(loop, size=100.0, token_out=110.0, legs=_l1_legs_with_bridge("base"))
    rec = await _run(loop, sim)
    assert rec.state == LoopState.DONE
    assert rec.steps_done == [
        "withdraw_token", "sell_token_onchain", "bridge_base_ethereum",
        "vnx_usdc_deposit", "platform_buyback",
    ]


@pytest.mark.asyncio
async def test_loop1_eth_skips_bridge():
    loop = LoopSpec(LOOP1_OUTBOUND, "VNXAU", "ethereum")
    sim = _sim(loop, size=100.0, token_out=108.0, legs=_l1_legs_eth())
    rec = await _run(loop, sim)
    assert rec.state == LoopState.DONE
    # No bridge step at all — USDC already settles on ETH
    assert rec.steps_done == [
        "withdraw_token", "sell_token_onchain", "vnx_usdc_deposit", "platform_buyback",
    ]
    assert not any(s.startswith("bridge_") for s in rec.steps_done)


@pytest.mark.asyncio
async def test_loop2_eth_skips_bridge():
    loop = LoopSpec(LOOP2_INBOUND, "VNXAU", "ethereum")
    legs = [
        LoopLeg("platform_sell", "vnx", "", 145.0),
        LoopLeg("onchain_buyback", "ethereum", "", 143.0),
        LoopLeg("vnx_token_deposit", "ethereum", "", 143.0),
    ]
    sim = _sim(loop, size=100.0, token_out=109.0, legs=legs)
    rec = await _run(loop, sim)
    assert rec.state == LoopState.DONE
    assert rec.steps_done == [
        "platform_sell_token", "withdraw_usdc", "onchain_buyback", "vnx_token_deposit",
    ]
    assert not any(s.startswith("bridge_") for s in rec.steps_done)


@pytest.mark.asyncio
async def test_loop2_base_bridges_eth_to_base():
    loop = LoopSpec(LOOP2_INBOUND, "VNXAU", "base")
    legs = [
        LoopLeg("platform_sell", "vnx", "", 145.0),
        LoopLeg("bridge_stable", "ethereum", "", 143.0),
        LoopLeg("onchain_buyback", "base", "", 143.0),
        LoopLeg("vnx_token_deposit", "base", "", 143.0),
    ]
    sim = _sim(loop, size=100.0, token_out=109.0, legs=legs)
    rec = await _run(loop, sim)
    assert rec.state == LoopState.DONE
    assert "bridge_ethereum_base" in rec.steps_done


@pytest.mark.asyncio
async def test_loop3_base_to_solana_cctp():
    loop = LoopSpec(LOOP3_CROSS, "VNXAU", "base", "solana")
    legs = [
        LoopLeg("sell_onchain", "base", "", 145.0),
        LoopLeg("bridge_stable", "base", "", 143.0),
        LoopLeg("onchain_buyback", "solana", "", 143.0),
        LoopLeg("vnx_token_deposit", "solana", "", 143.0),
    ]
    sim = _sim(loop, size=100.0, token_out=107.0, legs=legs)
    rec = await _run(loop, sim)
    assert rec.state == LoopState.DONE
    assert "bridge_base_solana" in rec.steps_done


@pytest.mark.asyncio
async def test_unprofitable_loop_is_gated():
    loop = LoopSpec(LOOP1_OUTBOUND, "VNXAU", "base")
    sim = _sim(loop, size=100.0, token_out=99.0, legs=_l1_legs_with_bridge("base"), profitable=False, error="loss")
    rec = await _run(loop, sim)
    assert rec.state == LoopState.FAILED
    assert rec.error == "loss"


@pytest.mark.asyncio
async def test_live_execution_blocked_without_flag():
    loop = LoopSpec(LOOP1_OUTBOUND, "VNXAU", "ethereum")
    sim = _sim(loop, size=100.0, token_out=110.0, legs=_l1_legs_eth())
    rec = await _run(loop, sim, dry_run=False, enable=False)
    assert rec.state == LoopState.FAILED
    assert rec.error and "ENABLE_LOOP_EXECUTOR" in rec.error


@pytest.mark.asyncio
async def test_live_execution_allowed_with_flag():
    loop = LoopSpec(LOOP1_OUTBOUND, "VNXAU", "ethereum")
    sim = _sim(loop, size=100.0, token_out=110.0, legs=_l1_legs_eth())
    rec = await _run(loop, sim, dry_run=False, enable=True)
    assert rec.state == LoopState.DONE


# ---- robustness hardening: swap retry + destination balance-await ----------


@pytest.mark.asyncio
async def test_swap_with_retry_recovers_after_transient_failure():
    ex = LoopExecutor(CHAINS, TOKEN, _cfg())
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        return None if calls["n"] == 1 else "0xok"

    with patch(f"{MOD}.is_dry_run", new=MagicMock(return_value=True)):
        tx = await ex._swap_with_retry("sell test", flaky)
    assert tx == "0xok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_swap_with_retry_gives_up_after_max():
    ex = LoopExecutor(CHAINS, TOKEN, _cfg())  # loop_swap_retry_max=2 -> 3 attempts
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        return None

    with patch(f"{MOD}.is_dry_run", new=MagicMock(return_value=True)):
        tx = await ex._swap_with_retry("buy test", always_fail)
    assert tx is None
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_await_stable_times_out_in_live_mode():
    cfg = _cfg()
    cfg.vnx_bridge_timeout_sec = 0
    ex = LoopExecutor(CHAINS, TOKEN, cfg)
    rec = LoopRecord(id="x", loop_key="k", family=LOOP1_OUTBOUND, size=100.0)
    with patch(f"{MOD}.is_dry_run", new=MagicMock(return_value=False)), \
            patch.object(ex, "_stable_balance_raw", return_value=0):
        ok = await ex._await_stable(rec, "base", 100.0)
    assert ok is False
    assert rec.state == LoopState.FAILED
    assert rec.error and "timeout waiting for hub stable" in rec.error


@pytest.mark.asyncio
async def test_await_stable_skips_chain_without_reader():
    ex = LoopExecutor(CHAINS, TOKEN, _cfg())
    rec = LoopRecord(id="x", loop_key="k", family=LOOP1_OUTBOUND, size=100.0)
    with patch(f"{MOD}.is_dry_run", new=MagicMock(return_value=False)), \
            patch.object(ex, "_stable_balance_raw", return_value=None):
        ok = await ex._await_stable(rec, "solana", 100.0)
    assert ok is True
    assert rec.state != LoopState.FAILED
