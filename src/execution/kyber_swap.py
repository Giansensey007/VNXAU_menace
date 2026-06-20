from __future__ import annotations

import logging
import os
from typing import Any, Protocol

import httpx

from src.config_loader import ChainConfig
from src.quotes.addresses import checksum
from src.quotes.kyber import (
    KYBER_BASE,
    kyber_headers,
    parse_route_response,
    route_params,
    routes_url,
)
from src.quotes.sync_throttle import retry_backoff_sec, sync_throttle

logger = logging.getLogger(__name__)

_MAX_KYBER_ATTEMPTS = int(os.getenv("API_RETRY_MAX", "6"))


def _is_kyber_retryable(status_code: int, body: str = "") -> bool:
    if status_code in (429, 502, 503, 504):
        return True
    if status_code == 403 and "rate" in body.lower():
        return True
    return False


def _kyber_request(method: str, url: str, **kwargs: Any) -> httpx.Response | None:
    import time

    for attempt in range(_MAX_KYBER_ATTEMPTS):
        sync_throttle("kyber")
        try:
            with httpx.Client(timeout=25.0) as client:
                resp = client.request(method, url, **kwargs)
            if _is_kyber_retryable(resp.status_code, resp.text):
                wait = retry_backoff_sec(attempt)
                logger.warning("Kyber %s HTTP %s — retry in %.1fs", method, resp.status_code, wait)
                time.sleep(wait)
                continue
            return resp
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
            if attempt + 1 >= _MAX_KYBER_ATTEMPTS:
                logger.warning("Kyber %s network error: %s", method, exc)
                return None
            wait = retry_backoff_sec(attempt)
            logger.warning("Kyber %s network error: %s — retry in %.1fs", method, exc, wait)
            time.sleep(wait)
    return None


class _EvmSwapExecutor(Protocol):
    account: Any
    chain: ChainConfig
    last_error: str | None

    def approve_if_needed(self, token: str, spender: str, amount: int) -> str | None: ...
    def _build_and_send(self, tx: dict, *, fn=None) -> str | None: ...


def fetch_route(
    chain: ChainConfig,
    token_in: str,
    token_out: str,
    amount_in: int,
) -> tuple[dict | None, int]:
    """Return (routeSummary, amountOut) from KyberSwap v1 routes API."""
    if not chain.kyber_slug or amount_in <= 0:
        return None, 0
    url = routes_url(chain)
    params = route_params(token_in, token_out, amount_in)
    resp = _kyber_request(
        "GET",
        url,
        params=params,
        headers={**kyber_headers(), "Content-Type": "application/json"},
    )
    if resp is None:
        return None, 0
    if resp.status_code >= 400:
        logger.warning("Kyber route HTTP %s: %s", resp.status_code, resp.text[:160])
        return None, 0
    try:
        summary, amount_out, _ = parse_route_response(resp.json().get("data", {}), amount_in)
        if not summary or amount_out <= 0:
            return None, 0
        return summary, amount_out
    except Exception as exc:
        logger.warning("Kyber route fetch failed: %s", exc)
        return None, 0


def build_swap_tx(
    chain: ChainConfig,
    route_summary: dict,
    sender: str,
    *,
    slippage_bps: int = 50,
) -> dict | None:
    """Encode swap calldata via KyberSwap v1 route/build."""
    if not chain.kyber_slug:
        return None
    url = f"{KYBER_BASE}/{chain.kyber_slug}/api/v1/route/build"
    wallet = checksum(sender)
    payload = {
        "routeSummary": route_summary,
        "sender": wallet,
        "recipient": wallet,
        "slippageTolerance": max(1, slippage_bps),
    }
    resp = _kyber_request("POST", url, json=payload, headers=kyber_headers())
    if resp is None:
        return None
    if resp.status_code >= 400:
        logger.warning("Kyber build HTTP %s: %s", resp.status_code, resp.text[:160])
        return None
    try:
        body = resp.json().get("data") or {}
        if not body.get("data") or not body.get("routerAddress"):
            return None
        return body
    except Exception as exc:
        logger.warning("Kyber build failed: %s", exc)
        return None


def swap_via_kyber(
    executor: _EvmSwapExecutor,
    token_in: str,
    token_out: str,
    amount_in: int,
    amount_out_min: int,
    *,
    slippage_bps: int = 50,
) -> str | None:
    """Execute swap through KyberSwap aggregator router."""
    chain = executor.chain
    route_summary, quoted_out = fetch_route(chain, token_in, token_out, amount_in)
    if not route_summary:
        executor.last_error = "kyber: no route"
        return None
    if quoted_out < amount_out_min:
        executor.last_error = f"kyber quote {quoted_out} < min {amount_out_min}"
        return None

    built = build_swap_tx(chain, route_summary, executor.account.address, slippage_bps=slippage_bps)
    if not built:
        executor.last_error = "kyber: build route failed"
        return None

    router = checksum(built["routerAddress"])
    executor.approve_if_needed(token_in, router, amount_in)
    tx = {
        "from": executor.account.address,
        "to": router,
        "data": built["data"],
        "value": int(built.get("transactionValue") or 0),
    }
    try:
        tx["gas"] = executor.w3.eth.estimate_gas(tx)  # type: ignore[attr-defined]
    except Exception:
        tx["gas"] = int(built.get("gas") or 500_000)

    if hasattr(executor, "_tx_base"):
        base = executor._tx_base()  # type: ignore[attr-defined]
    else:
        base = executor._base_tx(type("_Fn", (), {"estimate_gas": lambda _s, _x: tx["gas"]})())  # type: ignore[attr-defined]

    for key in ("nonce", "gasPrice", "maxFeePerGas", "maxPriorityFeePerGas", "chainId"):
        if key in base:
            tx[key] = base[key]
    if "gas" not in tx and "gas" in base:
        tx["gas"] = base["gas"]
    return executor._build_and_send(tx)
