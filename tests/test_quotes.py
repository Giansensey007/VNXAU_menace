import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.quotes.jupiter import quote
from src.quotes.types import ProviderQuote, from_human


@pytest.mark.asyncio
async def test_kyber_quote_base_mock():
    from src.config_loader import load_chains
    from src.quotes import kyber

    chain = load_chains()["base"]
    amount = 1_000_000_000_000_000_000  # 1 VNXAU
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "routeSummary": {
                "amountOut": "131000000",
                "route": [[{"exchange": "UniswapV3"}]],
            }
        }
    }

    with patch("src.quotes.kyber.get_with_retry", new=AsyncMock(return_value=mock_resp)):
        q = await kyber.quote(
            AsyncMock(),
            chain,
            "0xac3fe22294beaed9d1fd752323a6d06d12ff3098",
            chain.hub_token,
            amount,
        )
    assert q.ok
    assert q.amount_out == 131_000_000
    assert q.provider == "kyber"


@pytest.mark.asyncio
async def test_kyber_quote_mock():
    from src.config_loader import load_chains
    from src.quotes import kyber

    chain = load_chains()["ethereum"]
    amount = 1_000_000_000_000_000_000  # 1 VNXAU
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "routeSummary": {
                "amountOut": "131000000",
                "route": [[{"exchange": "UniswapV3"}]],
            }
        }
    }

    with patch("src.quotes.kyber.get_with_retry", new=AsyncMock(return_value=mock_resp)):
        q = await kyber.quote(
            AsyncMock(),
            chain,
            "0x6d57B2E05F26C26b549231c866bdd39779e4a488",
            chain.hub_token,
            amount,
        )
    assert q.ok
    assert q.amount_out == 131_000_000
    assert q.provider == "kyber"


@pytest.mark.asyncio
async def test_router_kyber_with_uniswap_fallback():
    from src.config_loader import load_chains
    from src.quotes.router import quote_best

    chain = load_chains()["base"]
    token_in = chain.hub_token
    token_out = "0xac3fe22294beaed9d1fd752323a6d06d12ff3098"
    amount = 5_000_000

    async def fake_kyber(*_a, **_k):
        return ProviderQuote("kyber", amount, 0, error="no route")

    def fake_onchain(*_a, **_k):
        # ~$131/VNXAU: 5 USDC buys ~0.038 VNXAU
        return [ProviderQuote("uniswap_v3", amount, 38_000_000_000_000_000, route_dexs=["UniswapV3-3000"])]

    with patch("src.quotes.router.kyber.quote", new=fake_kyber), patch(
        "src.quotes.router.onchain.quote_onchain_pools", new=fake_onchain
    ), patch("src.quotes.router.api_sync", new=AsyncMock()):
        q = await quote_best(AsyncMock(), chain, token_in, token_out, amount, 6, 18, "VNXAU")
    assert q is not None
    assert q.provider == "uniswap_v3"


@pytest.mark.asyncio
async def test_kyber_rejects_limit_order_garbage():
    from src.config_loader import load_bot_config, load_chains, load_tokens, token_decimals
    from src.quotes import kyber

    chain = load_chains()["ethereum"]
    token = load_tokens()["VNXAU"]
    dec = token_decimals(token, "ethereum")
    vnxau = token.chains["ethereum"]
    amount = from_human(50, dec)
    cfg = load_bot_config()

    bad_out = from_human(10.0 * 50, chain.hub_decimals)  # $10/VNXAU
    assert not kyber.vnxau_quote_sane(amount, bad_out, vnxau, chain.hub_token, vnxau, chain, dec, cfg)

    good_out = from_human(131.0 * 50, chain.hub_decimals)
    assert kyber.vnxau_quote_sane(amount, good_out, vnxau, chain.hub_token, vnxau, chain, dec, cfg)


@pytest.mark.asyncio
async def test_kyber_route_params_exclude_limit_orders():
    from src.quotes import kyber

    params = kyber.route_params(
        "0x6d57B2E05F26C26b549231c866bdd39779e4a488",
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        1_000_000,
    )
    assert "excludedSources" in params
    assert "limit-order" in params["excludedSources"]


@pytest.mark.asyncio
async def test_router_rejects_bad_kyber_eth_quote():
    from src.config_loader import load_chains, load_tokens, token_decimals
    from src.quotes.router import sell_token_for_stable

    chain = load_chains()["ethereum"]
    token = load_tokens()["VNXAU"]
    dec = token_decimals(token, "ethereum")
    amount = from_human(50, dec)

    async def fake_kyber(*_a, **_k):
        return ProviderQuote("kyber", amount, 516_000_000)  # ~$10/VNXAU

    with patch("src.quotes.router.kyber.quote", new=fake_kyber), patch(
        "src.quotes.router.onchain.quote_onchain_pools", return_value=[]
    ), patch("src.quotes.router.api_sync", new=AsyncMock()):
        q = await sell_token_for_stable(AsyncMock(), chain, token, "ethereum", amount)
    assert q is None


