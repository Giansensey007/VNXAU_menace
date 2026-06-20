from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from src.config_loader import BotConfig, ChainConfig, TokenConfig, load_bot_config
from src.quotes.api_gate import stagger_delay_ms
from src.scanner.routes import (
    BASE_SOL_DIRECTIONS,
    BASE_VNX_DIRECTIONS,
    ETH_VNX_DIRECTIONS,
    VNX_SOL_DIRECTIONS,
    route_for_direction,
)
from src.scanner.sizing import SizedSimulation, search_profitable_size
from src.scanner.simulator import CycleSimulation

logger = logging.getLogger(__name__)


@dataclass
class RouteGroupBest:
    group: str
    direction: str
    size_vnxau: float
    net_profit_usd: float
    simulation: CycleSimulation


@dataclass
class SelectionResult:
    """Outcome of parallel pre-execution route comparison."""

    opportunity: RouteGroupBest | None
    base_sol: RouteGroupBest | None
    vnx_sol: RouteGroupBest | None
    base_vnx: RouteGroupBest | None
    reason: str
    eth_vnx: RouteGroupBest | None = None


def _qualifies(sim: CycleSimulation, cfg: BotConfig) -> bool:
    return (
        sim.error is None
        and sim.sanity_ok
        and sim.net_profit_usd >= cfg.min_profit_usd
    )


async def _best_in_group(
    client: httpx.AsyncClient,
    chains: dict[str, ChainConfig],
    token: TokenConfig,
    cfg: BotConfig,
    group: str,
    directions: tuple[str, ...],
) -> RouteGroupBest | None:
    best: RouteGroupBest | None = None

    for direction in directions:
        sized = await search_profitable_size(client, chains, token, cfg, direction)
        if not sized:
            continue
        sim = sized.simulation
        profit = (
            sized.round_trip_profit_usd
            if cfg.close_loop_after_cycle and sized.round_trip_profit_usd is not None
            else sim.net_profit_usd
        )
        if cfg.close_loop_after_cycle:
            if sized.round_trip_profit_usd is None or profit < cfg.min_profit_usd:
                continue
            if sim.error or not sim.sanity_ok:
                continue
        elif not _qualifies(sim, cfg):
            continue
        if best is None or profit > best.net_profit_usd:
            best = RouteGroupBest(group, direction, sized.size_vnxau, profit, sim)

    return best


def _pick_base_sol_vs_vnx_sol(
    base_sol: RouteGroupBest | None,
    vnx_sol: RouteGroupBest | None,
    cfg: BotConfig,
) -> tuple[RouteGroupBest | None, str]:
    """Apply indirect-route premium when both base↔sol and SOL↔platform qualify."""
    premium = cfg.indirect_route_premium_usd
    cs_ok = base_sol is not None
    vs_ok = vnx_sol is not None

    if not cs_ok and not vs_ok:
        return None, "no profitable route in base↔sol or SOL↔platform groups"

    if cs_ok and not vs_ok:
        return base_sol, f"base↔sol only ({base_sol.direction} ${base_sol.net_profit_usd:.2f})"

    if vs_ok and not cs_ok:
        return vnx_sol, f"SOL↔platform only ({vnx_sol.direction} ${vnx_sol.net_profit_usd:.2f})"

    assert base_sol and vnx_sol
    delta = vnx_sol.net_profit_usd - base_sol.net_profit_usd
    if delta >= premium:
        return (
            vnx_sol,
            f"indirect +${delta:.2f} ≥ ${premium:.0f} premium → {vnx_sol.direction}",
        )
    return (
        base_sol,
        f"base↔sol preferred (indirect +${delta:.2f} < ${premium:.0f} premium)",
    )


def choose_execution(
    base_sol: RouteGroupBest | None,
    vnx_sol: RouteGroupBest | None,
    cfg: BotConfig,
    *,
    base_vnx: RouteGroupBest | None = None,
    eth_vnx: RouteGroupBest | None = None,
) -> SelectionResult:
    """
    Parallel scan done — pick what to execute.

    - base↔sol vs SOL↔platform: indirect only if ≥ indirect_route_premium_usd better
    - base↔VNX / eth↔VNX: compete on best net profit when enabled
    """
    cs_vs_winner, cs_vs_reason = _pick_base_sol_vs_vnx_sol(base_sol, vnx_sol, cfg)

    candidates: list[tuple[RouteGroupBest, str]] = []
    if cs_vs_winner:
        candidates.append((cs_vs_winner, cs_vs_reason))
    if base_vnx:
        candidates.append(
            (
                base_vnx,
                f"base↔VNX ({base_vnx.direction} ${base_vnx.net_profit_usd:.2f})",
            )
        )
    if eth_vnx:
        candidates.append(
            (
                eth_vnx,
                f"eth↔VNX ({eth_vnx.direction} ${eth_vnx.net_profit_usd:.2f})",
            )
        )

    if not candidates:
        return SelectionResult(
            None,
            base_sol,
            vnx_sol,
            base_vnx,
            "no profitable route in any enabled group",
            eth_vnx=eth_vnx,
        )

    winner, winner_reason = max(candidates, key=lambda item: item[0].net_profit_usd)
    if len(candidates) == 1:
        reason = winner_reason
    else:
        others = [c[0] for c in candidates if c[0] is not winner]
        best_other = max(others, key=lambda item: item.net_profit_usd)
        reason = (
            f"{winner.group} best (${winner.net_profit_usd:.2f} vs "
            f"${best_other.net_profit_usd:.2f}) — {winner_reason}"
        )

    return SelectionResult(
        winner,
        base_sol,
        vnx_sol,
        base_vnx,
        reason,
        eth_vnx=eth_vnx,
    )


async def select_execution_route(
    client: httpx.AsyncClient,
    chains: dict[str, ChainConfig],
    token: TokenConfig,
    cfg: BotConfig | None = None,
) -> SelectionResult:
    """Scan all enabled route groups with staggered API pacing, then apply selection rules."""
    cfg = cfg or load_bot_config()

    cs_dirs = BASE_SOL_DIRECTIONS
    vs_dirs = VNX_SOL_DIRECTIONS if cfg.enable_vnx_cctp_routes else ()
    bv_dirs = BASE_VNX_DIRECTIONS if cfg.enable_vnx_arb_routes else ()
    ev_dirs = ETH_VNX_DIRECTIONS if cfg.enable_vnx_arb_routes else ()

    base_sol = await _best_in_group(client, chains, token, cfg, "base_sol", cs_dirs)
    vnx_sol = None
    if vs_dirs:
        await stagger_delay_ms()
        vnx_sol = await _best_in_group(client, chains, token, cfg, "vnx_sol", vs_dirs)
    base_vnx = None
    if bv_dirs:
        await stagger_delay_ms()
        base_vnx = await _best_in_group(client, chains, token, cfg, "base_vnx", bv_dirs)
    eth_vnx = None
    if ev_dirs:
        await stagger_delay_ms()
        eth_vnx = await _best_in_group(client, chains, token, cfg, "eth_vnx", ev_dirs)

    result = choose_execution(
        base_sol,
        vnx_sol,
        cfg,
        base_vnx=base_vnx,
        eth_vnx=eth_vnx,
    )
    if result.opportunity:
        logger.info(
            "Route selected: %s @ %.0f VNXAU ($%.2f) — %s",
            result.opportunity.direction,
            result.opportunity.size_vnxau,
            result.opportunity.net_profit_usd,
            result.reason,
        )
    else:
        logger.info("No execution: %s", result.reason)
    return result
