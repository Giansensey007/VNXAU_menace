# VNXAU Menace

Cross-chain VNXAU arbitrage on **Base**, **Solana**, and **VNX Platform** (no Celo).

```bash
cp .env.example .env   # same BASE/SOL wallets as GBP/VCHF
DRY_RUN=true python -m pytest tests/ -q
DRY_RUN=true python scripts/execute_route_matrix.py --step audit
```

Repo: https://github.com/Giansensey007/VNXAU_menace
