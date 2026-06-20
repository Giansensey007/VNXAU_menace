# VNXAU Menace — production status

**Chains:** Base + Ethereum + Solana (no Celo) · **Swaps:** KyberSwap (EVM) + Jupiter (Sol) · **Default:** `DRY_RUN=true`  
**Routes:** 8 canonical (Base + ETH + Sol via VNX) · **Remote:** `https://github.com/Giansensey007/VNXAU_menace.git`

## Round 2 validation pass (2026-06-20)

| Check | Command | Result |
|-------|---------|--------|
| pytest | `DRY_RUN=true python -m pytest tests/ -q` | **215 passed** |
| validation matrix | `DRY_RUN=true python scripts/run_validation_matrix.py --iterations 10` | **230/230 PASS** (10 × 23 agents incl. SA-00) |
| live sanity-10 | `DRY_RUN=true python scripts/run_sanity_10.py --iterations 10` | **10/10 agents × 10 iterations** (100/100) |
| verify-all | `DRY_RUN=true python scripts/execute_route_matrix.py --step verify-all` | **critical PASS** (`cctp_claim`, `wormhole_claim`, `wormhole_preflight`, `route_simulations`, `platform_probe`) |

**Guards verified:** 8 routes (no Celo), KyberSwap Base+ETH, infinite approvals (`test_token_approvals.py`), VNXAU rate band 80–250, in-flight ledger, VNX collision retry.

**Fix in round 2:** Ethereum hub route simulations use VNX platform bid/ask fallback when on-chain Kyber quotes are outside the sanity band (thin ETH DEX pools).

| Iteration | validation matrix | sanity-10 |
|-----------|-------------------|-----------|
| I1–I10 | 23/23 PASS each | 10/10 agents PASS each |

Results: `validation/iteration-{1..10}/`, `validation/sanity-10/summary.json`

## Round 4 validation matrix (2026-06-20)

Post `b9968a4` 8-route audit (dropped eth↔sol executor; hardened wormhole preflight).

| Check | Command | Result |
|-------|---------|--------|
| pytest | `DRY_RUN=true python -m pytest tests/ -q` | **215 passed** |
| validation matrix | `DRY_RUN=true python scripts/run_validation_matrix.py --iterations 10` | **230/230 PASS** (10 × 23 agents incl. SA-00) |

| Iteration | SA-00 … SA-21 |
|-----------|---------------|
| I1–I10 | 23/23 PASS each |

All 8 directions verified in SA-05 (`routes-eight-directions`) and SA-15 (`scanner-all-routes`) every iteration.  
Results: `validation/iteration-{1..10}/`

## 10-iteration sanity (`run_sanity_10.py`)

Command: `DRY_RUN=true python scripts/run_sanity_10.py --iterations 10` (2026-06-20, round 2)

| Agent | Status | Notes |
|-------|--------|-------|
| SA-00 config-env | PASS | base↔sol active |
| SA-01 Jupiter sell | PASS | ~132 USDC/VNXAU; band `[80,250]` |
| SA-02 Kyber buy | PASS | ~134 USDT/VNXAU (Base KyberSwap) |
| SA-03 VNX platform | PASS | assets + platform sell |
| SA-04 deposit addrs | PASS | BASE + SOL deposit addresses |
| SA-05 Wormhole | PASS | 100→99.50 USDT |
| SA-06 bridge dry-run | PASS | dry-run orchestrator |
| SA-07 sim base→sol | PASS | quotes + sim; sanity band ok |
| SA-08 sim sol→base | PASS | same |
| SA-09 pytest | PASS | **215 passed** |

**Round 2:** 10/10 agents on all 10 iterations (`all_iterations_pass: true`).  
Results: `validation/sanity-10/summary.json`

### Prior single-run (pre round 2)

Command: `DRY_RUN=true python scripts/run_sanity_10.py --iterations 10` (2026-06-20)

| Iteration | Agents PASS |
|-----------|-------------|
| 1–10 | 8, 7, 7, 8, 7, 7, 7, 7, 7, 7 (last: **7/10**) |

SA-01/02 previously failed only due to stale VCHF-era bounds `[1,2]`; live quotes were healthy at ~$132/oz.

Results: `validation/sanity-10/summary.json`

## Route matrix (`verify-all`)

Command: `DRY_RUN=true python scripts/execute_route_matrix.py --step verify-all`

