#!/usr/bin/env python3
"""
Small-size probe tests (~5 USDC / 5 VNXAU per leg). Allowed to run at a loss.

Usage:
  python scripts/test_probe_trades.py              # quotes + dry-run only
  python scripts/test_probe_trades.py --execute  # live swaps (set DRY_RUN=false)

VNX on-chain deposit credit min is 5 VNXAU (BASE/SOL cumulative). Platform buy/sell min is 30 VNXAU.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.config_loader import is_dry_run, load_bot_config, load_chains, load_tokens, token_decimals
from src.execution.base import BaseExecutor
from src.execution.executor import ArbExecutor
from src.execution.solana import SolanaExecutor
from src.quotes.http_client import build_client
from src.quotes.router import buy_token_with_stable, sell_token_for_stable
from src.quotes.types import from_human, to_human
from src.scanner.simulator import simulate_direction
from src.vnx.deposits import min_deposit_vnxau
from src.vnx.trading import VNXAU_MIN_ORDER

PROBE_VNXAU = 5.0
PROBE_STABLE_USD = 5.0
VNX_DEPOSIT_MIN_VNXAU = min(min_deposit_vnxau("BASE"), min_deposit_vnxau("SOL"))


def print_funding_guide(base_addr: str, sol_addr: str) -> None:
    print("\n" + "=" * 60)
    print("FUNDING GUIDE — test probes (5 USDC / 5 VNXAU each side)")
    print("=" * 60)
    print(
        """
┌─────────────────┬──────────────────────────────────────────────────────────┐
│ Wallet / Platform│ Fund with (minimum for probes)                          │
├─────────────────┼──────────────────────────────────────────────────────────┤
│ Base hot wallet │ ~15 USDT  (5 for buy probe + 5 buffer + gas in BASE)    │
│                 │ ~0.05 BASE native for gas                                 │
│                 │ Optional: 5 VNXAU on-wallet if testing sell-only first     │
│                 │ Address: {base}                                           │
├─────────────────┼──────────────────────────────────────────────────────────┤
│ Solana hot wallet│ ~15 USDC (5 for buy probe + 5 buffer + tx fees)         │
│                 │ ~0.02 SOL for Jupiter swap fees                           │
│                 │ Optional: 5 VNXAU SPL if testing sell-only first           │
│                 │ Address: {sol}                                            │
├─────────────────┼──────────────────────────────────────────────────────────┤
│ VNX Platform    │ NOT needed for 5 VNXAU swap-only probes                    │
│                 │ For LIVE cross-chain arb: bridge min {vnx_min:.0f} VNXAU     │
│                 │ Whitelist labels: base-hot + sol-hot (already configured)   │
│                 │ USDC on platform: NOT used (routes disabled; ETH only)      │
└─────────────────┴──────────────────────────────────────────────────────────┘

Test phases (this script):
  1. Quote 5 VNXAU buy/sell on Base (USDT) and Solana (USDC)
  2. Simulate full base↔sol routes at 5 VNXAU (expect loss; bridge dry-run only)
  3. With --execute: broadcast single-chain swap legs only (~5 VNXAU / ~$5)