def test_sanitize_rpc_url():
    from src.config_loader import _sanitize_rpc_url

    assert _sanitize_rpc_url("https://ethereum.publicnode.comVNX_BASE_") == "https://ethereum.publicnode.com"
    assert _sanitize_rpc_url("  https://base.llamarpc.com  ") == "https://base.llamarpc.com"


@pytest.mark.asyncio
async def test_jupiter_quote_mock():
    amount = 1_000_000_000
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"outAmount": "1350000", "routePlan": []}

    with patch("src.quotes.jupiter.get_with_retry", new=AsyncMock(return_value=mock_resp)):
        q = await quote(AsyncMock(), "mint_in", "mint_out", amount)
    assert q.ok
    assert q.amount_out == 1_350_000


@pytest.mark.asyncio
async def test_vnx_platform_quote_mock():
    from src.quotes import vnx

    amount = 50_000_000_000_000_000_000  # 50 VNXAU
    mock_quotes = {"VNXAU/USDC": {"b": [1.35, 50000], "a": [1.36, 50000]}}

    with patch("src.quotes.vnx._load_quotes", new=AsyncMock(return_value=mock_quotes)):
        q = await vnx.quote_sell_token_for_usdc(AsyncMock(), "VNXAU", amount, 18, 6)
    assert q.ok


@pytest.mark.asyncio
async def test_vnx_rejects_zero_bid_liquidity():
    from src.quotes import vnx

    amount = 50_000_000_000_000_000_000
    mock_quotes = {"VNXAU/USDC": {"b": [1.35, 0], "a": [1.36, 50000]}}

    with patch("src.quotes.vnx._load_quotes", new=AsyncMock(return_value=mock_quotes)):
        q = await vnx.quote_sell_token_for_usdc(AsyncMock(), "VNXAU", amount, 18, 6)
    assert not q.ok
    assert "bid liquidity" in (q.error or "")


@pytest.mark.asyncio
async def test_vnx_load_quotes_surfaces_http_errors():
    from src.quotes import vnx

    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.text = "service unavailable"

    with patch("src.quotes.vnx.VNX_API_PUBLIC_KEY", "test-key"):
        with patch("src.quotes.vnx.get_with_retry", new=AsyncMock(return_value=mock_resp)):
            with pytest.raises(RuntimeError, match="503"):
                await vnx._load_quotes(AsyncMock())


@pytest.mark.asyncio
async def test_rate_limit_releases_semaphore_during_backoff():
    from src.quotes import rate_limit

    rate_limit._api_sem = asyncio.Semaphore(1)
    client = AsyncMock()
    resp429 = MagicMock()
    resp429.status_code = 429
    resp429.text = "rate limited"
    resp200 = MagicMock()
    resp200.status_code = 200
    resp200.text = "ok"
    client.request = AsyncMock(side_effect=[resp429, resp200])

    acquired_during_backoff = False

    original_sleep = asyncio.sleep

    async def spy_sleep(sec):
        nonlocal acquired_during_backoff
        if rate_limit._api_sem.locked():
            acquired_during_backoff = True
        await original_sleep(0)

    with patch.object(rate_limit.asyncio, "sleep", side_effect=spy_sleep):
        with patch.object(rate_limit, "QUOTE_DELAY_MS", 0):
            with patch.object(rate_limit, "BACKOFF_BASE_SEC", 0.001):
                with patch.object(rate_limit, "api_sync", new=AsyncMock()):
                    r = await rate_limit.get_with_retry(client, "https://api.jup.ag/test")
    assert not acquired_during_backoff
    assert r.status_code == 200
    assert client.request.await_count == 2


def test_onchain_mock():
    from src.quotes.onchain import quote_pool

    w3 = MagicMock()
    contract = MagicMock()
    w3.eth.contract.return_value = contract
    contract.functions.quoteExactInputSingle.return_value.call.return_value = (900_000, 0, 0, 0)

    token_a = "0x" + "a" * 40
    token_b = "0x" + "b" * 40
    q = quote_pool(w3, "0x82825d0554fA07f7FC52Ab63c961F330fdEFa8E8", token_a, token_b, 1_000_000, 100)
    assert q.ok
