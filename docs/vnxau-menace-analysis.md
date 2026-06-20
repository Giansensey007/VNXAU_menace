# VNXAU Menace — analysis

Platform-centric gold arb bot: **VNXAU/XAU lives on VNX**; Base and Solana hold USDC hub stables only (`platform_vnxau_only=true`).

## vs VCHF Menace

| Aspect | VCHF | VNXAU |
|--------|------|-------|
| Asset | VCHF | VNXAU (1 tokenized fine troy oz) |
| Primary L2 | Celo | **Base** |
| Hub stable | Celo USDT | **Base USDC** |
| Platform min order | 30 VCHF | **0.4 VNXAU** |
| Deploy sizing | 200–2000 VCHF | **0.5–5 VNXAU** |
| CELO routes | yes | **removed** |
| In-flight ledger | `src/treasury/in_flight.py` | **ported** (Base/SOL baselines) |
| Collision retry | `src/vnx/collision.py` | **present** (shared VNX account) |

## Route logic (mirror VCHF)

```
base_to_vnx     ← celo_to_vnx
vnx_to_base     ← vnx_to_celo
base_to_solana  ← celo_to_solana
solana_to_base  ← solana_to_celo
solana_to_vnx   ← unchanged (CCTP)
vnx_to_solana   ← unchanged (+ CCTP USDC return)
```

Ethereum remains a **wormhole/CCTP hub** (USDC/USDT legs), not a seventh directed arb pair.

## VNX API research

- **Assets:** VNXAU active on `BASE`, `SOL`, `ETH` (not CELO)
- **Pair:** `VNXAU/USDC` on platform quotes API
- **Min order:** 0.4 VNXAU (`VNX_MIN_ORDER` in `src/quotes/vnx.py`)
- **Withdraw env:** `VNX_BASE_BLOCKCHAIN=BASE`, `VNX_BASE_WITHDRAW_LABEL=<whitelisted label>`

## Bridge stack

- **Base ↔ Sol:** Wormhole Portal USDC (chain id 30)
- **Sol ↔ VNX:** Circle CCTP v2 (Sol USDC → ETH USDC → platform)
- **Base ↔ VNX:** direct VNXAU on-chain deposit + platform withdraw

## In-flight / collision (ported from VCHF)

- **`src/treasury/in_flight.py`** — persistent ledger for pending VNX withdraws/deposits and CCTP/Wormhole burns; reconciles against on-chain Base/SOL balances and bridge queues
- **`src/vnx/collision.py`** — classifies shared-account contention errors; wired in `client.py`, `bridge.py`, `trading.py`, `usdc_bridge.py`, `main.py`
- **Duplicate withdraw guard** — `VnxBridge` skips a second withdraw to the same chain while one is pending

## Deploy (Railway Docker)

Copy `.env.example` to Railway env. Critical RPC/Kyber vars:

- `RPC_BASE`, `RPC_ETHEREUM`, `RPC_SOLANA`
- `USE_KYBER_SWAP=true`, `KYBER_API_URL`, `KYBER_CLIENT_ID`, `BASE_SWAP_ROUTER`

Full steps: `DEPLOY.md`.

## Known gaps

1. On-chain Uniswap V3 pool address for VNXAU/USDC on Base not pinned — quotes use fee-tier probe + Kyber fallback in simulator paths.
2. VNX cumulative deposit minimum for VNXAU on BASE/SOL not documented in public API; env default `0.01` — validate with a small live deposit before production sizing.
3. `verify-all` hits VNX `invalid_nonce` when sibling bots share the same API key concurrently.
4. Public Base/Sol RPC rate limits (429) — use paid RPC for matrix runs.

## Tests

156+ unit tests (`DRY_RUN=true`), including `tests/test_in_flight.py` and `tests/test_vnx_collision.py`. Route quotes work at zero on-chain VNXAU balance when platform/VNX quote APIs respond.
