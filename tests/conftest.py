from __future__ import annotations

import base64
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


@pytest.fixture(scope="session", autouse=True)
def test_env_keys():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    os.environ["VNX_PRIVATE_KEY_B64"] = base64.b64encode(pem).decode()
    os.environ["BASE_PRIVATE_KEY"] = "0x" + "22" * 32
    os.environ["DRY_RUN"] = "true"
    kp = __import__("solders.keypair", fromlist=["Keypair"]).Keypair()
    os.environ["SOLANA_SECRET_KEY"] = str(kp)
    os.environ.pop("VNX_API_PUBLIC_KEY", None)


@pytest.fixture(autouse=True)
def yaml_bot_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep config tests on bot.yaml defaults; local .env must not override."""
    monkeypatch.delenv("MIN_TRADE_VNXAU", raising=False)
    monkeypatch.delenv("MAX_TRADE_VNXAU", raising=False)
    for var in (
        "MIN_TRADE_VNXAU",
        "MAX_TRADE_VNXAU",
        "VNXAU_USD_MIN",
        "VNXAU_USD_MAX",
        "VNX_MIN_DEPOSIT_VNXAU_BASE",
        "VNX_MIN_DEPOSIT_VNXAU_SOL",
        "VNX_MIN_ORDER_VNXAU",
        "PLATFORM_VNXAU_ONLY",
        "JIT_WITHDRAW",
    ):
        os.environ.pop(var, None)
