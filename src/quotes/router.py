from __future__ import annotations

import asyncio

import httpx

from src.config_loader import ChainConfig, TokenConfig, load_bot_config, load_tokens, token_decimals
from src.quotes import jupiter, kyber, onchain, vnx
from src.quotes.api_gate import api_sync
from src.quotes.types import ProviderQuote, QuoteResult


def _reject_bad_kyber_vnxau(
    pq: ProviderQuote,
    chain: ChainConfig,
    token_in: str,
    token_out: str,
    amount_in: int,
    token_symbol: str,
    token: TokenConfig,
    chain_key: str,
) -> ProviderQuote:
    if not pq.ok or token_symbol != "VNXAU":
        return pq
    vnxau_addr = token.chains.get(chain_key, "")
    if not vnxau_addr:
        return pq
    dec = token_decimals(token, chain_key)
    cfg = load_bot_config()
    if kyber.vnxau_quote_sane(amount_in, pq.amount_out, token_in, token_out, vnxau_addr, chain, dec, cfg):
        return pq
    return ProviderQuote(
        "kyber",
        amount_in,
        0,
        error=f"rate outside [{cfg.vnxau_usd_min}, {cfg.vnxau_usd_max}]",
    )


async def _evm_quotes(
    client: httpx.AsyncClient,
    chain: ChainConfig,
    token_in: str,
    token_out: str,
    amount_in: int,
    token_symbol: str,
    token: TokenConfig,
    chain_key: str,
) -> list[ProviderQuote]:
    providers: list[ProviderQuote] = []
    kyber_q = await kyber.quote(client, chain, token_in, token_out, amount_in)
    kyber_q = _reject_bad_kyber_vnxau(kyber_q, chain, token_in, token_out, amount_in, token_symbol, token, chain_key)
    providers.append(kyber_q)
    if not kyber_q.ok:
        pool_quotes = await asyncio.to_thread(
            onchain.quote_onchain_pools, chain, token_in, token_out, amount_in, token_symbol
        )
        for pq in pool_quotes:
            if pq.ok and token_symbol == "VNXAU":
                vnxau_addr = token.chains.get(chain_key, "")
                dec = token_decimals(token, chain_key)
                cfg = load_bot_config()
                if vnxau_addr and not kyber.vnxau_quote_sane(
                    amount_in, pq.amount_out, token_in, token_out, vnxau_addr, chain, dec, cfg
                ):
                    pq = ProviderQuote(pq.provider, amount_in, 0, error="onchain rate outside sanity band")
            providers.append(pq)
    return providers


async def quote_best(
    client: httpx.AsyncClient,
    chain: ChainConfig,
    token_in: str,
    token_out: str,
    amount_in: int,
    src_decimals: int,
    dest_decimals: int,
    token_symbol: str = "",
) -> QuoteResult | None:
    if amount_in <= 0:
        return None

    if chain.quote_tier == "aggregator":
        await api_sync("kyber")
        token_cfg = load_tokens()[token_symbol] if token_symbol else None
        if not token_cfg:
            return None
        providers = await _evm_quotes(
            client, chain, token_in, token_out, amount_in, token_symbol, token_cfg, chain.key
        )
    elif chain.quote_tier == "onchain":
        await api_sync("base_rpc")
        providers = await asyncio.to_thread(
            onchain.quote_onchain_pools, chain, token_in, token_out, amount_in, token_symbol
        )
    elif chain.quote_tier == "jupiter":
        providers = [await jupiter.quote(client, token_in, token_out, amount_in)]
    elif chain.quote_tier == "vnx":
        if not token_symbol:
            return None
        if token_in == chain.hub_token:
            pq = await vnx.quote_buy_token_with_usdc(
                client, token_symbol, amount_in, dest_decimals, src_decimals
            )
        else:
            pq = await vnx.quote_sell_token_for_usdc(
                client, token_symbol, amount_in, src_decimals, dest_decimals
            )
        providers = [pq]
    else:
        return None

    valid = [p for p in providers if p.ok]
    if not valid:
        return None
    best = max(valid, key=lambda p: p.amount_out)
    return QuoteResult(
        provider=best.provider,
        amount_in=amount_in,
        amount_out=best.amount_out,
        route_dexs=best.route_dexs,
        all_providers=providers,
        token_in=token_in,
        token_out=token_out,
        chain_key=chain.key,
        hub_stable=chain.hub_stable,
    )


async def sell_token_for_stable(
    client: httpx.AsyncClient,
    chain: ChainConfig,
    token: TokenConfig,
    chain_key: str,
    amount_in: int,
) -> QuoteResult | None:
    token_addr = token.chains.get(chain_key)
    if not token_addr:
        return None
    dec = token_decimals(token, chain_key)
    result = await quote_best(
        client, chain, token_addr, chain.hub_token, amount_in, dec, chain.hub_decimals, token.symbol
    )
    if result or chain_key != "ethereum":
        return result
    pq = await vnx.quote_sell_token_for_usdc(
        client, token.symbol, amount_in, dec, chain.hub_decimals
    )
    if not pq.ok:
        return None
    return QuoteResult(
        provider=f"{pq.provider}-eth-fallback",
        amount_in=pq.amount_in,
        amount_out=pq.amount_out,
        route_dexs=pq.route_dexs,
        all_providers=[pq],
        token_in=token_addr,
        token_out=chain.hub_token,
        chain_key=chain_key,
        hub_stable=chain.hub_stable,
    )


async def buy_token_with_stable(
    client: httpx.AsyncClient,
    chain: ChainConfig,
    token: TokenConfig,
    chain_key: str,
    stable_amount: int,
) -> QuoteResult | None:
    token_addr = token.chains.get(chain_key)
    if not token_addr:
        return None
    dec = token_decimals(token, chain_key)
    result = await quote_best(
        client, chain, chain.hub_token, token_addr, stable_amount, chain.hub_decimals, dec, token.symbol
    )
    if result or chain_key != "ethereum":
        return result
    pq = await vnx.quote_buy_token_with_usdc(
        client, token.symbol, stable_amount, dec, chain.hub_decimals
    )
    if not pq.ok:
        return None
    return QuoteResult(
        provider=f"{pq.provider}-eth-fallback",
        amount_in=pq.amount_in,
        amount_out=pq.amount_out,
        route_dexs=pq.route_dexs,
        all_providers=[pq],
        token_in=chain.hub_token,
        token_out=token_addr,
        chain_key=chain_key,
        hub_stable=chain.hub_stable,
    )