| Step | Status | Notes |
|------|--------|-------|
| `cctp_claim` | PASS | Discover + claim (dry-run skips broadcast) |
| `wormhole_claim` | PASS | Queue empty |
| `wormhole_preflight` | PASS | Base→Sol, Base→ETH outbound |
| `route_simulations` | PASS | All 8 directions quote @ 5 VNXAU (ETH uses VNX platform fallback) |
| `base_swaps` | SKIP | Base USDT below probe threshold |
| `sol_swaps` | SKIP | Sol USDC below probe threshold |
| `platform_probe` | PASS | DRY_RUN buy/sell @ 5 VNXAU |
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
| ETH→VNX asset | USDC only (never USDT on ETH) | `src/vnx/constants.py` → `VNX_ETH_DEPOSIT_ASSET` |
| Platform buy/sell min | 0.4 VNXAU | `src/vnx/trading.py`, `src/quotes/vnx.py` |
| `platform_vnxau_only` | true | treasury + executor |
| Persistent state | `data_dir()` → `/data` on Railway | in-flight, CCTP/Wormhole queues, tx log, DB |
| VNX collision retry | 3 × 5s backoff | `src/vnx/collision.py`, bridge + trading |
| VNXAU/USD sanity band | 80–250 USDC/VNXAU | `config/bot.yaml`, `src/quotes/sanity.py` |
| KyberSwap | `USE_KYBER_SWAP=true` on Base + **Ethereum mainnet** | `src/execution/evm_swap.py`, `src/quotes/kyber.py` |
| Solana RPC throttle | 800 ms | `.env.example` |
| Docker default | `DRY_RUN=true` | `Dockerfile`, `docker-compose.yml` |

### VNXAU contract addresses

| Chain | VNXAU |
|-------|-------|
| Base | `0xac3fe22294beaed9d1fd752323a6d06d12ff3098` |
| Ethereum | `0x6d57B2E05F26C26b549231c866bdd39779e4a488` |
| Solana | `9TPL8droGJ7jThsq4momaoz6uhTcvX2SeMqipoPmNa8R` |
| VNX Platform | `VNXAU` |

**KyberSwap ETH mainnet sample** (2026-06-20, `KYBER_EXCLUDED_SOURCES` limit-order filter on):

| Leg | Amount in | Amount out | Implied $/VNXAU | Route DEXs |
|-----|-----------|------------|-----------------|------------|
| Buy | 131 USDC | 0.774 VNXAU | ~169 | ekubo-v3, fermi, uniswapv3 |
| Sell | 1 VNXAU | 7.21 USDC | ~7 (rejected by sanity band) | uniswap-v4, uniswapv3 |

Sell-side thin-pool quotes below `vnxau_usd_min` (80) are dropped in `src/quotes/router.py`.

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
4. `DRY_RUN=true python -m pytest tests/ -q` → 215 passed
5. `DRY_RUN=true python scripts/run_sanity_10.py` → SA-01/02 PASS; SA-04/06 may flake under shared VNX key
6. `python scripts/execute_route_matrix.py --step verify-all`
7. Re-run until on-chain probes PASS
8. Set `DRY_RUN=false` only after critical verify-all checks PASS

## Railway readiness: 10/10

| Item | Status |
|------|--------|
| Dockerfile + `DRY_RUN=true` default | OK |
| docker-compose + `/data` volume | OK |
| DEPLOY.md | OK |
| `.env.example` (RPC_BASE, RPC_ETHEREUM, Kyber) | OK |
| pytest all pass | OK — 215 (round 2, 2026-06-20) |
| validation matrix 10× | OK — 230/230 (round 2) |
| sanity-10 (10 iterations) | OK — 10/10 agents × 10 iterations |
| verify-all critical steps | OK |
| In-flight + collision guards | OK |
| Funded wallet for live probes | **Gap** — fund before `DRY_RUN=false` |

## Quick commands

```bash
cd environment/VNXAU_Menace
DRY_RUN=true python -m pytest tests/ -q
DRY_RUN=true python scripts/run_sanity_10.py --iterations 10
DRY_RUN=true python scripts/run_validation_matrix.py --iterations 10
DRY_RUN=true python scripts/execute_route_matrix.py --step verify-all
python scripts/rebalance_for_test.py   # fund for 31 VNXAU matrix
```
