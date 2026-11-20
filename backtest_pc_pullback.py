#!/usr/bin/env python3
"""Backtest the 20-period Price Channel (PC 20) Midline Pullback strategy on 60 days of NSE 5m data.

Includes real Indian MIS intraday charges (brokerage, STT, NSE txn, SEBI, stamp duty, GST)
and zero-lookahead bar-by-bar execution with 15:15 IST square-off.
"""

from __future__ import annotations

import os
import sys
import time
from collections import defaultdict

LIB_DIR = r"C:\Users\VEERAJ\.gemini\config\plugins\india-day-trader-skill\lib"
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

import india_market as im

SYMBOLS = [
    "ITC.NS",
    "RELIANCE.NS",
    "ICICIBANK.NS",
    "HDFCBANK.NS",
    "SBIN.NS",
    "INFY.NS",
    "TCS.NS",
    "LT.NS",
    "AXISBANK.NS",
    "M&M.NS",
    "SUNPHARMA.NS",
    "BHARTIARTL.NS",
    "HINDZINC.NS",
    "HINDCOPPER.NS",
    "VEDL.NS",
]

POSITION_INR = 25000.0  # 50% of Rs 50,000 paper capital per trade


def run_symbol_variant(bars_by_day: dict[str, list[dict]], stop_buf_pct: float, target_rr: float, min_channel_pct: float = 0.0, slippage_pct: float = 0.0) -> list[dict]:
    """Run zero-lookahead PC(20) midline pullback simulation across all sessions."""
    trades = []
    # Flatten chronologically so PC(20) carries across session boundaries just like TradingView
    all_bars = []
    for d in sorted(bars_by_day.keys()):
        all_bars.extend(bars_by_day[d])

    n = len(all_bars)
    i = 20
    while i < n:
        b = all_bars[i]
        t = b["time"]
        if t < "09:30" or t > "14:30":
            i += 1
            continue

        window = all_bars[i - 20 : i]  # strictly previous 20 completed bars
        upper = max(x["high"] for x in window)
        lower = min(x["low"] for x in window)
        mid = (upper + lower) / 2.0
        ch_pct = (upper - lower) / mid * 100.0 if mid > 0 else 0.0
        if ch_pct < min_channel_pct:
            i += 1
            continue

        # Prior upward push: any of the last 6 bars reached upper 25% of channel
        upper_zone = mid + 0.5 * (upper - mid)
        had_push = any(x["high"] >= upper_zone for x in all_bars[i - 6 : i])
        if not had_push:
            i += 1
            continue

        # Pullback & bounce on current completed bar i: touched near midline and closed above midline (below upper)
        touched_mid = b["low"] <= mid * 1.0015 and b["low"] >= lower
        bounced = b["close"] > mid and b["close"] < upper * 0.999
        if not (touched_mid and bounced):
            i += 1
            continue

        # Enter on close of bar i (with optional slippage)
        entry = b["close"] * (1.0 + slippage_pct / 100.0)
        stop = mid * (1.0 - stop_buf_pct / 100.0)
        if stop >= entry:
            i += 1
            continue
        risk = entry - stop
        target = entry + target_rr * risk
        qty = int(POSITION_INR // entry)
        if qty <= 0:
            i += 1
            continue

        # Walk forward bar-by-bar within the same session until stop, target, or 15:15 IST square-off
        day = b["date"]
        exit_px = entry
        outcome = "flat"
        j = i + 1
        while j < n and all_bars[j]["date"] == day:
            nb = all_bars[j]
            if nb["low"] <= stop:
                exit_px = stop * (1.0 - slippage_pct / 100.0)
                outcome = "stop"
                break
            if nb["high"] >= target:
                exit_px = target
                outcome = "target"
                break
            if nb["time"] >= "15:15":
                exit_px = nb["close"]
                outcome = "flat"
                break
            j += 1
        else:
            if j - 1 > i and all_bars[j - 1]["date"] == day:
                exit_px = all_bars[j - 1]["close"]

        buy_val = qty * entry
        sell_val = qty * exit_px
        gross = sell_val - buy_val
        ch = im.estimate_intraday_charges(buy_val, sell_val, brokerage_per_order=20.0, exchange="NSE")
        net = gross - ch["total"]
        r_mult = (exit_px - entry) / risk

        trades.append({
            "date": day,
            "entry_time": t,
            "entry": round(entry, 2),
            "stop": round(stop, 2),
            "target": round(target, 2),
            "exit": round(exit_px, 2),
            "qty": qty,
            "outcome": outcome,
            "r_gross": round(r_mult, 3),
            "gross_inr": round(gross, 2),
            "charges_inr": ch["total"],
            "net_inr": round(net, 2),
        })
        # Skip past exit bar (no overlapping trades in same stock)
        i = max(j + 1, i + 1)
    return trades


def summarize(label: str, trades: list[dict]) -> dict:
    if not trades:
        return {"label": label, "n": 0}
    n = len(trades)
    wins = sum(1 for t in trades if t["net_inr"] > 0)
    targets = sum(1 for t in trades if t["outcome"] == "target")
    stops = sum(1 for t in trades if t["outcome"] == "stop")
    flats = sum(1 for t in trades if t["outcome"] == "flat")
    gross = sum(t["gross_inr"] for t in trades)
    charges = sum(t["charges_inr"] for t in trades)
    net = sum(t["net_inr"] for t in trades)
    avg_r = sum(t["r_gross"] for t in trades) / n
    # Max drawdown on cumulative net P&L
    peak = 0.0
    cum = 0.0
    max_dd = 0.0
    for t in trades:
        cum += t["net_inr"]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd
    return {
        "label": label,
        "n": n,
        "win_pct": round(wins / n * 100.0, 1),
        "target_pct": round(targets / n * 100.0, 1),
        "stop_pct": round(stops / n * 100.0, 1),
        "flat_pct": round(flats / n * 100.0, 1),
        "avg_r": round(avg_r, 3),
        "gross_inr": round(gross, 2),
        "charges_inr": round(charges, 2),
        "net_inr": round(net, 2),
        "max_dd_inr": round(max_dd, 2),
    }


def main() -> int:
    print("Fetching 60 days of 5-minute NSE bars for 15 liquid stocks...")
    data_by_sym: dict[str, dict[str, list[dict]]] = {}
    for sym in SYMBOLS:
        try:
            ch = im.fetch_chart(sym, range_str="60d", interval="5m")
            bars = im.parse_bars(ch, interval_minutes=5)
            by_day: dict[str, list[dict]] = defaultdict(list)
            for b in bars:
                by_day[b["date"]].append(b)
            clean = {d: sorted(v, key=lambda x: x["ts"]) for d, v in by_day.items() if len(v) >= 60}
            if clean:
                data_by_sym[sym] = clean
        except Exception as e:
            print(f"  Skipped {sym}: {e}")
        time.sleep(0.15)

    print(f"Loaded {len(data_by_sym)} NSE stocks (~{len(next(iter(data_by_sym.values())))} sessions each).\n")

    variants = [
        ("A: Tight stop (mid - 0.10%, 2.0R) [Your ITC style]", 0.10, 2.0, 0.0, 0.02),
        ("B: Medium stop (mid - 0.35%, 2.0R)", 0.35, 2.0, 0.0, 0.02),
        ("C: Wider stop (mid - 0.50%, 2.0R) + Min 1.0% ch", 0.50, 2.0, 1.0, 0.02),
        ("D: Medium stop (mid - 0.35%, 1.5R) + Min 1.0% ch", 0.35, 1.5, 1.0, 0.02),
    ]

    print("=== 1. ITC.NS ALONE (60 DAYS, Rs 25,000/trade, 0.02% slippage + Indian MIS fees) ===")
    if "ITC.NS" in data_by_sym:
        for name, sb, rr, mc, slip in variants:
            tr = run_symbol_variant(data_by_sym["ITC.NS"], sb, rr, mc, slip)
            s = summarize(name, tr)
            if s["n"] == 0:
                print(f"  {name}: 0 trades")
            else:
                print(f"  {name}")
                print(f"    Trades={s['n']:>3} | Target={s['target_pct']:>4.1f}% Stop={s['stop_pct']:>4.1f}% Flat={s['flat_pct']:>4.1f}% | NetWin={s['win_pct']:>4.1f}% | AvgR={s['avg_r']:+.3f}")
                print(f"    Gross={im.format_inr(s['gross_inr']):>12} | Fees={im.format_inr(s['charges_inr']):>10} | NET={im.format_inr(s['net_inr']):>12} | MaxDD={im.format_inr(s['max_dd_inr'])}")

    print("\n=== 2. ALL 15 NSE STOCKS COMBINED (60 DAYS, Rs 25,000/trade, 0.02% slippage + Indian MIS fees) ===")
    for name, sb, rr, mc, slip in variants:
        all_tr = []
        per_stock = []
        for sym, bd in data_by_sym.items():
            tr = run_symbol_variant(bd, sb, rr, mc, slip)
            all_tr.extend(tr)
            if tr:
                per_stock.append((sym, len(tr), round(sum(x["net_inr"] for x in tr), 2)))
        s = summarize(name, all_tr)
        if s["n"] == 0:
            print(f"  {name}: 0 trades")
            continue
        print(f"  {name}")
        print(f"    Trades={s['n']:>4} | Target={s['target_pct']:>4.1f}% Stop={s['stop_pct']:>4.1f}% Flat={s['flat_pct']:>4.1f}% | NetWin={s['win_pct']:>4.1f}% | AvgR={s['avg_r']:+.3f}")
        print(f"    Gross={im.format_inr(s['gross_inr']):>13} | Fees={im.format_inr(s['charges_inr']):>11} | NET={im.format_inr(s['net_inr']):>13} | MaxDD={im.format_inr(s['max_dd_inr'])}")
        per_stock.sort(key=lambda x: x[2], reverse=True)
        top2 = ", ".join(f"{sym} ({im.format_inr(p, 0)}/{c}t)" for sym, c, p in per_stock[:2])
        bot2 = ", ".join(f"{sym} ({im.format_inr(p, 0)}/{c}t)" for sym, c, p in per_stock[-2:])
        print(f"    Best: {top2}  |  Worst: {bot2}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
