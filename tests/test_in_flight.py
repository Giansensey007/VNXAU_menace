"""In-flight ledger reconcile and duplicate-withdraw guard tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.treasury.in_flight import (
    InFlightLedger,
    KIND_VNX_WITHDRAW,
    STATUS_PENDING,
    STATUS_SETTLED,
    parse_vnx_withdrawals,
)
from src.vnx.bridge import VnxBridge


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "in_flight.jsonl"


def test_reconcile_settles_vnx_withdraw_on_base_arrival(ledger_path: Path) -> None:
    ledger = InFlightLedger("VNXAU", ledger_path)
    ledger.log_vnx_withdraw(
        0.5,
        "BASE",
        "base-hot",
        "vnx_to_base",
        txids=["wd-1"],
        baseline_base_token=0.0,
        baseline_sol_token=0.0,
        baseline_platform_token=5.0,
    )
    active = ledger.reconcile(platform_token=4.0, base_token=0.0, sol_token=0.0)
    assert len(active) == 1
    assert active[0].status == STATUS_PENDING

    ledger.reconcile(platform_token=4.0, base_token=0.5, sol_token=0.0)
    records = ledger.read_all()
    settled = [r for r in records if r.kind == KIND_VNX_WITHDRAW]
    assert settled[0].status == STATUS_SETTLED


def test_parse_vnx_withdrawals_api_shape() -> None:
    api = {
        "withdrawals": [
            {
                "asset": "VNXAU",
                "quantity": 0.5,
                "blockchain": "BASE",
                "destination": "base-hot",
                "status": "pending",
                "txid": "abc123",
            },
            {
                "asset": "VNXAU",
                "quantity": 0.3,
                "blockchain": "SOL",
                "status": "completed",
            },
        ]
    }
    parsed = parse_vnx_withdrawals(api, "VNXAU")
    assert len(parsed) == 1
    assert parsed[0].quantity == 0.5
    assert parsed[0].blockchain == "BASE"


def test_reconcile_merges_api_pending_withdraw(ledger_path: Path) -> None:
    ledger = InFlightLedger("VNXAU", ledger_path)
    from src.treasury.in_flight import PendingVnxWithdraw

    api = [
        PendingVnxWithdraw(
            asset="VNXAU",
            quantity=0.5,
            blockchain="BASE",
            destination="base-hot",
            status="pending",
            txid="api-tx",
        )
    ]
    active = ledger.reconcile(platform_token=1.0, base_token=0.0, sol_token=0.0, api_withdrawals=api)
    assert len(active) == 1
    assert active[0].extra.get("source") == "vnx_api"


@pytest.mark.asyncio
async def test_bridge_skips_duplicate_withdraw_when_pending(ledger_path: Path, monkeypatch) -> None:
    ledger = InFlightLedger("VNXAU", ledger_path)
    ledger.log_vnx_withdraw(
        0.5,
        "BASE",
        "base-hot",
        "vnx_to_base",
        txids=["existing"],
        baseline_base_token=0.0,
        baseline_sol_token=0.0,
    )

    from src.config_loader import load_bot_config

    bridge = VnxBridge(load_bot_config())
    bridge._ledger = ledger

    withdraw_called = False

    class FakeVnx:
        async def account_balance(self):
            return {"balances": [{"asset": "VNXAU", "available_balance": 5}]}

        def vnxau_balance(self, bal):
            return 5.0

        async def withdraw(self, *args, **kwargs):
            nonlocal withdraw_called
            withdraw_called = True
            return {"txids": ["new"]}

    class Ctx:
        async def __aenter__(self):
            return FakeVnx()

        async def __aexit__(self, *a):
            pass

    monkeypatch.setattr("src.vnx.bridge.VnxClient", lambda: Ctx())
    monkeypatch.setattr("src.vnx.bridge.is_dry_run", lambda: False)

    result = await bridge.bridge_vnxau(
        direction="vnx_to_base",
        quantity=0.5,
        source_blockchain="BASE",
        dest_blockchain="BASE",
        dest_label="base-hot",
        deposit_tx_builder=lambda _a: None,
        withdraw_only=True,
    )
    assert result.success
    assert not withdraw_called
    assert "existing" in (result.withdraw_txids or [])


def test_reconcile_dedupes_api_by_txid(ledger_path: Path) -> None:
    ledger = InFlightLedger("VNXAU", ledger_path)
    ledger.log_vnx_withdraw(
        0.5,
        "BASE",
        "base-hot",
        "vnx_to_base",
        txids=["ABC123"],
        baseline_base_token=0.0,
    )
    from src.treasury.in_flight import PendingVnxWithdraw

    api = [
        PendingVnxWithdraw(
            asset="VNXAU",
            quantity=0.5,
            blockchain="BASE",
            destination="base-hot",
            status="pending",
            txid="abc123",
        )
    ]
    ledger.reconcile(platform_token=5.0, base_token=0.0, sol_token=0.0, api_withdrawals=api)
    pending = [r for r in ledger.read_all() if r.status == STATUS_PENDING and r.kind == KIND_VNX_WITHDRAW]
    assert len(pending) == 1


def test_reconcile_settles_api_pending_when_cleared(ledger_path: Path) -> None:
    ledger = InFlightLedger("VNXAU", ledger_path)
    from src.treasury.in_flight import PendingVnxWithdraw

    api = [
        PendingVnxWithdraw(
            asset="VNXAU",
            quantity=0.5,
            blockchain="BASE",
            destination="base-hot",
            status="pending",
            txid="gone-tx",
        )
    ]
    ledger.reconcile(platform_token=5.0, base_token=0.0, sol_token=0.0, api_withdrawals=api)
    assert len(ledger.active()) == 1

    ledger.reconcile(platform_token=5.0, base_token=0.5, sol_token=0.0, api_withdrawals=[])
    settled = [r for r in ledger.read_all() if r.kind == KIND_VNX_WITHDRAW]
    assert settled[0].status == STATUS_SETTLED


def test_log_cctp_burn_dedup(ledger_path: Path) -> None:
    ledger = InFlightLedger("VNXAU", ledger_path)
    r1 = ledger.log_cctp_burn("0xabc", "solana", quantity=5.0)
    r2 = ledger.log_cctp_burn("0xabc", "solana", quantity=5.0)
    assert r1.id == r2.id
    assert len(ledger.active()) == 1


def test_format_audit_block_shows_withdraw_summary(ledger_path: Path) -> None:
    ledger = InFlightLedger("VNXAU", ledger_path)
    ledger.log_vnx_withdraw(
        0.5, "BASE", "base-hot", "vnx_to_base", txids=["w1"], baseline_base_token=0.0
    )
    block = ledger.format_audit_block()
    assert "VNX withdraws: 1 pending" in block
    assert "BASE=0.50" in block
