#!/usr/bin/env python3
"""Live quote verification against screenshot baselines."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from src.config_loader import load_chains, load_tokens, token_decimals
from src.quotes.http_client import build_client
from src.quotes.router import buy_token_with_stable, sell_token_for_stable
from src.quotes.types import from_human, to_human
from src.vnx.auth import ensure_public_key_env


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sizes", default="10,50,100")
    args = p.parse_args()
    sizes = [float(x) for x in args.sizes.split(",")]

    try:
        ensure_public_key_env()
    except Exception:
        pass

    chains = load_chains()
    token = load_tokens()["VNXAU"]
    base = chains["base"]
    sol = chains["solana"]
    eth = chains["ethereum"]

    async with build_client() as client:
        for size in sizes:
            print(f"\n=== Size {size} VNXAU ===")
            sol_dec = token_decimals(token, "solana")
            base_dec = token_decimals(token, "base")
            eth_dec = token_decimals(token, "ethereum")

            vnxau_amt = from_human(size, sol_dec)
            sell_sol = await sell_token_for_stable(client, sol, token, "solana", vnxau_amt)
            if sell_sol:
                usdc = float(to_human(sell_sol.amount_out, sol.hub_decimals))
                rate = usdc / size if size else 0
                print(f"  Sol sell: {size} VNXAU -> {usdc:.4f} USDC ({rate:.4f} USDC/VNXAU) via {sell_sol.provider}")
            else:
                print("  Sol sell: FAILED")

            usdc_probe = from_human(size * 135.0, base.hub_decimals)
            buy_base = await buy_token_with_stable(client, base, token, "base", usdc_probe)
            if buy_base:
                vnxau = float(to_human(buy_base.amount_out, base_dec))
                usdc_in = float(to_human(usdc_probe, base.hub_decimals))
                rate = usdc_in / vnxau if vnxau else 0
                print(
                    f"  Base buy: {usdc_in:.2f} USDC -> {vnxau:.4f} VNXAU "
                    f"({rate:.2f} USDC/VNXAU) via {buy_base.provider}"
                )
            else:
                print("  Base buy: FAILED")

            eth_probe = from_human(size * 135.0, eth.hub_decimals)
            buy_eth = await buy_token_with_stable(client, eth, token, "ethereum", eth_probe)
            if buy_eth:
                vnxau = float(to_human(buy_eth.amount_out, eth_dec))
                usdc_in = float(to_human(eth_probe, eth.hub_decimals))
                rate = usdc_in / vnxau if vnxau else 0
                print(
                    f"  ETH buy: {usdc_in:.2f} USDC -> {vnxau:.4f} VNXAU "
                    f"({rate:.2f} USDC/VNXAU) via {buy_eth.provider}"
                )
            else:
                print("  ETH buy: FAILED")


if __name__ == "__main__":
    asyncio.run(main())
