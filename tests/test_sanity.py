from src.config_loader import load_bot_config
from src.quotes.sanity import check_stable_peg, check_vnxau_usd_rate, sanity_check_simulation
from src.scanner.simulator import CycleSimulation
from src.sanity.check import sanity_check_config, run_full_sanity
from src.vnx.deposits import min_deposit_vnxau
from src.vnx.trading import VNXAU_MIN_ORDER


def test_peg_and_vnxau_rate():
    cfg = load_bot_config()
    ok, _ = check_vnxau_usd_rate(13_500.0, 100.0, cfg)  # ~$135/VNXAU gold band
    assert ok
    ok2, _ = check_stable_peg(135.0, 135.5, cfg)
    assert ok2


def test_vnxau_rate_rejects_outside_sanity_band():
    cfg = load_bot_config()
    ok_low, msg_low = check_vnxau_usd_rate(50.0, 1.0, cfg)
    assert not ok_low
    assert "80" in msg_low
    ok_high, msg_high = check_vnxau_usd_rate(300.0, 1.0, cfg)
    assert not ok_high
    assert "250" in msg_high


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


def test_bot_config_min_sizes(monkeypatch):
    monkeypatch.delenv("MIN_TRADE_VNXAU", raising=False)
    cfg = load_bot_config()
    assert cfg.min_trade_vnxau == 0.4
    assert cfg.vnxau_usd_min == 80
    assert cfg.vnxau_usd_max == 250
    assert cfg.platform_vnxau_only is True
    assert cfg.jit_withdraw is True
    assert VNXAU_MIN_ORDER == 0.4
    assert min_deposit_vnxau("BASE") == 5.0
    assert min_deposit_vnxau("SOL") == 5.0


def test_sanity_check_config(monkeypatch):
    monkeypatch.setenv("MIN_TRADE_VNXAU", "0.4")
    monkeypatch.setenv("MAX_TRADE_VNXAU", "5")
    ok, issues = sanity_check_config()
    assert ok, issues


def test_run_full_sanity(monkeypatch):
    monkeypatch.setenv("MIN_TRADE_VNXAU", "0.4")
    monkeypatch.setenv("MAX_TRADE_VNXAU", "5")
    ok, evidence = run_full_sanity()
    assert ok, evidence


def test_sanity_rejects_inverted_trade_bounds(monkeypatch):
    monkeypatch.setenv("MIN_TRADE_VNXAU", "500")
    monkeypatch.setenv("MAX_TRADE_VNXAU", "200")
    ok, issues = sanity_check_config()
    assert not ok
    assert any("min_trade_vnxau" in issue for issue in issues)


def test_sanity_rejects_sub_platform_min_trade(monkeypatch):
    monkeypatch.setenv("MIN_TRADE_VNXAU", "0.1")
    monkeypatch.setenv("MAX_TRADE_VNXAU", "5")
    ok, issues = sanity_check_config()
    assert not ok
    assert any("platform min order" in issue for issue in issues)


def test_sanity_rejects_wrong_deposit_min(monkeypatch):
    monkeypatch.setenv("VNX_MIN_DEPOSIT_VNXAU_BASE", "0.01")
    ok, issues = sanity_check_config()
    assert not ok
    assert any("BASE VNXAU deposit min" in issue for issue in issues)
