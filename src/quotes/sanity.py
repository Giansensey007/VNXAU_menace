from __future__ import annotations

from src.config_loader import BotConfig


def check_vnxau_usd_rate(stable_usd: float, size_vnxau: float, cfg: BotConfig) -> tuple[bool, str]:
    if size_vnxau <= 0:
        return False, "zero size"
    rate = stable_usd / size_vnxau
    if rate < cfg.vnxau_usd_min or rate > cfg.vnxau_usd_max:
        return False, (
            f"VNXAU/USD rate {rate:.4f} outside [{cfg.vnxau_usd_min}, {cfg.vnxau_usd_max}]"
        )
    return True, f"VNXAU/USD {rate:.4f} ok"


def check_stable_peg(stable_in: float, stable_out: float, cfg: BotConfig) -> tuple[bool, str]:
    if stable_in <= 0 or stable_out <= 0:
        return False, "zero stable leg"
    ratio = stable_out / stable_in
    if ratio < cfg.peg_min or ratio > cfg.peg_max:
        return False, f"hub peg ratio {ratio:.4f} outside [{cfg.peg_min}, {cfg.peg_max}]"
    return True, f"hub peg {ratio:.4f} ok"


def sanity_check_simulation(sim) -> tuple[bool, list[str]]:
    """Cross-check a CycleSimulation object."""
    issues: list[str] = []
    if sim.error:
        issues.append(f"sim error: {sim.error}")
    if sim.size_vnxau <= 0:
        issues.append("invalid size")
    if not sim.sanity_ok and sim.sanity_notes:
        issues.extend(sim.sanity_notes)
    if sim.stable_in_usd < 0 or sim.stable_out_usd < 0:
        issues.append("negative stable amounts")
    return len(issues) == 0, issues
