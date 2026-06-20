from src.config_loader import load_bot_config, load_chains, load_tokens


def test_load_chains():
    chains = load_chains()
    assert "base" in chains
    assert "solana" in chains
    assert "ethereum" in chains
    assert chains["base"].hub_stable == "USDC"
    assert chains["solana"].hub_stable == "USDC"
    assert chains["ethereum"].hub_stable == "USDC"
    assert chains["base"].quote_tier == "aggregator"
    assert chains["ethereum"].quote_tier == "aggregator"
    assert chains["base"].kyber_slug == "base"
    assert chains["ethereum"].kyber_slug == "ethereum"


def test_load_tokens():
    tokens = load_tokens()
    assert "VNXAU" in tokens
    assert "base" in tokens["VNXAU"].chains
    assert "solana" in tokens["VNXAU"].chains
    assert "ethereum" in tokens["VNXAU"].chains
    assert tokens["VNXAU"].chains["ethereum"].lower() == "0x6d57b2e05f26c26b549231c866bdd39779e4a488"


def test_bot_yaml_min_sizes(monkeypatch):
    monkeypatch.delenv("MIN_TRADE_VNXAU", raising=False)
    monkeypatch.delenv("MAX_TRADE_VNXAU", raising=False)
    cfg = load_bot_config()
    assert cfg.min_trade_vnxau == 0.4
    assert cfg.max_trade_vnxau == 5.0
    assert cfg.probe_sizes[0] == 0.4
    assert cfg.vnxau_usd_min == 80
    assert cfg.vnxau_usd_max == 250
    assert cfg.platform_vnxau_only is True
    assert cfg.jit_withdraw is True
