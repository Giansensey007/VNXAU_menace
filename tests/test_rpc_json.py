"""JSON-RPC retry and rate-limit classification."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.execution import sol_rpc
from src.quotes import rpc_json


def test_is_json_rpc_rate_limited_solana_codes() -> None:
    assert rpc_json.is_json_rpc_rate_limited({"error": {"code": -32005, "message": "Too many requests"}})
    assert rpc_json.is_json_rpc_rate_limited({"error": {"code": -32429, "message": "rate limited"}})
    assert not rpc_json.is_json_rpc_rate_limited({"error": {"code": -32602, "message": "invalid params"}})
    assert not rpc_json.is_json_rpc_rate_limited({"result": []})


def test_post_json_rpc_does_not_retry_non_rate_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-rate JSON-RPC errors must return immediately (no blind retry loop)."""
    monkeypatch.setenv("RPC_RETRY_MAX", "5")
    calls = {"n": 0}

    def fake_post(*_a, **_k):
        calls["n"] += 1
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"error": {"code": -32602, "message": "invalid params"}}
        return resp

    with patch.object(httpx, "post", side_effect=fake_post):
        with patch.object(rpc_json, "sync_throttle"):
            data = rpc_json.post_json_rpc_sync("https://sol.example", "getBalance", ["addr"])
    assert calls["n"] == 1
    assert data["error"]["code"] == -32602


def test_post_json_rpc_rotates_sol_endpoint_on_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RPC_RETRY_MAX", "1")
    sol_rpc.reset_sol_rpc_url()
    urls: list[str] = []

    def fake_post(url, *_a, **_k):
        urls.append(url)
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"error": {"code": -32005, "message": "Too many requests"}}
        return resp

    with patch.object(httpx, "post", side_effect=fake_post):
        with patch.object(rpc_json, "sync_throttle"):
            with patch.object(rpc_json.time, "sleep"):
                with patch.object(
                    sol_rpc,
                    "sol_rpc_candidates",
                    return_value=["https://sol-a.example", "https://sol-b.example"],
                ):
                    rpc_json.post_json_rpc_sync("https://sol-a.example", "getSignaturesForAddress", ["pk"])
    assert len(urls) >= 2
    assert urls[0] != urls[-1]


def test_sol_rpc_candidates_dedupes_preferred(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RPC_SOLANA", "https://api.mainnet-beta.solana.com")
    cands = sol_rpc.sol_rpc_candidates("https://api.mainnet-beta.solana.com")
    assert cands.count("https://api.mainnet-beta.solana.com") == 1
