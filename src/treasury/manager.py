from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from src.config_loader import BotConfig, ChainConfig, TokenConfig, is_dry_run, token_decimals
from src.execution.base import BaseExecutor
from src.execution.executor import ArbExecutor, CycleRecord, CycleState
from src.execution.solana import SolanaExecutor
from src.quotes.types import from_human, to_human
from src.scanner.simulator import simulate_cctp_usdc_return_to_vnx, simulate_direction, simulate_round_trip
from src.treasury.in_flight import (
    InFlightLedger,
    PendingVnxWithdraw,
    format_treasury_balance_line,
    parse_vnx_withdrawals,
)
from src.treasury.loops import (
    DIRECTIONS_FROM_ORIGIN,
    closes_to_origin,
    inverse_direction,
    leg_end,
    return_closes_origin_with_cctp,
    return_leg_direction,
    use_cctp_usdc_return,
)
from src.vnx.bridge import VnxBridge
from src.vnx.client import VnxClient
from src.vnx.collision import vnx_error_message
from src.vnx.deposits import check_deposit_amount, min_deposit_vnxau
from src.vnx.trading import platform_buy_vnxau

logger = logging.getLogger(__name__)


@dataclass
class TreasurySnapshot:
    platform_vnxau: float = 0.0
    platform_usdc: float = 0.0
    base_vnxau: float = 0.0
    base_usdc: float = 0.0
    sol_vnxau: float = 0.0
    sol_usdc: float = 0.0
    pending_vnx_withdraws: list[PendingVnxWithdraw] = field(default_factory=list)
    in_flight_summary: str = ""


@dataclass
class PrepareResult:
    ready: bool
    direction: str
    size_vnxau: float
    notes: list[str] = field(default_factory=list)
    consolidated_vnxau: float = 0.0


@dataclass
class ClosedLoopResult:
    origin: str
    primary_direction: str
    primary: CycleRecord | None
    return_direction: str | None
    return_leg: CycleRecord | None
    closed: bool
    reason: str
    round_trip_profit_usd: float | None = None


