# VNXAU Menace — production status

**Template:** VCHF Menace · **Bot token:** VNXAU (platform XAU) · **Default:** `DRY_RUN=true`

## Route matrix

| VCHF Menace | VNXAU Menace |
|-------------|--------------|
| Celo, Solana, Ethereum, VNX | **Base**, Solana, Ethereum (hub), VNX |
| `celo_to_*` | `base_to_*` |
| Celo USDT hub | **Base USDC** hub |
| 6 directed routes | 6 directed routes (same logic) |

### Six directed routes

| Direction | Group | Stable bridge |
|-----------|-------|---------------|
| `base_to_solana` | base↔sol | Wormhole USDC |
| `solana_to_base` | base↔sol | Wormhole USDC |
| `base_to_vnx` | base↔vnx | VNXAU deposit/withdraw on BASE |
| `vnx_to_base` | base↔vnx | VNXAU deposit/withdraw on BASE |
| `solana_to_vnx` | sol↔vnx | CCTP USDC + platform |
| `vnx_to_solana` | sol↔vnx | CCTP USDC return when origin=vnx |

## VNXAU on-chain addresses

| Chain | Address / mint |
|-------|----------------|
| **Base** | `0xac3fe22294beaed9d1fd752323a6d06d12ff3098` |
| **Solana** | `9TPL8droGJ7jThsq4momaoz6uhTcvX2SeMqipoPmNa8R` |
| **Ethereum** | `0x6d57b2e05f26c26b549231c866bdd39779e4a488` (hub / reference) |
| **VNX platform** | `VNXAU` |

## VNX platform (live API, 2026-06-20)

| Item | Value |
|------|-------|
| Trading pair | `VNXAU/USDC` (bid ~130.51, ask ~136.54) |
| Min platform order | **0.4 VNXAU** |
| VNX blockchain codes | `BASE`, `SOL`, `ETH` (no CELO for VNXAU) |
| Deposit min (env default) | **0.01 VNXAU** cumulative on BASE/SOL — confirm with VNX ops before live |

## Production guards

| Guard | Value | Enforced in |
|-------|-------|-------------|
| VNXAU deposit min (BASE/SOL) | 0.01 oz (env) | `src/vnx/deposits.py` |
| ETH USDC deposit min | 20 USDC cumulative | `src/vnx/deposits.py` |
| Platform buy/sell min | 0.4 VNXAU | `src/vnx/trading.py`, `src/quotes/vnx.py` |
| `platform_vnxau_only` | true | treasury + executor |
| VNX collision retry | 3 × 5s backoff | `src/vnx/collision.py` |
| Docker default | `DRY_RUN=true` | `Dockerfile`, `docker-compose.yml` |

## Validation (2026-06-20)

```bash
DRY_RUN=true python -m pytest tests/ -q          # 152 passed
DRY_RUN=true python scripts/execute_route_matrix.py --step audit
DRY_RUN=true python scripts/execute_route_matrix.py --step verify-all
```

**Route simulations @ 0.5 VNXAU:** all 6 directions quote (negative net at test size is expected).

**Gaps:** hot wallet under-funded for production thresholds; use paid Base/Sol RPC in production; `verify-all` may fail on shared VNX account `invalid_nonce` when GBP/VCHF bots are active.

## Go-live checklist

1. Copy `.env.example` → `.env` (same BASE/SOL hot wallets as GBP/VCHF)
2. Whitelist: `VNX_BASE_WITHDRAW_LABEL`, `VNX_SOL_WITHDRAW_LABEL`, `VNX_ETH_WITHDRAW_LABEL`
3. Fund per `config/production.yaml`
4. `DRY_RUN=true python -m pytest tests/ -q`
5. Route matrix audit + verify-all
6. Set `DRY_RUN=false` only after funding + whitelist confirmed
