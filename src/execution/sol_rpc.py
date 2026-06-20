"""Solana JSON-RPC call wrapper with throttle and retry."""

from __future__ import annotations

import logging
import os
import random
from collections.abc import Callable
from typing import TypeVar

from src.config_loader import DEFAULT_RPC, SOL_RPC_FALLBACKS
from src.quotes.sync_throttle import retry_backoff_sec, sync_throttle

logger = logging.getLogger(__name__)

T = TypeVar("T")

_MAX_ATTEMPTS = int(os.getenv("RPC_RETRY_MAX", "4"))
SOL_BALANCE_POLL_SEC = float(os.getenv("SOL_BALANCE_POLL_SEC", "5"))

_sol_rpc_index = 0


def sol_rpc_candidates(preferred: str | None = None) -> list[str]:
    """Ordered Solana RPC endpoints: preferred → env → default → public fallbacks."""
    candidates: list[str] = []
    if preferred:
        candidates.append(preferred.rstrip("/"))
    env = os.getenv("RPC_SOLANA", "").strip()
    if env and env not in candidates:
        candidates.append(env.rstrip("/"))
    default = DEFAULT_RPC.get("RPC_SOLANA", "")
    if default and default not in candidates:
        candidates.append(default.rstrip("/"))
    for url in SOL_RPC_FALLBACKS:
        if url not in candidates:
            candidates.append(url)
    return candidates


def current_sol_rpc_url(preferred: str | None = None) -> str:
    cands = sol_rpc_candidates(preferred)
    return cands[min(_sol_rpc_index, len(cands) - 1)]


def rotate_sol_rpc_url(preferred: str | None = None) -> str:
    global _sol_rpc_index
    cands = sol_rpc_candidates(preferred)
    _sol_rpc_index = (_sol_rpc_index + 1) % len(cands)
    url = cands[_sol_rpc_index]
    logger.warning("Rotating Solana RPC to %s", url)
    return url


def reset_sol_rpc_url() -> None:
    global _sol_rpc_index
    _sol_rpc_index = 0


def sol_rpc_backoff_sec(attempt: int) -> float:
    """Exponential backoff for Solana RPC 429 / rate-limit responses."""
    base = float(
        os.getenv(
            "SOL_RPC_429_BACKOFF_SEC",
            os.getenv("API_RETRY_BACKOFF_BASE_SEC", "8.0"),
        )
    )
    cap = float(os.getenv("API_RETRY_BACKOFF_CAP_SEC", "120.0"))
    return min(cap, base * (2**attempt)) + random.uniform(0, 0.5)


def is_sol_retryable(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        k in msg
        for k in (
            "429",
            "too many requests",
            "rate limit",
            "blockhash",
            "block height",
            "blockhashnotfound",
            "transactionexpired",
            "timeout",
            "connection",
            "temporarily unavailable",
            "503",
            "502",
        )
    )


def is_jupiter_slippage_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "6024" in msg or "0x1788" in msg or "slippage" in msg


def call_with_retry(fn: Callable[[], T], *, label: str = "sol-rpc", max_attempts: int | None = None) -> T:
    attempts = max_attempts or _MAX_ATTEMPTS
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            sync_throttle("solana_rpc")
            return fn()
        except Exception as exc:
            last = exc
            rate_limited = any(k in str(exc).lower() for k in ("429", "too many requests", "rate limit"))
            if rate_limited and attempt + 1 >= attempts:
                rotate_sol_rpc_url()
            if attempt + 1 >= attempts or not is_sol_retryable(exc):
                raise
            wait = sol_rpc_backoff_sec(attempt) if rate_limited else retry_backoff_sec(attempt)
            logger.warning(
                "%s failed (attempt %s/%s): %s — retry in %.1fs",
                label,
                attempt + 1,
                attempts,
                exc,
                wait,
            )
            import time

            time.sleep(wait)
    if last:
        raise last
    raise RuntimeError(f"{label} failed with no exception")