class TreasuryManager:
    """
    Platform-centric VNXAU treasury: idle VNXAU lives on VNX only.
    Chains hold hub stables (Base USDT, Sol USDC) for buy legs.
    """

    def __init__(
        self,
        chains: dict[str, ChainConfig],
        token: TokenConfig,
        bot_cfg: BotConfig,
    ) -> None:
        self.chains = chains
        self.token = token
        self.cfg = bot_cfg
        self.dust = bot_cfg.vnxau_on_chain_dust
        self._ledger = InFlightLedger("VNXAU")

    def balance_line(self, snap: TreasurySnapshot) -> str:
        return format_treasury_balance_line(
            snap,
            "vnxau",
            pending_vnx_withdraws=snap.pending_vnx_withdraws,
            in_flight_summary=snap.in_flight_summary,
        )

    def _platform_vnxau_only(self) -> bool:
        return self.cfg.platform_vnxau_only and self.cfg.treasury_vnxau_home == "platform"

    async def assert_vnxau_home_policy(self) -> tuple[bool, str]:
        """Verify on-chain VNXAU is at or below dust threshold."""
        if not self._platform_vnxau_only():
            return True, "policy off"
        snap = await self.snapshot()
        over = []
        pending_base = self._ledger.total_pending_to_blockchain("BASE")
        pending_sol = self._ledger.total_pending_to_blockchain("SOL")
        base_adj = max(0.0, snap.base_vnxau - pending_base)
        sol_adj = max(0.0, snap.sol_vnxau - pending_sol)
        if base_adj > self.dust:
            over.append(f"base={snap.base_vnxau:.2f}")
        if sol_adj > self.dust:
            over.append(f"sol={snap.sol_vnxau:.2f}")
        if over:
            pending_note = ""
            if pending_base or pending_sol:
                pending_note = f" (pending withdraw base={pending_base:.2f} sol={pending_sol:.2f})"
            return False, f"on-chain VNXAU above dust ({self.dust}): {', '.join(over)}{pending_note}"
        return True, "ok"

    async def snapshot(self) -> TreasurySnapshot:
        snap = TreasurySnapshot()
        api_withdrawals: list[PendingVnxWithdraw] | None = None
        async with VnxClient() as vnx:
            bal = await vnx.account_balance_resilient()
            err = vnx_error_message(bal)
            if err:
                logger.warning("VNX snapshot balance unavailable: %s", err)
            else:
                snap.platform_vnxau = vnx.vnxau_balance(bal)
                snap.platform_usdc = vnx.usdc_balance(bal)
            wd_resp = await vnx.query_withdrawals()
            if wd_resp is not None:
                if api_withdrawals is None:
                    api_withdrawals = []
                api_withdrawals.extend(parse_vnx_withdrawals(wd_resp, "VNXAU"))
            tr_resp = await vnx.query_transfers()
            if tr_resp is not None:
                if api_withdrawals is None:
                    api_withdrawals = []
                api_withdrawals.extend(parse_vnx_withdrawals(tr_resp, "VNXAU"))

        base = BaseExecutor(self.chains["base"])
        dec = token_decimals(self.token, "base")
        snap.base_vnxau = float(to_human(base.balance_erc20(self.token.chains["base"]), dec))
        snap.base_usdc = float(
            to_human(base.balance_erc20(self.chains["base"].hub_token), self.chains["base"].hub_decimals)
        )

        sol = SolanaExecutor(self.chains["solana"])
        from spl.token.instructions import get_associated_token_address
        from solders.pubkey import Pubkey

        vnxau_ata = get_associated_token_address(
            sol.keypair.pubkey(), Pubkey.from_string(self.token.chains["solana"])
        )
        usdc_ata = get_associated_token_address(
            sol.keypair.pubkey(), Pubkey.from_string(self.chains["solana"].hub_token)
        )
        try:
            snap.sol_vnxau = sol.token_balance_ui(vnxau_ata)
        except Exception:
            snap.sol_vnxau = 0.0
        try:
            snap.sol_usdc = sol.token_balance_ui(usdc_ata)
        except Exception:
            snap.sol_usdc = 0.0

        self._ledger.reconcile(
            platform_token=snap.platform_vnxau,
            base_token=snap.base_vnxau,
            sol_token=snap.sol_vnxau,
            api_withdrawals=api_withdrawals,
        )
        snap.pending_vnx_withdraws = self._ledger.pending_vnx_withdraws_view()
        snap.in_flight_summary = self._ledger.format_summary()
        return snap

    async def consolidate_vnxau_to_platform(self) -> float:
        """Deposit on-chain VNXAU dust/excess to VNX (platform home). Returns total moved."""
        snap = await self.snapshot()
        moved = 0.0
        bridge = VnxBridge(self.cfg)

        bc = os.getenv("VNX_BASE_BLOCKCHAIN", "BASE")
        base_min = min_deposit_vnxau(bc)
        if snap.base_vnxau > self.dust and snap.base_vnxau < base_min:
            logger.warning(
                "Stuck Base VNXAU %.4f: above dust (%.2f) but below VNX min deposit (%.2f)",
                snap.base_vnxau,
                self.dust,
                base_min,
            )
        if snap.base_vnxau >= base_min:
            qty = snap.base_vnxau
            dep_err = check_deposit_amount(bc, qty)
            if dep_err:
                logger.warning("Skip Base VNXAU consolidate (%.4f): %s", qty, dep_err)
            else:
                logger.info("Treasury: deposit %.4f VNXAU from Base → platform", qty)
                base = BaseExecutor(self.chains["base"])
                dec = token_decimals(self.token, "base")

                async def base_dep(addr: str) -> str | None:
                    return base.transfer_erc20(
                        self.token.chains["base"], addr, from_human(qty, dec)
                    )

                br = await bridge.bridge_vnxau(
                    direction="treasury_base_to_platform",
                    quantity=qty,
                    source_blockchain=bc,
                    dest_blockchain=bc,
                    dest_label="platform",
                    deposit_tx_builder=base_dep,
                    deposit_only=True,
                )
                if br.success:
                    moved += qty
                else:
                    logger.warning("Base VNXAU consolidate failed: %s", br.error)

        snap = await self.snapshot()
        sol_bc = os.getenv("VNX_SOL_BLOCKCHAIN", "SOL")
        sol_min = min_deposit_vnxau(sol_bc)
        if snap.sol_vnxau > self.dust and snap.sol_vnxau < sol_min:
            logger.warning(
                "Stuck Sol VNXAU %.4f: above dust (%.2f) but below VNX min deposit (%.2f)",
                snap.sol_vnxau,
                self.dust,
                sol_min,
            )
        if snap.sol_vnxau >= sol_min:
            qty = snap.sol_vnxau
            dep_err = check_deposit_amount(sol_bc, qty)
            if dep_err:
                logger.warning("Skip Sol VNXAU consolidate (%.4f): %s", qty, dep_err)
            else:
                logger.info("Treasury: deposit %.4f VNXAU from Sol → platform", qty)
                sol = SolanaExecutor(self.chains["solana"])
                dec = token_decimals(self.token, "solana")

                async def sol_dep(addr: str) -> str | None:
                    return sol.transfer_spl(
                        self.token.chains["solana"], addr, from_human(qty, dec), dec
                    )

                br = await bridge.bridge_vnxau(
                    direction="treasury_sol_to_platform",
                    quantity=qty,
                    source_blockchain=sol_bc,
                    dest_blockchain=sol_bc,
                    dest_label="platform",
                    deposit_tx_builder=sol_dep,
                    deposit_only=True,
                )
                if br.success:
                    moved += qty
                else:
                    logger.warning("Sol VNXAU consolidate failed: %s", br.error)

        if moved > 0:
            logger.info("Treasury consolidated %.4f VNXAU to platform", moved)
        return moved

    async def prepare_for_direction(self, direction: str, size_vnxau: float) -> PrepareResult:
        """JIT prep: sweep VNXAU home, verify stables / platform inventory for the leg."""
        notes: list[str] = []
        consolidated = 0.0
        if self.cfg.jit_withdraw or self._platform_vnxau_only():
            consolidated = await self.consolidate_vnxau_to_platform()
            if consolidated:
                notes.append(f"consolidated {consolidated:.2f} VNXAU to platform")

        snap = await self.snapshot()

        if self._platform_vnxau_only():
            ok, msg = await self.assert_vnxau_home_policy()
            if not ok:
                notes.append(msg)

        if direction in ("base_to_solana", "solana_to_base"):
            if not await self.ensure_platform_vnxau_for_bridge(size_vnxau):
                notes.append(f"platform VNXAU short for bridge ({snap.platform_vnxau:.1f} < {size_vnxau:.0f})")
                return PrepareResult(False, direction, size_vnxau, notes, consolidated)

        if direction.startswith("vnx_to_"):
            from src.vnx.bridge import VNXAU_WITHDRAW_FEE_BUFFER
            from src.vnx.trading import VNXAU_MIN_ORDER, _round_down, VNXAU_USDC_QTY_DECIMALS

            withdrawable = max(0.0, snap.platform_vnxau - VNXAU_WITHDRAW_FEE_BUFFER)
            if snap.platform_vnxau >= size_vnxau * 0.95:
                pass
            elif withdrawable >= 1.0:
                # Withdraw has no 30 VNXAU floor — only platform buy/sell does.
                size_vnxau = _round_down(withdrawable, VNXAU_USDC_QTY_DECIMALS)
                notes.append(f"withdraw-only size {size_vnxau:.2f} VNXAU (platform balance minus fee buffer)")
            else:
                need_usdc = VNXAU_MIN_ORDER * 1.35
                if snap.platform_usdc < need_usdc * 0.95:
                    notes.append(
                        f"platform short: need withdrawable VNXAU≥{size_vnxau:.0f} or USDC≥{need_usdc:.0f} "
                        f"to buy {VNXAU_MIN_ORDER:.0f} VNXAU (platform order min; have "
                        f"{snap.platform_vnxau:.1f} VNXAU, {snap.platform_usdc:.1f} USDC)"
                    )
                    return PrepareResult(False, direction, size_vnxau, notes, consolidated)
                size_vnxau = VNXAU_MIN_ORDER
                notes.append(f"will buy {size_vnxau:.0f} VNXAU on platform (order minimum)")

        if direction in ("base_to_vnx", "base_to_solana"):
            need_usdt = size_vnxau * 1.35
            if snap.base_usdc < need_usdt * 0.9:
                notes.append(
                    f"Base needs ≥{need_usdt:.0f} USDT (have {snap.base_usdc:.1f}) — "
                    "fund via vnx_to_base or wormhole"
                )
                return PrepareResult(False, direction, size_vnxau, notes, consolidated)

        if direction in ("solana_to_vnx", "solana_to_base"):
            need_usdc = size_vnxau * 1.35
            if snap.sol_usdc < need_usdc * 0.9:
                notes.append(
                    f"Sol needs ≥{need_usdc:.0f} USDC (have {snap.sol_usdc:.1f}) — fund via vnx_to_solana"
                )
                return PrepareResult(False, direction, size_vnxau, notes, consolidated)

        notes.append("ready")
        return PrepareResult(True, direction, size_vnxau, notes, consolidated)

    async def ensure_platform_vnxau_for_bridge(self, size_vnxau: float) -> bool:
        """Buy VNXAU on platform if needed for cross-chain bridge inventory."""
        snap = await self.snapshot()
        if snap.platform_vnxau >= size_vnxau * 0.95:
            return True
        need = size_vnxau - snap.platform_vnxau
        if snap.platform_usdc < need * 1.2:
            logger.warning(
                "Cannot top-up platform VNXAU (need %.1f, USDC %.1f)", need, snap.platform_usdc
            )
            return False
        buy = await platform_buy_vnxau(self.cfg, need, max_usdc=snap.platform_usdc * 0.995)
        return buy.success

    async def run_closed_loop(
        self,
        client,
        executor: ArbExecutor,
        *,
        origin: str,
        direction: str,
        size_vnxau: float,
        force_return: bool | None = None,
        force_execute: bool = False,
    ) -> ClosedLoopResult:
        """
        Execute `direction` then return capital to `origin` hub stable.

        When close_loop_always_return: always run inverse leg (capital homing).
        Otherwise: return only if inverse sim profitable or round-trip ≥ min_net.
        """
        force = force_return if force_return is not None else _env_bool("CLOSE_LOOP_FORCE", False)
        always_return = force or self.cfg.close_loop_always_return
        min_round = self.cfg.close_loop_min_net_usd

        prep = await self.prepare_for_direction(direction, size_vnxau)
        if not prep.ready:
            return ClosedLoopResult(
                origin, direction, None, None, None, False, "; ".join(prep.notes)
            )

        exec_size = prep.size_vnxau
        primary = await executor.run_cycle(
            client, direction, exec_size, force_execute=force_execute or always_return
        )
        await self.consolidate_vnxau_to_platform()

        if primary.state != CycleState.DONE:
            return ClosedLoopResult(
                origin, direction, primary, None, None, False, primary.error or "primary failed"
            )

        if closes_to_origin(origin, direction):
            return ClosedLoopResult(
                origin,
                direction,
                primary,
                None,
                None,
                True,
                "primary already ends on origin",
                primary.simulation.net_profit_usd if primary.simulation else None,
            )

        inv = return_leg_direction(origin, direction, enable_cctp=self.cfg.enable_vnx_cctp_routes)
        if not inv:
            end = leg_end(direction)
            return ClosedLoopResult(
                origin,
                direction,
                primary,
                None,
                None,
                False,
                f"no inverse leg; capital on {end}",
            )

        if not return_closes_origin_with_cctp(
            origin, direction, enable_cctp=self.cfg.enable_vnx_cctp_routes
        ):
            return ClosedLoopResult(
                origin,
                direction,
                primary,
                inv,
                None,
                False,
                f"return {inv} does not close to {origin}",
            )

        if use_cctp_usdc_return(origin, direction, enable_cctp=self.cfg.enable_vnx_cctp_routes):
            usdc_on_sol = primary.simulation.stable_out_usd if primary.simulation else 0.0
            inv_sim = await simulate_cctp_usdc_return_to_vnx(
                client, self.chains, self.token, self.cfg, usdc_on_sol, exec_size
            )
        else:
            inv_sim = await simulate_direction(
                client, self.chains, self.token, self.cfg, inv, exec_size
            )
        primary_profit = primary.simulation.net_profit_usd if primary.simulation else 0.0
        round_profit = primary_profit + inv_sim.net_profit_usd
        return_profitable = inv_sim.profitable and inv_sim.net_profit_usd >= self.cfg.min_profit_usd
        round_ok = round_profit >= min_round and (return_profitable or round_profit >= self.cfg.min_profit_usd)

        if not always_return and not return_profitable and not round_ok:
            await self.consolidate_vnxau_to_platform()
            return ClosedLoopResult(
                origin,
                direction,
                primary,
                inv,
                None,
                False,
                f"return leg uneconomic (inv profit ${inv_sim.net_profit_usd:.2f}, "
                f"round ${round_profit:.2f}) — capital left at {leg_end(direction)}",
                round_profit,
            )

        if not return_profitable and always_return:
            logger.warning(
                "Running return leg %s despite sim loss $%.2f (close_loop_always_return)",
                inv,
                inv_sim.net_profit_usd,
            )

        prep_ret = await self.prepare_for_direction(inv, exec_size)
        if (
            not prep_ret.ready
            and not always_return
            and not use_cctp_usdc_return(origin, direction, enable_cctp=self.cfg.enable_vnx_cctp_routes)
        ):
            return ClosedLoopResult(
                origin,
                direction,
                primary,
                inv,
                None,
                False,
                f"return prep failed: {prep_ret.notes}",
                round_profit,
            )

        return_size = exec_size
        if primary.simulation and primary.simulation.token_mid > 0:
            return_size = primary.simulation.token_mid

        if use_cctp_usdc_return(origin, direction, enable_cctp=self.cfg.enable_vnx_cctp_routes):
            usdc_amt = primary.simulation.stable_out_usd if primary.simulation else 0.0
            return_record = await executor.run_cctp_usdc_return_to_vnx(
                client,
                usdc_amt,
                return_size,
                force_execute=force_execute or always_return,
            )
        else:
            return_record = await executor.run_cycle(
                client, inv, return_size, force_execute=force_execute or always_return
            )
        await self.consolidate_vnxau_to_platform()

        closed = return_record.state == CycleState.DONE
        return ClosedLoopResult(
            origin,
            direction,
            primary,
            inv,
            return_record,
            closed,
            "closed loop" if closed else (return_record.error or "return failed"),
            round_profit if closed else round_profit,
        )

    async def best_closed_loop_from_origin(
        self, client, executor: ArbExecutor, origin: str, size_vnxau: float
    ) -> ClosedLoopResult | None:
        """Pick best profitable direction from origin and run as closed loop."""
        candidates = DIRECTIONS_FROM_ORIGIN.get(origin, ())
        best_dir: str | None = None
        best_profit = float("-inf")
        for d in candidates:
            rt = await simulate_round_trip(
                client, self.chains, self.token, self.cfg, d, size_vnxau, origin=origin
            )
            if not rt.profitable:
                continue
            if rt.round_trip_profit_usd > best_profit:
                best_profit = rt.round_trip_profit_usd
                best_dir = d
        if not best_dir:
            return None
        return await self.run_closed_loop(
            client, executor, origin=origin, direction=best_dir, size_vnxau=size_vnxau
        )


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, "true" if default else "false").lower()
    return raw in ("1", "true", "yes")
