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

## Known gaps

1. On-chain Uniswap V3 pool address for VNXAU/USDC on Base not pinned — quotes use fee-tier probe + Kyber fallback in simulator paths.
2. VNX cumulative deposit minimum for VNXAU on BASE/SOL not documented in public API; env default `0.01` — validate with a small live deposit before production sizing.
3. `verify-all` hits VNX `invalid_nonce` when sibling bots share the same API key concurrently.
4. Public Base/Sol RPC rate limits (429) — use paid RPC for matrix runs.

## Tests

152 unit tests (`DRY_RUN=true`). Route quotes work at zero on-chain VNXAU balance when platform/VNX quote APIs respond.
