# VNXAU Menace — deep analysis

Adapted from **GBP Menace** for **VNXAU** platform-centric arbitrage on **Base + Ethereum + Solana** (no Celo).  
Repo: https://github.com/Giansensey007/VNXAU_menace

---

## 1. Route map (8 directions)

| Direction | Buy leg | Sell leg | Bridge / hub |
|-----------|---------|----------|--------------|
| `base_to_solana` | Base USDC → VNXAU | Sol VNXAU → USDC | Wormhole USDC |
| `solana_to_base` | Sol USDC → VNXAU | Base VNXAU → USDC | Wormhole USDC |
| `base_to_vnx` | Base USDC → VNXAU | VNX sell VNXAU | deposit |
| `vnx_to_base` | VNX buy VNXAU | Base VNXAU → USDC | withdraw |
| `solana_to_vnx` | Sol USDC → VNXAU | VNX sell VNXAU | deposit + CCTP return path |
| `vnx_to_solana` | VNX buy VNXAU | Sol VNXAU → USDC | withdraw + CCTP return path |
| `ethereum_to_vnx` | ETH USDC → VNXAU (Kyber) | VNX sell VNXAU | deposit |
| `vnx_to_ethereum` | VNX buy VNXAU | ETH VNXAU → USDC (Kyber) | withdraw |

Route groups: `base_sol` (always on), `base_vnx` + **`eth_vnx`** (separate scanner group; `ENABLE_VNX_ARB_ROUTES`), `vnx_sol` (`ENABLE_VNX_CCTP_ROUTES`).

---

## 2. VNXAU-specific VNX minimums (API)

Fetched from VNX `get_trading_pairs()` (live API, 2026-06-20):

| Pair | Status | `min_order_size` | Notes |
|------|--------|------------------|-------|
| **VNXAU/USDC** | online | **30** | Used by bot (`VNXAU_MIN_ORDER`, route test @ 31) |
| VNXAU/ETH | online | 30 | — |
| VNXAU/BTC | online | 50 | — |
| VNXAU/CHF | online | 0.1 | Fiat rail |
| VGBP/USDC (GBP ref) | online | 40 | GBP uses 40; VNXAU is 30 |

On-chain deposit minimums:

| Chain | Asset | Min cumulative |
|-------|-------|----------------|
| BASE | VNXAU | 5 |
| SOL | VNXAU | 5 |
| ETH | USDC | 20 |

Code constants: `src/vnx/trading.py` → `VNXAU_MIN_ORDER = 30.0`; `src/quotes/vnx.py` → `VNX_MIN_ORDER["VNXAU"] = 30.0`.

---

## 3. Token addresses

| Chain | VNXAU mint / contract |
|-------|----------------------|
| Base | `0xac3fe22294beaed9d1fd752323a6d06d12ff3098` |
| Ethereum | `0x6d57B2E05F26C26b549231c866bdd39779e4a488` |
| Solana | `9TPL8droGJ7jThsq4momaoz6uhTcvX2SeMqipoPmNa8R` |
| VNX Platform | `VNXAU` (symbol) |

Base hub stable: USDC (`0x833589fCD6eDb6E08f4c7C32D4F71b54bda02913`).  
EVM swaps: **KyberSwap aggregator** first (`USE_KYBER_SWAP=true`), Uniswap V3 fallback.

---

## 4. Production route — Base → Sol closed loop

**Platform VNXAU → withdraw BASE → sell VNXAU→USDC → bridge to Solana → buy VNXAU with USDC → deposit VNXAU to platform.**

| # | Action | Implementation |
|---|--------|----------------|
| 1 | Withdraw VNXAU from VNX to Base hot wallet | `VnxBridge.bridge_vnxau(..., withdraw_only=True)` in `vnx_to_base` |
| 2 | Swap VNXAU → USDC on Base | KyberSwap / Uniswap via `BaseExecutor` |
| 3 | Bridge USDC Base → Solana | Wormhole Portal |
| 4 | Acquire VNXAU on Solana | Jupiter: USDC → VNXAU |
| 5 | Deposit VNXAU to VNX | `solana_to_vnx` — SPL transfer + VNX deposit poll |

Treasury: `platform_vnxau_only=true`, `consolidate_vnxau_to_platform()`, `close_loop_always_return=true`.

---

## 5. Test results

### Pytest

```
DRY_RUN=true python -m pytest tests/ -q
165 passed
```

### verify-all (with production `.env`, DRY_RUN=true)

| Branch | Result |
|--------|--------|
| cctp_claim | PASS |
| wormhole_claim | PASS |
| wormhole_preflight | PASS |
| route_simulations (8 dirs @ 31 VNXAU) | PASS |
| base_swaps | PASS |
| sol_swaps | SKIP (low Sol USDC) |
| platform_probe | SKIP (low platform USDC) |
| eth_to_vnx / vnx_to_eth | SKIP (below 20 USDC VNX min) |
| cctp_sol_eth / cctp_eth_sol | SKIP (insufficient hub USDC) |

Critical preflight branches (`cctp_claim`, `wormhole_claim`, `wormhole_preflight`, `route_simulations`) **all PASS**.

---

## 6. Production guards (ported from GBP/VCHF)

| Guard | Implementation |
|-------|----------------|
| Rate limits | `API_SYNC_*_MS`, `SOL_RPC_MIN_INTERVAL_MS`, `sync_throttle` |
| VNX collision | `VNX_COLLISION_RETRY_MAX`, backoff in bridge + trading |
| In-flight ledger | `src/treasury/in_flight.py` — duplicate withdraw guard, reconcile |
| Bridge queues | CCTP + Wormhole log burns to in-flight ledger |

---

## 7. Funding thresholds

### Production deploy (`config/production.yaml`)

| Location | Minimum |
|----------|---------|
| Platform VNXAU | 200 |
| Platform USDC | 250 |
| Base USDT | 250 |
| Sol USDC | 250 |
| ETH USDC | 50 |
| ETH USDT | 50 |
| ETH native | 0.015 |
| BASE native | 0.5 |
| SOL native | 0.05 |

### Route test (31 VNXAU matrix)

| Location | Minimum |
|----------|---------|
| Platform VNXAU | 32 |
| Platform USDC | 45 |
| Base USDT | 45 |
| Sol USDC | 45 |

---

## 8. Railway readiness: 9/10

- Dockerfile, docker-compose, DEPLOY.md: complete
- `.env.example`: `RPC_BASE`, `RPC_ETHEREUM`, `KYBER_*`, collision + in-flight vars
- **Gap:** hot wallet under-funded for live on-chain probes

---

## 9. Workspace wiring

| Item | Path |
|------|------|
| Local bot | `environment/VNXAU_Menace/` |
| Nested git | `environment/VNXAU_Menace/.git` |
| GitHub | https://github.com/Giansensey007/VNXAU_menace |
| Registry | `environment/REGISTRY.md` |
