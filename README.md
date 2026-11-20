# India Day Trader — ₹500 → ₹1,000 NSE Rotation Workspace

Automated cloud morning briefs (GitHub Actions → WhatsApp / ntfy / Telegram / Gmail) + local `india-day-trader-skill` workspace for NSE & BSE equities in INR (`IST 09:15–15:30`).

> **Educational & paper-first tooling only — not financial advice.** Nothing in this repository places live broker orders automatically.

## What's Inside
- [`trader/rotation_watchlist.txt`](trader/rotation_watchlist.txt) — 10 liquid multi-sector NSE stocks (`₹35–₹370`, 1x affordable inside `₹500`)
- [`trader/config.json`](trader/config.json) — Risk rules (`₹500` budget, `₹10` max loss/trade, `₹15` daily loss limit, max 2 trades/day, `15:10 IST` flat-by, `MIS` intraday, `"paper": true`)
- [`trader/challenge_ledger.md`](trader/challenge_ledger.md) — Daily trade & P&L scorecard
- [`scripts/morning_brief.py`](scripts/morning_brief.py) — Pure-stdlib NSE holiday-aware scanner & WhatsApp/ntfy/Telegram/Gmail notifier
- [`.github/workflows/nse-morning-alert.yml`](.github/workflows/nse-morning-alert.yml) — Scheduled Mon–Fri IST alerts (`09:00`, `~09:45`, `15:05 IST`)
- [`backtest_pc_pullback.py`](backtest_pc_pullback.py) — 60-day NSE 5-minute backtester including real Indian MIS charges
- [`GITHUB_SETUP.md`](GITHUB_SETUP.md) — Step-by-step guide to connect WhatsApp / phone push / email alerts
