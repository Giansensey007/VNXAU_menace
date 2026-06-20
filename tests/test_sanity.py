from src.quotes.sanity import check_stable_peg, check_vnxau_usd_rate, sanity_check_simulation
from src.config_loader import load_bot_config
from src.scanner.simulator import CycleSimulation
from src.sanity.check import sanity_check_config, run_full_sanity


def test_peg_and_vnxau_rate():
    cfg = load_bot_config()
    ok, _ = check_vnxau_usd_rate(135.0, 100.0, cfg)
    assert ok
    ok2, _ = check_stable_peg(135.0, 135.5, cfg)
    assert ok2


def test_sanity_check_simulation_ok():
    sim = CycleSimulation(
        direction="base_to_vnx",
        buy_chain="base",
        sell_chain="vnx",
        size_vnxau=50,
        stable_in_usd=67.5,
        stable_out_usd=68.0,
        token_mid=50,
        net_profit_usd=0.5,
        profitable=True,
        sanity_ok=True,
    )
    ok, issues = sanity_check_simulation(sim)
    assert ok
    assert not issues


def test_sanity_check_config(monkeypatch):
    monkeypatch.setenv("MIN_TRADE_VNXAU", "0.5")
    monkeypatch.setenv("MAX_TRADE_VNXAU", "5")
    ok, issues = sanity_check_config()
    assert ok, issues


def test_run_full_sanity(monkeypatch):
    monkeypatch.setenv("MIN_TRADE_VNXAU", "0.5")
    monkeypatch.setenv("MAX_TRADE_VNXAU", "5")
    ok, evidence = run_full_sanity()
    assert ok, evidence


def test_sanity_rejects_inverted_trade_bounds(monkeypatch):
    monkeypatch.setenv("MIN_TRADE_VNXAU", "500")
    monkeypatch.setenv("MAX_TRADE_VNXAU", "200")
    ok, issues = sanity_check_config()
    assert not ok
    assert any("min_trade_vnxau" in issue for issue in issues)
