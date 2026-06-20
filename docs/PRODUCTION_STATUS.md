# VNXAU Menace — production status

**Chains:** Base + Ethereum + Solana (no Celo) · **Swaps:** KyberSwap (EVM) + Jupiter (Sol) · **Default:** `DRY_RUN=true`

## Route matrix (`verify-all`)

Command: `DRY_RUN=true python scripts/execute_route_matrix.py --step verify-all`

| Step | Status | Notes |
|------|--------|-------|
| `cctp_claim` | PASS | Discover + claim (dry-run skips broadcast) |
| `wormhole_claim` | PASS | Queue empty |
| `wormhole_preflight` | PASS | Base→Sol, Base→ETH outbound |
| `route_simulations` | PASS | All 8 directions quote @ 31 VNXAU |
| `base_swaps` | PASS | DRY_RUN buy/sell probes (Kyber + Uniswap fallback) |
| `sol_swaps` | SKIP | Sol USDC below probe threshold |
| `platform_probe` | SKIP | Platform USDC below probe threshold |
| `eth_to_vnx` / `vnx_to_eth` | SKIP | ETH USDC below VNX min 20 |
| `cctp_sol_eth` / `cctp_eth_sol` | SKIP | Insufficient hub USDC |

### Route simulations @ 31 VNXAU (quotes only)

| Direction | Active | Net @ 31 VNXAU |
|-----------|--------|---------------|
| `base_to_solana` | yes | ~-$2.05 |
| `solana_to_base` | yes | ~-$2.05 |
| `base_to_vnx` | yes | ~-$1.70 |
| `vnx_to_base` | yes | ~-$0.51 |
| `solana_to_vnx` | yes | ~-$1.67 |
| `vnx_to_solana` | yes | ~-$1.63 |
| `ethereum_to_vnx` | yes | fee-dominated at test size |
| `vnx_to_ethereum` | yes | fee-dominated at test size |

Negative net at test size is expected (fees + spread); deploy sizing 200–2000 VNXAU.

### Production guards

| Guard | Value | Enforced in |
|-------|-------|-------------|
| VNXAU deposit min (BASE/SOL) | 5 VNXAU cumulative | `src/vnx/deposits.py` |
| ETH USDC deposit min | 20 USDC cumulative | `src/vnx/deposits.py` |
| Platform buy/sell min | 30 VNXAU | `src/vnx/trading.py`, VNX `VNXAU/USDC` |
| `platform_vnxau_only` | true | treasury + executor |
| In-flight ledger | `data/in_flight.jsonl` | bridge, CCTP, Wormhole, treasury |
| VNX collision retry | 3 × 5s backoff | `src/vnx/collision.py`, bridge + trading |
| KyberSwap | `USE_KYBER_SWAP=true` | `src/execution/evm_swap.py` |
| Solana RPC throttle | 800 ms | `.env.example` |
| Docker default | `DRY_RUN=true` | `Dockerfile`, `docker-compose.yml` |

### VNXAU contract addresses

| Chain | VNXAU |
|-------|-------|
| Base | `0xac3fe22294beaed9d1fd752323a6d06d12ff3098` |
| Ethereum | `0x6d57B2E05F26C26b549231c866bdd39779e4a488` |
| Solana | `9TPL8droGJ7jThsq4momaoz6uhTcvX2SeMqipoPmNa8R` |
| VNX Platform | `VNXAU` |

### Route test minimum (31 VNXAU matrix)

See `config/production.yaml` → `route_test` (platform_vnxau: 32, stables ~45 USDC).

### Funding gaps (live wallet snapshot)

Current hot wallet is **under-funded** for production and route-test thresholds. Top up before live:

- Platform VNXAU ≥ 200 (deploy) / 32 (route test)
- Platform USDC ≥ 250 / 45
- Base USDT ≥ 250 / 45
- Sol USDC ≥ 250 / 45
- ETH USDC ≥ 50 / 3 (VNX credit min 20 for hub legs)

## Target closed loop (Base → Sol homing)

**Platform VNXAU → BASE withdraw → sell VNXAU/USDC → Wormhole USDC to Sol → buy VNXAU (Jupiter) → deposit to platform**

Treasury `close_loop_always_return` + `consolidate_vnxau_to_platform()` sweep idle on-chain VNXAU back to platform after cycles.

## Go-live checklist

1. Copy `.env.example` → `.env` (same BASE/SOL keys as GBP; separate VNX keys optional)
2. Whitelist withdraw labels: `VNX_BASE_WITHDRAW_LABEL`, `VNX_SOL_WITHDRAW_LABEL`, `VNX_ETH_WITHDRAW_LABEL`
3. Fund per `config/production.yaml`
4. `DRY_RUN=true python -m pytest tests/ -q` → 165 passed
5. `DRY_RUN=true python scripts/run_validation_matrix.py --iterations 10` → 230/230 PASS (SA-00..SA-21)
6. `python scripts/execute_route_matrix.py --step verify-all`
7. Re-run until on-chain probes PASS
8. Set `DRY_RUN=false` only after critical verify-all checks PASS

## Railway readiness: 9/10

| Item | Status |
|------|--------|
| Dockerfile + `DRY_RUN=true` default | OK |
| docker-compose + `/data` volume | OK |
| DEPLOY.md | OK |
| `.env.example` (RPC_BASE, RPC_ETHEREUM, Kyber) | OK |
| pytest all pass | OK |
| validation matrix 10× (SA-00..SA-21) | OK — 230/230 (2026-06-20) |
| verify-all critical steps | OK |
| In-flight + collision guards | OK |
| Funded wallet for live probes | **Gap** — fund before `DRY_RUN=false` |

## Quick commands

```bash
cd environment/VNXAU_Menace
DRY_RUN=true python -m pytest tests/ -q
DRY_RUN=true python scripts/run_validation_matrix.py --iterations 10
DRY_RUN=true python scripts/execute_route_matrix.py --step verify-all
python scripts/rebalance_for_test.py   # fund for 31 VNXAU matrix
```
