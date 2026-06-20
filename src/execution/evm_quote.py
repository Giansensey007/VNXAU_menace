from __future__ import annotations

from src.config_loader import BotConfig, ChainConfig, load_bot_config
from src.execution.kyber_swap import fetch_route
from src.quotes import kyber
from src.quotes.onchain import quote_onchain_pools


def simulate_evm_swap(
    chain: ChainConfig,
    token_in: str,
    token_out: str,
    amount_in: int,
    *,
    token_symbol: str = "VNXAU",
    vnxau_addr: str = "",
    vnxau_decimals: int = 18,
    cfg: BotConfig | None = None,
) -> dict | None:
    """Dry-run swap quote: Kyber (no limit orders) then on-chain Uniswap fee tiers."""
    if amount_in <= 0:
        return None
    cfg = cfg or load_bot_config()

    _, kyber_out = fetch_route(chain, token_in, token_out, amount_in)
    if kyber_out > 0:
        if token_symbol == "VNXAU" and vnxau_addr:
            if not kyber.vnxau_quote_sane(
                amount_in, kyber_out, token_in, token_out, vnxau_addr, chain, vnxau_decimals, cfg
            ):
                kyber_out = 0
        if kyber_out > 0:
            return {"amount_in": amount_in, "amount_out": kyber_out, "provider": "kyber"}

    pools = quote_onchain_pools(chain, token_in, token_out, amount_in, token_symbol)
    valid = [p for p in pools if p.ok]
    if not valid:
        return None
    best = max(valid, key=lambda p: p.amount_out)
    if token_symbol == "VNXAU" and vnxau_addr:
        if not kyber.vnxau_quote_sane(
            amount_in, best.amount_out, token_in, token_out, vnxau_addr, chain, vnxau_decimals, cfg
        ):
            return None
    return {"amount_in": amount_in, "amount_out": best.amount_out, "provider": best.provider}
