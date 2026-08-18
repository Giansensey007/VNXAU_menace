"""Pre-launch gates: env example, Kyber id, yaml bounds, token addresses, DB isolation."""

from __future__ import annotations

from pathlib import Path

from src.config_loader import load_bot_config, load_chains, load_tokens

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_KYBER = "vnxau-menace"
OTHER_KYBER = ("gbp-menace", "vchf-menace")


def test_env_example_base_and_db():
    text = (ROOT / ".env.example").read_text()
    for needle in ("RPC_BASE", "BASE_PRIVATE_KEY", "VNX_BASE_"):
        assert needle in text
    assert "DB_PATH=data/bot.db" in text
    db_lines = [ln for ln in text.splitlines() if ln.startswith("DB_PATH=")]
    assert db_lines == ["DB_PATH=data/bot.db"]


def test_kyber_client_id_in_quote_and_swap():
    quotes = (ROOT / "src" / "quotes" / "kyber.py").read_text()
    swap = (ROOT / "src" / "execution" / "kyber_swap.py").read_text()
    assert f'"{EXPECTED_KYBER}"' in quotes
    for other in OTHER_KYBER:
        assert f'"{other}"' not in quotes
        assert f'"{other}"' not in swap
    has_default = f'"{EXPECTED_KYBER}"' in swap
    imports_quotes = "from src.quotes.kyber import" in swap and "KYBER_CLIENT_ID" in swap
    assert has_default or imports_quotes


def test_yaml_min_max_when_env_cleared(monkeypatch):
    monkeypatch.delenv("MIN_TRADE_VNXAU", raising=False)
    monkeypatch.delenv("MAX_TRADE_VNXAU", raising=False)
    cfg = load_bot_config()
    assert cfg.min_trade_vnxau == 0.4
    assert cfg.max_trade_vnxau == 5


def test_token_addresses_and_base_chain_id():
    token = load_tokens()["VNXAU"]
    chains = load_chains()
    assert token.chains["base"].lower() == "0xac3fe22294beaed9d1fd752323a6d06d12ff3098"
    assert chains["base"].hub_token.lower() == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    assert chains["base"].chain_id == 8453
    assert "ethereum" in token.chains
    assert chains["ethereum"].chain_id == 1
