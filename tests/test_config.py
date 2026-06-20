from src.config_loader import load_chains, load_tokens


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
