# Deploy — VNXAU Menace

## Railway

1. Connect Railway to https://github.com/Giansensey007/VNXAU_menace
2. Root directory: repo root (Dockerfile at root)
3. Mount **persistent volume** at `/data` (SQLite at `/data/bot.db`, `in_flight.jsonl` / queues / `tx_log.jsonl` under `/data`)
4. Copy all vars from `.env.example` into Railway env
5. **Start with `DRY_RUN=true`** (Dockerfile and `is_dry_run()` default to true)
6. Preflight (Railway shell or one-off job):
   ```bash
   DRY_RUN=true python scripts/execute_route_matrix.py --step verify-all
   DRY_RUN=true python -m pytest tests/ -q
   ```
7. Fund to `config/production.yaml` targets — see `docs/PRODUCTION_STATUS.md`
8. **Infinite ERC20 approvals** (once per funded wallet):
   ```bash
   python scripts/approve_all.py
   # or set AUTO_APPROVE_ON_STARTUP=true in Railway env
   ```
9. Re-run `verify-all`; optional live probes:
   `DRY_RUN=false python scripts/test_probe_trades.py --execute` (5 VNXAU / hub USDC legs)
9. Set `DRY_RUN=false` and run deploy bot: `python -m src.main` (0.4–5 VNXAU sizing)

## Deploy vs test

| Entry | Purpose | Sizes |
|-------|---------|-------|
| `python -m src.main` | **Deploy** — poll, dynamic sizing, min profit | 0.4–5 VNXAU |
| `python scripts/test_probe_trades.py` | **Test** — tiny swaps, loss OK | 5 VNXAU / hub USDC |
| `python scripts/execute_route_matrix.py --step verify-all` | **Preflight** — claims, sims, funding audit | 5 VNXAU quotes |
| `python scripts/rebalance_for_test.py` | **Fund** — move stables for matrix | per `route_test` in production.yaml |
| `python scripts/convert_platform_xau.py` | **Fund** — CHF→USDC on VNX (min 30 USDC order) | optional |

## Required env vars

| Variable | Notes |
|----------|-------|
| `DRY_RUN` | `true` until funded + verify-all passes |
| `BASE_PRIVATE_KEY` | Base hot wallet |
| `SOLANA_SECRET_KEY` | Solana hot wallet (base58) |
| `SOLANA_PUBLIC_KEY` | Solana pubkey (withdraw whitelisting) |
| `VNX_PRIVATE_KEY_B64` | VNX platform PEM (base64) |
| `VNX_API_PUBLIC_KEY` | From VNX Platform → My Account |
| `VNX_BASE_WITHDRAW_LABEL` | Whitelisted Base withdraw label |
| `VNX_SOL_WITHDRAW_LABEL` | Whitelisted Sol withdraw label |
| `VNX_ETH_WITHDRAW_LABEL` | Whitelisted ETH USDC withdraw label |
| `ENABLE_VNX_ARB_ROUTES` | `true` — base↔vnx VNXAU (hub USDC path) |
| `ENABLE_VNX_CCTP_ROUTES` | `true` — SOL↔platform via Circle CCTP |
| `MIN_TRADE_VNXAU`, `MAX_TRADE_VNXAU` | Deploy sizing: `0.4` / `5` |
| `RPC_BASE`, `RPC_SOLANA`, `RPC_ETHEREUM` | Mainnet RPCs — use paid Base/Sol RPC in prod |
| `USE_KYBER_SWAP` | `true` — KyberSwap aggregator for Base + Ethereum EVM swaps |
| `KYBER_API_URL` | `https://aggregator-api.kyberswap.com` |
| `KYBER_CLIENT_ID` | Client id for Kyber rate limits (e.g. `vnxau-menace`) |
| `BASE_SWAP_ROUTER` | Kyber router on Base (default in `.env.example`) |
| `SOL_RPC_MIN_INTERVAL_MS` | 800+ on public RPC; lower on Helius/QuickNode |
| `DB_PATH` | Docker sets `/data/bot.db` — mount volume at `/data`; queues + logs live in parent dir |
| `VNX_COLLISION_RETRY_MAX` | Shared VNX account with GBP/VCHF — default `3` |
| `VNX_COLLISION_BACKOFF_SEC` | Backoff between collision retries — default `5` |

## VNX minimums (enforced in code)

| Guard | Value | Where |
|-------|-------|-------|
| BASE/SOL VNXAU deposit credit | 5 VNXAU cumulative | `VNX_MIN_DEPOSIT_VNXAU_*` |
| ETH USDC deposit credit | 20 USDC cumulative | `VNX_MIN_DEPOSIT_USDC_ETH` |
| ETH→VNX deposit asset | **USDC only** (never USDT on ETH) | `src/vnx/constants.py` → `VNX_ETH_DEPOSIT_ASSET` |
| Platform buy/sell order | 0.4 VNXAU | `src/vnx/trading.py` |

## VNX API keys

`VNX_API_PUBLIC_KEY` must match **VNX Platform → My Account**. If
`scripts/derive_vnx_public_key.py` gets HTTP 401, copy the public key from the UI.

1. Whitelist Base, Solana, and ETH hot wallet addresses on VNX
2. Confirm VNXAU deposit/withdraw for BASE and SOL; **USDC only** for ETH (not USDT)
3. Optional: top up CHF, then `python scripts/convert_platform_xau.py --execute`

## Local Docker

```bash
docker compose up --build
# DRY_RUN=true is set in docker-compose; override in .env only when going live
```
