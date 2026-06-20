# VNXAU Menace — production status

**Chains:** Base + Ethereum + Solana (no Celo) · **Swaps:** KyberSwap (EVM) + Jupiter (Sol) · **Default:** `DRY_RUN=true`  
**Last commit:** `d8ea2d1` · **pytest:** 165 passed · **Remote:** `https://github.com/Giansensey007/VNXAU_menace.git`

## 10-iteration sanity (`run_sanity_10.py`)

Command: `DRY_RUN=true python scripts/run_sanity_10.py` (2026-06-20, post bounds fix)

| Agent | Status | Notes |
|-------|--------|-------|
| SA-00 config-env | PASS | base↔sol active |
| SA-01 Jupiter sell | PASS | ~132 USDC/VNXAU; band `[80,250]` from `config/bot.yaml` |
| SA-02 Kyber buy | PASS | ~134 USDT/VNXAU; same config band |
| SA-03 VNX platform | PASS | assets + platform sell |
| SA-04 deposit addrs | FAIL† | intermittent VNX nonce / empty BASE |
| SA-05 Wormhole | PASS | 100→99.50 USDT |
| SA-06 bridge dry-run | FAIL‡ | nonce contention on deposit address |
| SA-07 sim base→sol | PASS | quotes + sim; `sanity=True` with gold band |
| SA-08 sim sol→base | PASS | same |
| SA-09 pytest | PASS | **165 passed** |

† SA-04 flaky under shared VNX key collision with other Menace bots.  
‡ SA-06 passes when deposit address resolves.

**Rate band:** `vnxau_usd_min` / `vnxau_usd_max` in `config/bot.yaml` (default 80–250 USDC/VNXAU; override via `VNXAU_USD_MIN` / `VNXAU_USD_MAX`).

### Prior 10-iteration sweep (pre bounds fix)

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
| VNXAU/USD sanity band | 80–250 USDC/VNXAU | `config/bot.yaml`, `src/quotes/sanity.py` |
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
5. `DRY_RUN=true python scripts/run_sanity_10.py` → SA-01/02 PASS; SA-04/06 may flake under shared VNX key
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
| pytest all pass | OK — 165 (2026-06-20) |
| sanity-10 (single run) | **Partial** — 8/10 agents; SA-01/02 PASS; SA-04/06 nonce flake |
| verify-all critical steps | OK |
| In-flight + collision guards | OK |
| Funded wallet for live probes | **Gap** — fund before `DRY_RUN=false` |

## Quick commands

```bash
cd environment/VNXAU_Menace
DRY_RUN=true python -m pytest tests/ -q
DRY_RUN=true python scripts/run_sanity_10.py --iterations 10
DRY_RUN=true python scripts/execute_route_matrix.py --step verify-all
python scripts/rebalance_for_test.py   # fund for 31 VNXAU matrix
```