Do NOT fund Ethereum USDC for VNX — platform USDC arb routes are off.
""".format(
            base=base_addr or "(set BASE_PRIVATE_KEY)",
            sol=sol_addr or "(set SOLANA_SECRET_KEY)",
            vnx_min=VNX_BRIDGE_MIN_VNXAU,
        )
    )


async def quote_leg(
    client,
    chain_key: str,
    side: str,
    vnxau: float,
) -> tuple[bool, str]:
    chains = load_chains()
    token = load_tokens()["VNXAU"]
    chain = chains[chain_key]
    dec = token_decimals(token, chain_key)

    if side == "buy":
        stable_raw = from_human(PROBE_STABLE_USD, chain.hub_decimals)
        q = await buy_token_with_stable(client, chain, token, chain_key, stable_raw)
        if not q:
            return False, f"{chain_key} buy FAILED"
        got = float(to_human(q.amount_out, dec))
        return True, f"{chain_key} buy: ${PROBE_STABLE_USD:.0f} → {got:.4f} VNXAU via {q.provider}"

    amt = from_human(vnxau, dec)
    q = await sell_token_for_stable(client, chain, token, chain_key, amt)
    if not q:
        return False, f"{chain_key} sell FAILED"
    out = float(to_human(q.amount_out, chain.hub_decimals))
    return True, f"{chain_key} sell: {vnxau:.1f} VNXAU → ${out:.4f} via {q.provider}"


async def execute_swap_leg(chain_key: str, side: str, vnxau: float) -> str | None:
    chains = load_chains()
    token = load_tokens()["VNXAU"]
    cfg = load_bot_config()
    dec = token_decimals(token, chain_key)

    if chain_key == "base":
        ex = BaseExecutor(chains["base"])
        if side == "buy":
            usdt = from_human(PROBE_STABLE_USD, chains["base"].hub_decimals)
            min_out = int(vnxau * 0.97 * 10**dec)
            return ex.swap_exact_input(chains["base"].hub_token, token.chains["base"], usdt, min_out)
        vnxau_raw = from_human(vnxau, dec)
        min_usdt = int(PROBE_STABLE_USD * 0.97 * 10**chains["base"].hub_decimals)
        return ex.swap_exact_input(token.chains["base"], chains["base"].hub_token, vnxau_raw, min_usdt)

    ex = SolanaExecutor(chains["solana"])
    async with build_client() as client:
        if side == "buy":
            usdc = from_human(PROBE_STABLE_USD, chains["solana"].hub_decimals)
            return await ex.swap(
                client, chains["solana"].hub_token, token.chains["solana"], usdc, cfg.slippage_bps
            )
        vnxau_raw = from_human(vnxau, dec)
        return await ex.swap(
            client, token.chains["solana"], chains["solana"].hub_token, vnxau_raw, cfg.slippage_bps
        )


async def main() -> None:
    p = argparse.ArgumentParser(description="5 USDC / 5 VNXAU probe tests")
    p.add_argument("--execute", action="store_true", help="Broadcast swap legs (needs DRY_RUN=false)")
    args = p.parse_args()

    if args.execute and is_dry_run():
        print("ERROR: set DRY_RUN=false in .env for live probe swaps")
        sys.exit(1)

    base_addr = sol_addr = ""
    try:
        base_addr = BaseExecutor(load_chains()["base"]).address
    except Exception:
        pass
    try:
        sol_addr = SolanaExecutor(load_chains()["solana"]).address
    except Exception:
        pass

    print_funding_guide(base_addr, sol_addr)

    chains = load_chains()
    token = load_tokens()["VNXAU"]
    cfg = load_bot_config()

    print("\n--- Live quotes @ 5 VNXAU / $5 stable ---")
    async with build_client() as client:
        for chain_key in ("base", "solana"):
            ok, msg = await quote_leg(client, chain_key, "buy", PROBE_VNXAU)
            print(f"  {'OK' if ok else 'FAIL'}: {msg}")
            ok, msg = await quote_leg(client, chain_key, "sell", PROBE_VNXAU)
            print(f"  {'OK' if ok else 'FAIL'}: {msg}")

        print("\n--- Route simulation @ 5 VNXAU (loss OK; bridge dry-run below VNX min) ---")
        for direction in ("base_to_solana", "solana_to_base"):
            sim = await simulate_direction(client, chains, token, cfg, direction, PROBE_VNXAU)
            print(
                f"  {direction}: in=${sim.stable_in_usd:.2f} out=${sim.stable_out_usd:.2f} "
                f"net=${sim.net_profit_usd:+.2f} err={sim.error or 'none'}"
            )

    if args.execute:
        print("\n--- Executing single-chain swap probes ---")
        for chain_key, side in (
            ("base", "buy"),
            ("base", "sell"),
            ("solana", "buy"),
            ("solana", "sell"),
        ):
            tx = await execute_swap_leg(chain_key, side, PROBE_VNXAU)
            print(f"  {chain_key} {side}: tx={tx}")

        print(
            f"\n--- Full deposit-bridge route @ {PROBE_VNXAU} VNXAU "
            f"(deposit min {VNX_DEPOSIT_MIN_VNXAU}; platform order min {VNXAU_MIN_ORDER}) ---"
        )
        if PROBE_VNXAU < VNX_DEPOSIT_MIN_VNXAU:
            print(f"  SKIP live bridge: {PROBE_VNXAU} VNXAU < deposit min {VNX_DEPOSIT_MIN_VNXAU}")
        else:
            ex = ArbExecutor(chains, token, cfg)
            async with build_client() as client:
                for d in ("base_to_solana", "solana_to_base"):
                    rec = await ex.run_cycle(client, d, PROBE_VNXAU)
                    print(f"  {d}: state={rec.state.value} error={rec.error}")
    else:
        print("\nDry-run only. Re-run with --execute and DRY_RUN=false for live swap probes.")


if __name__ == "__main__":
    asyncio.run(main())
