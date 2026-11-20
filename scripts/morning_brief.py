#!/usr/bin/env python3
"""Cloud-ready NSE Rotation Morning Brief & Phone Notifier (GitHub Actions / Local).

Pure Python standard library only. Works even when your laptop is OFF when hosted on GitHub Actions.
Notification channels (configure any 1 or more via GitHub Repository Secrets):
  - WhatsApp (CallMeBot): WHATSAPP_PHONE (e.g. 9198XXXXXXXX) + WHATSAPP_CALLMEBOT_KEY
  - ntfy.sh phone push:   NTFY_TOPIC (e.g. my-secret-nse-alerts-9821)
  - Telegram bot:         TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
  - Gmail email:          GMAIL_USER + GMAIL_APP_PASSWORD + ALERT_TO_EMAIL (optional, defaults to GMAIL_USER)
"""

from __future__ import annotations

import argparse
import email.message
import json
import os
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import india_market as im


def load_rotation_list(path: str = "trader/rotation_watchlist.txt") -> list[tuple[str, str]]:
    items = []
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Watchlist not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|", 1)
            sym = im.normalize_ticker(parts[0].strip(), default_exchange="NSE")
            label = parts[1].strip() if len(parts) > 1 else sym
            items.append((sym, label))
    return items


def build_premarket_report(watchlist: list[tuple[str, str]], now: datetime) -> tuple[str, str]:
    title = f"NSE Pre-Market Brief ({now.strftime('%d %b %Y, %H:%M IST')})"
    lines = [f"Rs 500 Rotation Watchlist — Pre-Market ({now.strftime('%a %d %b %Y')})"]
    for sym, _ in watchlist:
        try:
            ch = im.fetch_chart(sym, range_str="1mo", interval="1d")
            meta = ch.get("meta") or {}
            quotes = ((ch.get("indicators") or {}).get("quote") or [{}])[0]
            closes = [float(c) for c in (quotes.get("close") or []) if c is not None]
            if len(closes) >= 2:
                last_c = closes[-1]
                prev_c = closes[-2]
                chg = (last_c - prev_c) / prev_c * 100.0 if prev_c else 0.0
                ma20 = sum(closes[-20:]) / min(20, len(closes))
                trend = "ABOVE 20MA" if last_c > ma20 else "below 20MA"
                lines.append(f"• {sym[:-3]:<10} Rs {last_c:>6.2f} ({chg:+5.2f}%) | {trend}")
        except Exception as e:
            lines.append(f"• {sym[:-3]:<10} fetch error: {e}")
        time.sleep(0.15)
    lines.append("\nNext auto-alert: ~09:45 IST (after 09:15-09:30 opening chaos settles).")
    return title, "\n".join(lines)


def build_orb_report(watchlist: list[tuple[str, str]], now: datetime, or_minutes: int = 15, pinned: bool = False) -> tuple[str, str]:
    session_date = now.date().isoformat()
    or_end_dt = datetime.combine(now.date(), im.MARKET_OPEN, tzinfo=im.IST) + timedelta(minutes=or_minutes)
    title = f"NSE 09:45 ORB Brief ({now.strftime('%d %b, %H:%M IST')})"

    triggered = []
    near_breakout = []
    weak = []

    for sym, _ in watchlist:
        try:
            ch = im.fetch_chart(sym, range_str="1d", interval="5m")
            meta = ch.get("meta") or {}
            prev_close = float(meta.get("chartPreviousClose") or meta.get("previousClose") or 0)
            bars = [b for b in im.parse_bars(ch, interval_minutes=5, now=now) if b["date"] == session_date]
            or_bars = [b for b in bars if b["dt"] < or_end_dt]
            after_bars = [b for b in bars if b["dt"] >= or_end_dt]
            if len(or_bars) < (or_minutes // 5):
                continue
            live_px = bars[-1]["close"] if pinned else float(meta.get("regularMarketPrice") or bars[-1]["close"])
            or_hi = max(b["high"] for b in or_bars)
            or_lo = min(b["low"] for b in or_bars)
            chg_pct = ((live_px - prev_close) / prev_close * 100.0) if prev_close else 0.0

            hit_bar = None
            for b in after_bars:
                if b["close"] > or_hi:
                    hit_bar = b
                    break

            if hit_bar:
                entry = hit_bar["close"]
                stop = round(((or_hi + or_lo) / 2.0) * 20) / 20.0
                risk = max(0.05, round(entry - stop, 2))
                target = round((entry + 1.5 * risk) * 20) / 20.0
                hit_time = (hit_bar["dt"] + timedelta(minutes=5)).strftime("%H:%M")
                triggered.append({
                    "sym": sym[:-3],
                    "live": live_px,
                    "chg": chg_pct,
                    "hit_time": hit_time,
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "or_lo": or_lo,
                    "or_hi": or_hi,
                })
            elif live_px >= or_hi * 0.995:
                near_breakout.append((sym[:-3], live_px, chg_pct, or_lo, or_hi))
            else:
                weak.append((sym[:-3], live_px, chg_pct, or_lo, or_hi))
        except Exception:
            continue
        time.sleep(0.15)

    lines = [f"Rs 500 Challenge — Post-Chaos Scan ({now.strftime('%d %b %Y, %H:%M IST')})"]
    lines.append(f"Opening Range: 09:15-{or_end_dt.strftime('%H:%M')} IST | Ready for 09:50 IST review\n")

    if triggered:
        triggered.sort(key=lambda x: x["chg"], reverse=True)
        lines.append(f"TRIGGERED ORB ({len(triggered)}):")
        for t in triggered:
            lines.append(
                f"• {t['sym']} Rs {t['live']:.2f} ({t['chg']:+.2f}%) | broke {t['or_hi']:.2f} @ {t['hit_time']}"
                f"\n  Plan preview: Stop Rs {t['stop']:.2f} | 1.5R Target Rs {t['target']:.2f}"
            )
    else:
        lines.append("TRIGGERED ORB: None yet.")

    if near_breakout:
        lines.append(f"\nWATCHING NEAR RANGE HIGH ({len(near_breakout)}):")
        for s, px, chg, lo, hi in near_breakout:
            lines.append(f"• {s} Rs {px:.2f} ({chg:+.2f}%) | need > Rs {hi:.2f} (OR {lo:.2f}-{hi:.2f})")

    if weak:
        lines.append(f"\nBELOW RANGE ({len(weak)}):")
        lines.append("  " + ", ".join(f"{s} ({chg:+.1f}%)" for s, _, chg, _, _ in weak))

    lines.append("\nRules: Pick max 2 stocks (total <= Rs 500, MIS 1x), check Time Machine first, flat by 15:10 IST.")
    return title, "\n".join(lines)


def build_close_reminder(now: datetime) -> tuple[str, str]:
    title = f"NSE Square-Off Reminder ({now.strftime('%H:%M IST')})"
    body = (
        f"It is {now.strftime('%H:%M IST')}.\n\n"
        "Check Paytm Money Positions RIGHT NOW:\n"
        "• Square off ANY open Intraday (MIS) position before 15:10 IST.\n"
        "• Avoid the Rs 59 (Rs 50 + GST) auto-square-off penalty at 15:15-15:20 IST.\n"
        "• Log today's net result in trader/challenge_ledger.md."
    )
    return title, body


def send_whatsapp_callmebot(title: str, body: str) -> bool:
    phone = (os.environ.get("WHATSAPP_PHONE") or "").strip().lstrip("+")
    apikey = (os.environ.get("WHATSAPP_CALLMEBOT_KEY") or "").strip()
    if not phone or not apikey:
        return False
    # Keep WhatsApp message crisp and under CallMeBot URL length limits
    text = f"*{title}*\n\n{body}"
    if len(text) > 1500:
        text = text[:1490] + "\n..."
    params = urllib.parse.urlencode({"phone": phone, "text": text, "apikey": apikey})
    url = f"https://api.callmebot.com/whatsapp.php?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": im.UA}, method="GET")
    with urllib.request.urlopen(req, timeout=20) as r:
        print(f"WhatsApp (CallMeBot) sent -> HTTP {r.status}")
    return True


