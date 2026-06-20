"""JSON-RPC and REST helpers with retry + throttle (sync and async)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from src.quotes.rate_limit import get_with_retry, post_with_retry
from src.quotes.sync_throttle import retry_backoff_sec, sync_throttle

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = int(os.getenv("RPC_RETRY_MAX", "5"))


def _rpc_backoff_sec(provider: str, attempt: int) -> float:
    if provider == "solana_rpc":
        from src.execution.sol_rpc import sol_rpc_backoff_sec

        return sol_rpc_backoff_sec(attempt)
    return retry_backoff_sec(attempt)


def _is_retryable_status(code: int, body: str = "") -> bool:
    if code in (429, 502, 503, 504):
        return True
    if code == 403 and "rate" in body.lower():
        return True
    return False


def is_json_rpc_rate_limited(data: dict[str, Any]) -> bool:
    err = data.get("error")
    if not err:
        return False
    if isinstance(err, dict) and err.get("code") in (-32005, -32429):
        return True
    text = str(err).lower()
    return "429" in text or "too many requests" in text or "rate limit" in text


def post_json_rpc_sync(
    rpc_url: str,
    method: str,
    params: list[Any],
    *,
    provider: str = "solana_rpc",
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Sync Solana/EVM JSON-RPC POST with throttle, retry, and Solana endpoint rotation."""
    from src.execution.sol_rpc import rotate_sol_rpc_url, sol_rpc_candidates

    urls = sol_rpc_candidates(rpc_url) if provider == "solana_rpc" else [rpc_url]
    last: dict[str, Any] = {}

    for url_idx, url in enumerate(urls):
        for attempt in range(_MAX_ATTEMPTS):
            sync_throttle(provider)
            try:
                resp = httpx.post(
                    url,
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    timeout=timeout,
                )
                if _is_retryable_status(resp.status_code, resp.text):
                    wait = _rpc_backoff_sec(provider, attempt)
                    logger.warning("RPC %s HTTP %s — retry in %.1fs", method, resp.status_code, wait)
                    time.sleep(wait)
                    continue
                data = resp.json()
                last = data
                if is_json_rpc_rate_limited(data):
                    wait = _rpc_backoff_sec(provider, attempt)
                    logger.warning("RPC %s rate limited %s — retry in %.1fs", method, data.get("error"), wait)
                    time.sleep(wait)
                    if attempt + 1 >= _MAX_ATTEMPTS:
                        break
                    continue
                return data
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
                last = {"error": str(exc)}
                if attempt + 1 >= _MAX_ATTEMPTS:
                    break
                wait = _rpc_backoff_sec(provider, attempt)
                logger.warning("RPC %s network error: %s — retry in %.1fs", method, exc, wait)
                time.sleep(wait)
        if url_idx + 1 < len(urls) and provider == "solana_rpc":
            rotate_sol_rpc_url(rpc_url)
    return last


async def get_http_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    provider: str = "default",
    **kwargs: Any,
) -> httpx.Response:
    """GET with shared async retry layer."""
    return await get_with_retry(client, url, **kwargs)


async def fetch_blockscout_txs(address: str, *, limit: int = 20) -> list[str]:
    """Blockscout address tx list with retry."""
    url = f"https://eth.blockscout.com/api/v2/addresses/{address}/transactions"
    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(_MAX_ATTEMPTS):
            resp = await get_with_retry(client, url, timeout=30.0)
            if resp.status_code == 200:
                out: list[str] = []
                for row in resp.json().get("items") or []:
                    h = row.get("hash")
                    if h:
                        out.append(str(h))
                    if len(out) >= limit:
                        break
                return out
            if _is_retryable_status(resp.status_code, resp.text) and attempt + 1 < _MAX_ATTEMPTS:
                import asyncio

                await asyncio.sleep(retry_backoff_sec(attempt))
                continue
            logger.warning("Blockscout HTTP %s for %s", resp.status_code, address[:12])
            return []
    return []
