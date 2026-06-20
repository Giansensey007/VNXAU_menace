from __future__ import annotations

import os

_DEFAULT_MIN_USDC_DEPOSIT: dict[str, float] = {"ETH": 20.0}


def min_deposit_vnxau(blockchain: str) -> float:
    """Minimum cumulative on-chain VNXAU deposit before VNX credits (BASE/ETH/SOL)."""
    bc = blockchain.strip().upper()
    if bc == "BASE":
        return float(os.getenv("VNX_MIN_DEPOSIT_VNXAU_BASE", "0.01"))
    if bc in ("ETH", "ETHEREUM"):
        return float(os.getenv("VNX_MIN_DEPOSIT_VNXAU_ETH", "0.01"))
    if bc == "SOL":
        return float(os.getenv("VNX_MIN_DEPOSIT_VNXAU_SOL", "0.01"))
    return 0.0


def check_deposit_amount(blockchain: str, quantity: float) -> str | None:
    """Return error message if VNXAU deposit is below chain minimum, else None."""
    min_qty = min_deposit_vnxau(blockchain)
    if min_qty <= 0:
        return None
    if quantity < min_qty:
        return (
            f"VNX {blockchain.upper()} deposit {quantity:.2f} VNXAU below minimum "
            f"{min_qty:.2f} VNXAU (cumulative on-chain transfers must reach minimum before credit)"
        )
    return None


def min_deposit_usdc(blockchain: str) -> float:
    """Minimum cumulative on-chain USDC deposit before VNX credits (ETH)."""
    bc = blockchain.strip().upper()
    if bc in ("ETH", "ETHEREUM"):
        return float(os.getenv("VNX_MIN_DEPOSIT_USDC_ETH", "20"))
    return 0.0


def check_usdc_deposit_amount(blockchain: str, quantity: float) -> str | None:
    """Return error message if USDC deposit is below chain minimum, else None."""
    min_qty = min_deposit_usdc(blockchain)
    if min_qty <= 0:
        return None
    if quantity < min_qty:
        return (
            f"VNX {blockchain.upper()} USDC deposit {quantity:.2f} below minimum "
            f"{min_qty:.2f} USDC (cumulative on-chain transfers must reach minimum before credit)"
        )
    return None
