from __future__ import annotations

import os
from typing import Any

import httpx

from src.config_loader import BotConfig, ChainConfig
from src.quotes.addresses import checksum
from src.quotes.rate_limit import get_with_retry
from src.quotes.types import ProviderQuote, to_human

KYBER_BASE = os.getenv("KYBER_API_URL", "https://aggregator-api.kyberswap.com").rstrip("/")
KYBER_CLIENT_ID = os.getenv("KYBER_CLIENT_ID", "vnxau-menace")
KYBER_EXCLUDED_SOURCES = os.getenv(
    "KYBER_EXCLUDED_SOURCES",
    "kyberswap-limit-order,kyberswap-limit-order-v2",
).strip()


def kyber_headers() -> dict[str, str]:
    return {"X-Client-Id": KYBER_CLIENT_ID}


def route_params(token_in: str, token_out: str, amount_in: int) -> dict[str, str]:
    params = {
        "tokenIn": checksum(token_in),
        "tokenOut": checksum(token_out),
        "amountIn": str(amount_in),
    }
    if KYBER_EXCLUDED_SOURCES:
        params["excludedSources"] = KYBER_EXCLUDED_SOURCES
    return params


def routes_url(chain: ChainConfig) -> str:
    return f"{KYBER_BASE}/{chain.kyber_slug}/api/v1/routes"


def parse_route_response(data: dict[str, Any], amount_in: int) -> tuple[dict | None, int, list[str]]:
    summary = data.get("routeSummary") or {}
    amount_out = int(summary.get("amountOut") or 0)
    route_dexs = _extract_dexs(summary.get("route") or [])
    if amount_out <= 0:
        return None, 0, route_dexs
    return summary, amount_out, route_dexs


def implied_vnxau_usd_rate(
    amount_in: int,
    amount_out: int,
    token_in: str,
    token_out: str,
    vnxau_addr: str,
    hub_token: str,
    vnxau_decimals: int,
    hub_decimals: int,
) -> float | None:
    if amount_in <= 0 or amount_out <= 0:
        return None
    vnxau = checksum(vnxau_addr)
    hub = checksum(hub_token)
    tin, tout = checksum(token_in), checksum(token_out)
    if tin == vnxau and tout == hub:
        vnxau_human = float(to_human(amount_in, vnxau_decimals))
        stable_human = float(to_human(amount_out, hub_decimals))
    elif tin == hub and tout == vnxau:
        stable_human = float(to_human(amount_in, hub_decimals))
        vnxau_human = float(to_human(amount_out, vnxau_decimals))
    else:
        return None
    if vnxau_human <= 0:
        return None
    return stable_human / vnxau_human


def vnxau_rate_ok(rate: float | None, cfg: BotConfig) -> bool:
    if rate is None:
        return True
    return cfg.vnxau_usd_min <= rate <= cfg.vnxau_usd_max


def vnxau_quote_sane(
    amount_in: int,
    amount_out: int,
    token_in: str,
    token_out: str,
    vnxau_addr: str,
    chain: ChainConfig,
    vnxau_decimals: int,
    cfg: BotConfig,
) -> bool:
    rate = implied_vnxau_usd_rate(
        amount_in,
        amount_out,
        token_in,
        token_out,
        vnxau_addr,
        chain.hub_token,
        vnxau_decimals,
        chain.hub_decimals,
    )
    return vnxau_rate_ok(rate, cfg)


async def quote(
    client: httpx.AsyncClient,
    chain: ChainConfig,
    token_in: str,
    token_out: str,
    amount_in: int,
) -> ProviderQuote:
    if not chain.kyber_slug:
        return ProviderQuote("kyber", amount_in, 0, error="unsupported chain")
    url = routes_url(chain)
    params = route_params(token_in, token_out, amount_in)
    try:
        resp = await get_with_retry(client, url, params=params, headers=kyber_headers(), timeout=20.0)
        if resp.status_code == 429:
            return ProviderQuote("kyber", amount_in, 0, error="rate limited")
        if resp.status_code >= 400:
            try:
                err_body = resp.json()
                msg = err_body.get("message") or resp.text[:200]
            except Exception:
                msg = resp.text[:200]
            return ProviderQuote("kyber", amount_in, 0, error=str(msg))
        _, amount_out, route_dexs = parse_route_response(resp.json().get("data", {}), amount_in)
        if amount_out <= 0:
            return ProviderQuote("kyber", amount_in, 0, error="no route")
        return ProviderQuote("kyber", amount_in, amount_out, route_dexs=route_dexs)
    except Exception as exc:
        return ProviderQuote("kyber", amount_in, 0, error=str(exc))


def _extract_dexs(route: list) -> list[str]:
    dexs: list[str] = []
    for hop in route:
        if isinstance(hop, list):
            for sub in hop:
                name = sub.get("exchange") or sub.get("pool") or "unknown"
                if name not in dexs:
                    dexs.append(str(name))
        elif isinstance(hop, dict):
            name = hop.get("exchange") or hop.get("pool") or "unknown"
            if name not in dexs:
                dexs.append(str(name))
    return dexs or ["KyberRoute"]