def send_ntfy(title: str, body: str) -> bool:
    topic = (os.environ.get("NTFY_TOPIC") or "").strip()
    if not topic:
        return False
    url = f"https://ntfy.sh/{urllib.parse.quote(topic)}"
    req = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        print(f"ntfy.sh sent -> HTTP {r.status}")
    return True


def send_telegram(title: str, body: str) -> bool:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": f"{title}\n\n{body}"}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"Telegram sent -> HTTP {r.status}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {e.code}: {detail}") from e
    return True


def send_gmail(title: str, body: str) -> bool:
    user = (os.environ.get("GMAIL_USER") or "").strip()
    app_pw = (os.environ.get("GMAIL_APP_PASSWORD") or "").strip()
    to_addr = (os.environ.get("ALERT_TO_EMAIL") or user).strip()
    if not user or not app_pw or not to_addr:
        return False
    msg = email.message.EmailMessage()
    msg["Subject"] = title
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(body)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=20) as srv:
        srv.login(user, app_pw)
        srv.send_message(msg)
    print(f"Gmail sent -> {to_addr}")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description="NSE Cloud Morning Brief & Phone Notifier")
    p.add_argument("--mode", choices=["auto", "premarket", "orb", "close_reminder"], default="auto")
    p.add_argument("--watchlist", default="trader/rotation_watchlist.txt")
    p.add_argument("--now", default=None, help="Pin IST timestamp ('YYYY-MM-DD HH:MM') for testing")
    p.add_argument("--dry-run", action="store_true", help="Print brief without sending notifications")
    p.add_argument("--force-holiday", action="store_true", help="Run even on NSE holidays/weekends")
    args = p.parse_args()

    now = im.now_ist(args.now)
    if not im.is_trading_day(now.date()) and not args.force_holiday:
        hol = im.holiday_name(now.date()) or now.strftime("%A")
        print(f"Skipping: NSE/BSE closed on {now.date().isoformat()} ({hol}).")
        return 0

    mode = args.mode
    if mode == "auto":
        hhmm = now.strftime("%H:%M")
        if hhmm < "09:30":
            mode = "premarket"
        elif hhmm < "14:55":
            mode = "orb"
        else:
            mode = "close_reminder"

    if mode == "close_reminder":
        title, body = build_close_reminder(now)
    else:
        wl = load_rotation_list(args.watchlist)
        if mode == "premarket":
            title, body = build_premarket_report(wl, now)
        else:
            title, body = build_orb_report(wl, now, pinned=bool(args.now))

    print(f"=== {title} ===\n{body}\n")

    if args.dry_run:
        print("(dry-run: notifications skipped)")
        return 0

    sent_any = False
    had_error = False
    for fn in (send_whatsapp_callmebot, send_ntfy, send_telegram, send_gmail):
        try:
            if fn(title, body):
                sent_any = True
        except Exception as e:
            had_error = True
            print(f"Notifier error ({fn.__name__}): {e}", file=sys.stderr)

    if had_error and not sent_any:
        return 1
    if not sent_any:
        print("No notification secrets configured (set WHATSAPP_PHONE+WHATSAPP_CALLMEBOT_KEY, NTFY_TOPIC, TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID, or GMAIL_USER+GMAIL_APP_PASSWORD).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
