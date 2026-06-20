#!/usr/bin/env python3
"""
Rebalance platform + chains before full route test.

Targets (platform-centric treasury):
  - Platform: >= 32 VNXAU (all inventory) + >= 54 USDC for vnx_to_* buys
  - Solana:   >= 53 USDC only (no on-chain VNXAU)
  - Base:     >= 53 USDT only (no on-chain VNXAU)
  - Ethereum: >= 3 USDC buffer + gas ETH (hub only)

Usage:
  python scripts/rebalance_for_test.py           # audit + plan
  python scripts/rebalance_for_test.py --execute # live moves
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.bridge.cctp import CircleCctpBridge
from src.bridge.cctp_queue import CctpClaimQueue
from src.bridge.hub_eth import eth_usdc_to_vnx, wormhole_base_to_eth, wormhole_eth_to_base
from src.bridge.wormhole_queue import WormholeClaimQueue
from src.treasury.manager import TreasuryManager
from src.config_loader import load_bot_config, load_bridge_config, load_chains, load_tokens, token_decimals
from src.execution.base import BaseExecutor
from src.execution.executor import ArbExecutor, CycleRecord, CycleState
from src.execution.solana import SolanaExecutor
from src.execution.tx_log import log_platform_order, log_tx
from src.quotes.http_client import build_client
from src.quotes.types import from_human, to_human
from src.vnx.deposits import check_usdc_deposit_amount, min_deposit_usdc
from src.vnx.client import VnxClient
from src.vnx.trading import _round_down, platform_buy_vnxau

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("rebalance")

TEST_VNXAU = 31.0
VNXAU_BUFFER = 1.0  # withdraw fee
USDC_FOR_BUY = 53.0  # ~31 VNXAU + slippage on Jupiter/VNX
USDT_FOR_BUY = 53.0
USDC_NEAR = USDC_FOR_BUY * 0.95  # tolerate ~5% shortfall for sequential routes
USDT_NEAR = USDT_FOR_BUY * 0.95
MIN_ETH_USDC = 3.0
MIN_ETH_USDT = 5.0
HUB_USDC = min_deposit_usdc("ETH")  # VNX ETH USDC cumulative minimum (default 20)
HUB_USDT = 5.0
MIN_SOL = 0.03


def _log(msg: str) -> None:
    print(msg, flush=True)


async def _balances() -> dict[str, float]:
    chains = load_chains()
    token = load_tokens()["VNXAU"]
    out: dict[str, float] = {}

    for attempt in range(3):
        try:
            async with VnxClient() as vnx:
                bal = await vnx.account_balance()
                out["platform_usdc"] = vnx.usdc_balance(bal)
                out["platform_vnxau"] = vnx.vnxau_balance(bal)
                out["platform_chf"] = vnx._asset_balance(bal, "CHF")
            break
        except Exception as exc:
            if attempt == 2:
                raise
            _log(f"  VNX balance retry ({exc})")
            time.sleep(2)

    base = BaseExecutor(chains["base"])
    dec = token_decimals(token, "base")
    out["base_usdc"] = float(to_human(base.balance_erc20(chains["base"].hub_token), 6))
    out["base_vnxau"] = float(to_human(base.balance_erc20(token.chains["base"]), dec))

    sol = SolanaExecutor(chains["solana"])
    from spl.token.instructions import get_associated_token_address
    from solders.pubkey import Pubkey

    usdc_ata = get_associated_token_address(
        sol.keypair.pubkey(), Pubkey.from_string(chains["solana"].hub_token)
    )
    vnxau_ata = get_associated_token_address(
        sol.keypair.pubkey(), Pubkey.from_string(token.chains["solana"])
    )
    for attempt in range(5):
        try:
            out["sol_usdc"] = float(sol.client.get_token_account_balance(usdc_ata).value.ui_amount or 0)
            try:
                out["sol_vnxau"] = float(sol.client.get_token_account_balance(vnxau_ata).value.ui_amount or 0)
            except Exception:
                out["sol_vnxau"] = 0.0
            out["sol_native"] = sol.balance_lamports() / 1e9
            break
        except Exception as exc:
            if attempt == 4:
                _log(f"  Sol balance unavailable after retries: {exc}")
                out["sol_usdc"] = 0.0
                out["sol_vnxau"] = 0.0
                out["sol_native"] = 0.0
            else:
                time.sleep(3 * (attempt + 1))

    try:
        from src.execution.ethereum import EthereumExecutor

        eth = EthereumExecutor(chains["ethereum"])
        wh = load_bridge_config()["wormhole"]
        out["eth_usdc"] = float(to_human(eth.balance_erc20(chains["ethereum"].hub_token), 6))
        out["eth_usdt"] = float(to_human(eth.balance_erc20(wh["ethereum_usdt"]), 6))
        out["eth_native"] = eth.balance_native() / 1e18
    except Exception as exc:
        _log(f"ETH unavailable: {exc}")
        out["eth_usdc"] = 0.0
        out["eth_usdt"] = 0.0
        out["eth_native"] = 0.0

    return out


async def route_order_for_balances(b: dict[str, float], *, dust: float) -> list[str]:
    """Pick capital-efficient route order from current balances."""
    need_plat = b["platform_usdc"] < USDC_NEAR and b["platform_vnxau"] < TEST_VNXAU + VNXAU_BUFFER
    sol_can_fund_plat = b["sol_usdc"] >= USDC_NEAR
    base_ready = b["base_usdc"] >= USDT_NEAR
    if base_ready and not (b["platform_vnxau"] >= TEST_VNXAU or b["platform_usdc"] >= USDC_NEAR):
        return ["base_to_solana", "solana_to_base", "solana_to_vnx", "vnx_to_solana"]
    if need_plat and sol_can_fund_plat:
        return ["solana_to_vnx", "vnx_to_solana", "solana_to_base", "base_to_solana"]
    return ["vnx_to_solana", "solana_to_vnx", "solana_to_base", "base_to_solana"]


def route_ready(direction: str, b: dict[str, float], *, dust: float) -> tuple[bool, str]:
    """Check if a single route can run at TEST_VNXAU with platform-centric capital."""
    if direction == "vnx_to_solana":
        ok = b["platform_vnxau"] >= TEST_VNXAU or b["platform_usdc"] >= USDC_NEAR
        return ok, "platform VNXAU or USDC"
    if direction == "vnx_to_base":
        ok = b["platform_vnxau"] >= TEST_VNXAU or b["platform_usdc"] >= USDC_NEAR
        return ok, "platform VNXAU or USDC"
    if direction == "solana_to_vnx":
        ok = b["sol_usdc"] >= USDC_NEAR and b["base_vnxau"] <= dust and b["sol_vnxau"] <= dust
        return ok, "Sol USDC (no on-chain VNXAU)"
    if direction == "base_to_vnx":
        ok = b["base_usdc"] >= USDT_NEAR and b["base_vnxau"] <= dust
        return ok, "Base USDT (no on-chain VNXAU)"
    if direction == "solana_to_base":
        ok = b["sol_usdc"] >= USDC_NEAR
        return ok, "Sol USDC"
    if direction == "base_to_solana":
        ok = b["base_usdc"] >= USDT_NEAR
        return ok, "Base USDT"
    return False, "unknown route"


async def audit() -> dict[str, float]:
    bot_cfg = load_bot_config()
    dust = bot_cfg.vnxau_on_chain_dust
    b = await _balances()
    _log("\n=== Balance audit ===")
    _log(
        f"Platform: USDC={b['platform_usdc']:.2f} VNXAU={b['platform_vnxau']:.2f} CHF={b['platform_chf']:.2f}"
    )
    _log(f"Base: USDT={b['base_usdc']:.2f} VNXAU={b['base_vnxau']:.2f}")
    _log(f"Sol:  USDC={b['sol_usdc']:.2f} VNXAU={b['sol_vnxau']:.2f} SOL={b['sol_native']:.4f}")
    _log(f"ETH:  USDC={b['eth_usdc']:.2f} USDT={b['eth_usdt']:.2f} ETH={b['eth_native']:.4f}")
    _log("\n=== Targets (platform-centric) ===")
    _log(f"  Platform: USDC>={USDC_FOR_BUY} or VNXAU>={TEST_VNXAU + VNXAU_BUFFER}")
    _log(f"  Sol:      USDC>={USDC_FOR_BUY} (no on-chain VNXAU > {dust})")
    _log(f"  Base:     USDT>={USDT_FOR_BUY} (no on-chain VNXAU > {dust})")
    if b["base_vnxau"] > dust or b["sol_vnxau"] > dust:
        _log(
            f"WARN: on-chain VNXAU base={b['base_vnxau']:.2f} sol={b['sol_vnxau']:.2f} "
            f"(dust={dust}) — consolidate to platform"
        )
    order = await route_order_for_balances(b, dust=dust)
    _log(f"\nSuggested route order: {order}")
    for d in order:
        ok, need = route_ready(d, b, dust=dust)
        _log(f"  {d}: {'OK' if ok else 'NEED'} ({need})")
    if b["platform_usdc"] < USDC_FOR_BUY and b["platform_chf"] < 25:
        _log("\nNOTE: Platform low on USDC; CHF→USDC needs ≥25 CHF (min 30 USDC order).")
    return b


async def step_cctp_claim(*, discover: bool | None = None) -> None:
    import os

    interval = float(os.getenv("CCTP_CLAIM_INTERVAL_SEC", "30"))
    max_rounds = int(os.getenv("CCTP_CLAIM_MAX_ROUNDS", "120"))
    _log("\n--- CCTP claim queue ---")
    queue = CctpClaimQueue()
    async with build_client() as client:
        summary = await queue.run_until_empty(
            client,
            interval_sec=interval,
            max_rounds=max_rounds,
            discover_first=True if discover is None else discover,
        )
    _log(f"CCTP: claimed={summary['claimed']} remaining={summary['remaining']}")


async def step_wormhole_claim(*, max_rounds: int = 60) -> None:
    interval = float(os.getenv("WORMHOLE_CLAIM_INTERVAL_SEC", "30"))
    _log("\n--- Wormhole claim queue ---")
    queue = WormholeClaimQueue()
    async with build_client() as client:
        summary = await queue.run_until_empty(client, interval_sec=interval, max_rounds=max_rounds)
    _log(f"Wormhole: claimed={summary['claimed']} remaining={summary['remaining']}")


async def step_cctp_eth_to_sol(client, amount: float) -> bool:
    if amount < 5:
        return True
    _log(f"\n--- CCTP ETH→Sol ${amount:.2f} USDC ---")
    try:
        bridge = CircleCctpBridge()
        r = await bridge.bridge_usdc_eth_to_sol(client, amount)
        _log(f"  {'OK' if r.success else 'PARTIAL'} src={r.source_tx} dst={r.dest_tx} err={r.error}")
        if r.source_tx and not r.dest_tx:
            await step_cctp_claim()
        return r.success or bool(r.dest_tx) or bool(r.source_tx)
    except Exception as exc:
        _log(f"  FAIL CCTP ETH→Sol: {exc}")
        return False


async def _fund_chain_stable_via_vnx(
    client,
    treasury: TreasuryManager,
    executor: ArbExecutor,
    chain: str,
    size_vnxau: float,
    execute: bool,
) -> bool:
    """
    Fund Base USDT or Sol USDC via vnx_to_* — withdraws platform VNXAU, sells to stable on chain.
    Ends with VNXAU consolidated back on platform (no on-chain VNXAU inventory).
    """
    direction = f"vnx_to_{chain}"
    _log(f"\n--- Treasury fund: {direction} ({size_vnxau:.0f} VNXAU) → {chain} stable ---")
    if not execute:
        return True
    prep = await treasury.prepare_for_direction(direction, size_vnxau)
    if not prep.ready:
        _log(f"  SKIP: {prep.notes}")
        return False
    from src.scanner.simulator import simulate_direction

    sim = await simulate_direction(
        client, load_chains(), load_tokens()["VNXAU"], load_bot_config(), direction, size_vnxau
    )
    record = CycleRecord(id="rebal", direction=direction, size_vnxau=size_vnxau)
    record.simulation = sim
    record.state = CycleState.EXECUTING
    await executor._exec_vnx_to_chain(client, record, sim, chain)
    await treasury.consolidate_vnxau_to_platform()
    ok = record.state == CycleState.DONE
    _log(f"  {'OK' if ok else 'FAIL'} {direction} err={record.error}")
    return ok


async def rebalance(execute: bool) -> bool:
    os.environ["CCTP_RECONCILE_USDC"] = "0"
    cfg = load_bot_config()
    chains = load_chains()
    token = load_tokens()["VNXAU"]
    treasury = TreasuryManager(chains, token, cfg)
    executor = ArbExecutor(chains, token, cfg)

    await step_cctp_claim()
    await step_wormhole_claim()
    if execute:
        await treasury.consolidate_vnxau_to_platform()
    b = await audit()
    _log("\n=== Treasury policy: VNXAU on platform only; chains hold stables ===")

    ok = True
    async with build_client() as client:
        # Move excess ETH USDC to platform when low on platform USDC
        if b["platform_usdc"] < USDC_FOR_BUY * 0.9 and b["eth_usdc"] > MIN_ETH_USDC + HUB_USDC:
            move = min(b["eth_usdc"] - MIN_ETH_USDC, HUB_USDC)
            dep_err = check_usdc_deposit_amount("ETH", move)
            if dep_err:
                _log(f"\nSKIP eth→vnx: {dep_err}")
            elif execute and move >= HUB_USDC:
                _log(f"\n--- ETH USDC → VNX platform ${move:.2f} ---")
                r = await eth_usdc_to_vnx(client, move)
                if not r["success"]:
                    _log(f"  FAIL eth→vnx: {r.get('error')}")
                    ok = False
            elif move >= HUB_USDC:
                _log(f"\nPLAN: ETH USDC → VNX ${move:.2f}")
            b = await _balances()

        # Fund Base USDT from ETH via Wormhole when Base short and ETH has USDT
        if b["base_usdc"] < USDT_FOR_BUY * 0.5 and b["eth_usdt"] >= HUB_USDT + MIN_ETH_USDT:
            move = min(HUB_USDT, b["eth_usdt"] - MIN_ETH_USDT)
            if execute and move >= HUB_USDT * 0.9:
                _log(f"\n--- Wormhole ETH→Base ${move:.2f} USDT ---")
                r = await wormhole_eth_to_base(client, move)
                if not r["success"]:
                    _log(f"  FAIL eth→base: {r.get('error')}")
                    ok = False
                await step_wormhole_claim(max_rounds=40)
            elif move >= HUB_USDT * 0.9:
                _log(f"\nPLAN: Wormhole ETH→Base ${move:.2f} USDT")
            b = await _balances()

        # Fund ETH USDT from Base via Wormhole when platform/ETH need stables
        if (
            b["eth_usdt"] < MIN_ETH_USDT
            and b["base_usdc"] >= HUB_USDT + 5
            and b["platform_usdc"] < USDC_NEAR
        ):
            move = min(HUB_USDT, b["base_usdc"] - 5)
            if execute and move >= HUB_USDT * 0.9:
                _log(f"\n--- Wormhole Base→ETH ${move:.2f} USDT ---")
                r = await wormhole_base_to_eth(client, move)
                if not r["success"]:
                    _log(f"  FAIL base→eth: {r.get('error')}")
                    ok = False
                await step_wormhole_claim(max_rounds=40)
            elif move >= HUB_USDT * 0.9:
                _log(f"\nPLAN: Wormhole Base→ETH ${move:.2f} USDT")
            b = await _balances()

        # Move excess ETH USDC to Sol (keep MIN_ETH_USDC on ETH)
        if b["eth_usdc"] > MIN_ETH_USDC + 5:
            move = min(b["eth_usdc"] - MIN_ETH_USDC, 15.0)
            if execute:
                if not await step_cctp_eth_to_sol(client, move):
                    ok = False
            else:
                _log(f"\nPLAN: CCTP ETH→Sol ${move:.2f}")

        b = await _balances()

        # Fund Sol USDC from ETH if still low
        if b["sol_usdc"] < USDC_FOR_BUY and b["eth_usdc"] > MIN_ETH_USDC + 5:
            need = min(USDC_FOR_BUY - b["sol_usdc"], b["eth_usdc"] - MIN_ETH_USDC)
            if execute and need >= 5:
                if not await step_cctp_eth_to_sol(client, need):
                    ok = False
            elif need >= 5:
                _log(f"\nPLAN: CCTP ETH→Sol ${need:.2f} (Sol USDC low)")
            b = await _balances()

        # Platform VNXAU inventory (home for all VNXAU)
        need_vnxau_plat = TEST_VNXAU + VNXAU_BUFFER
        if b["platform_vnxau"] < need_vnxau_plat and b["platform_usdc"] >= USDC_FOR_BUY * 0.95:
            if execute:
                buy = await platform_buy_vnxau(cfg, TEST_VNXAU, max_usdc=b["platform_usdc"] * 0.995)
                if buy.success:
                    log_platform_order("rebalance_platform_vnxau", buy.ordid, qty=buy.quantity)
                else:
                    _log(f"FAIL platform VNXAU buy: {buy.error}")
                    ok = False
            else:
                _log(f"\nPLAN: Platform buy VNXAU (~{need_vnxau_plat - b['platform_vnxau']:.0f})")
            b = await _balances()

        # Fund Base USDT via vnx_to_base (ends with USDT on Base, VNXAU back on platform)
        if b["base_usdc"] < USDT_FOR_BUY and b["platform_vnxau"] >= TEST_VNXAU:
            if execute:
                if not await _fund_chain_stable_via_vnx(client, treasury, executor, "base", TEST_VNXAU, True):
                    ok = False
                else:
                    time.sleep(30)
            else:
                _log(f"\nPLAN: vnx_to_base {TEST_VNXAU} VNXAU → Base USDT")
            b = await _balances()

        # Fund Sol USDC via vnx_to_solana
        if b["sol_usdc"] < USDC_FOR_BUY and b["platform_vnxau"] >= TEST_VNXAU:
            if execute:
                if not await _fund_chain_stable_via_vnx(client, treasury, executor, "solana", TEST_VNXAU, True):
                    ok = False
                else:
                    time.sleep(30)
            else:
                _log(f"\nPLAN: vnx_to_solana {TEST_VNXAU} VNXAU → Sol USDC")
            b = await _balances()

        if execute:
            await treasury.consolidate_vnxau_to_platform()

    await step_cctp_claim()
    await step_wormhole_claim()
    b = await audit()

    bot_cfg = load_bot_config()
    dust = bot_cfg.vnxau_on_chain_dust
    if b["base_vnxau"] > dust or b["sol_vnxau"] > dust:
        _log(
            f"WARN: on-chain VNXAU base={b['base_vnxau']:.2f} sol={b['sol_vnxau']:.2f} "
            f"(dust={dust}) — run consolidate"
        )

    order = await route_order_for_balances(b, dust=dust)
    first_ok, first_need = route_ready(order[0], b, dust=dust)
    needs_eth_buffer = order[0] in ("vnx_to_solana", "solana_to_vnx") and b["platform_usdc"] < USDC_NEAR
    ready = b["sol_native"] >= MIN_SOL and first_ok
    if needs_eth_buffer:
        ready = ready and b["eth_usdc"] >= MIN_ETH_USDC
    if not first_ok:
        _log(f"\nFirst route ({order[0]}) blocked: need {first_need}")
    _log(f"\n{'READY' if ready else 'NOT READY'} for full 31 VNXAU route test")
    return ready and ok


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()
    ok = await rebalance(args.execute)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
