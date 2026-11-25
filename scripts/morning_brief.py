#!/usr/bin/env python3
"""Cloud-ready NSE Rotation Morning Brief & Phone Notifier (GitHub Actions / Local).

Pure Python standard library only. Works even when your laptop is OFF when hosted on GitHub Actions.
Notification channels (configure any 1 or more via GitHub Repository Secrets):
  - Telegram bot:         TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (rich HTML formatting)
  - ntfy.sh phone push:   NTFY_TOPIC (e.g. my-secret-nse-alerts-9821)
  - WhatsApp (CallMeBot): WHATSAPP_PHONE + WHATSAPP_CALLMEBOT_KEY
  - Gmail email:          GMAIL_USER + GMAIL_APP_PASSWORD + ALERT_TO_EMAIL (optional)
"""

from __future__ import annotations

import argparse
import email.message
import html
import json
import os
import re
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

NUM_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s))


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


def best_500_combo(candidates: list[dict], budget: float = 500.0) -> list[dict]:
    """Pick up to 2 strongest active breakouts whose 1-share total fits inside budget."""
    best: list[dict] = []
    best_score = -1e9
    # Try pairs first
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = candidates[i], candidates[j]
            cost = a["live"] + b["live"]
            if cost <= budget:
                score = a["chg"] + b["chg"]
                if score > best_score:
                    best_score = score
                    best = [a, b]
    if best:
        return best
    # Fallback: best single stock under budget
    for c in candidates:
        if c["live"] <= budget:
            return [c]
    return []


def build_premarket_report(watchlist: list[tuple[str, str]], now: datetime) -> tuple[str, str]:
    title = f"NSE Pre-Market Brief ({now.strftime('%d %b, %H:%M IST')})"
    above = []
    below = []
    for sym, _ in watchlist:
        try:
            ch = im.fetch_chart(sym, range_str="1mo", interval="1d")
            quotes = ((ch.get("indicators") or {}).get("quote") or [{}])[0]
            closes = [float(c) for c in (quotes.get("close") or []) if c is not None]
            if len(closes) >= 2:
                last_c = closes[-1]
                prev_c = closes[-2]
                chg = (last_c - prev_c) / prev_c * 100.0 if prev_c else 0.0
                ma20 = sum(closes[-20:]) / min(20, len(closes))
                row = {"sym": sym[:-3], "px": last_c, "chg": chg}
                if last_c > ma20:
                    above.append(row)
                else:
                    below.append(row)
        except Exception:
            continue
        time.sleep(0.15)

    all_rows = sorted(above + below, key=lambda x: x["chg"], reverse=True)
    above_set = {r["sym"] for r in above}

    t_lines = [
        "STOCK        PREV    CHG%   20MA",
        "---------------------------------",
    ]
    for r in all_rows:
        tag = "UP  " if r["sym"] in above_set else "DOWN"
        t_lines.append(f"{r['sym']:<10} {r['px']:>6.2f} {r['chg']:>+6.2f}%  {tag}")

    lines = [
        "🌅 <b>NSE ₹500 Challenge — Pre-Market</b>",
        f"🗓 <code>{now.strftime('%a, %d %b %Y • %H:%M IST')}</code>",
        f"<pre>{html.escape(chr(10).join(t_lines))}</pre>",
        f"🟢 Above 20MA: <b>{len(above)}</b>  |  🔴 Below 20MA: <b>{len(below)}</b>",
        "⏳ <i>Next auto-alert at ~09:45 IST (after morning chaos settles).</i>",
    ]

    # Casual Hinglish bro-talk companion message
    top_names = ", ".join(f"<b>{r['sym']}</b> (<code>₹{r['px']:.0f}</code>)" for r in above[:3]) or "koi nahi"
    bro = (
        f"Yo Veeraj! ☕ Good morning ({now.strftime('%d %b')})\n\n"
        f"Aaj subah apni 10 stocks list mein <b>{len(above)}</b> up-trend mein hain aur <b>{len(below)}</b> neeche.\n"
        f"Sabse strong abhi: {top_names}\n\n"
        "Abhi <code>09:15–09:45</code> wala subah ka chaos dekhne de — <code>09:45</code> pe main tujhe exact setups aur Entry / Stop / Target bhejunga. Tab aaja chat pe! 👋"
    )
    return title, "\n".join(lines), bro


def build_orb_report(watchlist: list[tuple[str, str]], now: datetime, or_minutes: int = 15, pinned: bool = False) -> tuple[str, str]:
    session_date = now.date().isoformat()
    or_end_dt = datetime.combine(now.date(), im.MARKET_OPEN, tzinfo=im.IST) + timedelta(minutes=or_minutes)
    title = f"NSE ORB Brief ({now.strftime('%d %b, %H:%M IST')})"

    strong_orb = []
    faded_orb = []
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
                item = {
                    "sym": sym[:-3],
                    "live": live_px,
                    "chg": chg_pct,
                    "hit_time": hit_time,
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    "or_lo": or_lo,
                    "or_hi": or_hi,
                    "already_hit_target": live_px >= target,
                }
                if live_px > or_hi and chg_pct >= 0:
                    strong_orb.append(item)
                else:
                    faded_orb.append(item)
            elif live_px >= or_hi * 0.994:
                near_breakout.append((sym[:-3], live_px, chg_pct, or_lo, or_hi))
            else:
                weak.append((sym[:-3], live_px, chg_pct))
        except Exception:
            continue
        time.sleep(0.15)

    strong_orb.sort(key=lambda x: x["chg"], reverse=True)
    faded_orb.sort(key=lambda x: x["chg"], reverse=True)

    lines = [
        "📊 <b>NSE ₹500 Challenge — Post-Chaos Brief</b>",
        f"🗓 <code>{now.strftime('%a, %d %b • %H:%M IST')}</code>  |  OR <code>09:15–{or_end_dt.strftime('%H:%M')}</code>",
    ]

    if strong_orb:
        lines.append(f"\n🟢 <b>CLEAN BREAKOUTS — GREEN ({len(strong_orb)})</b>")
        t_lines = [
            "STOCK       LIVE    STOP    1.5R",
            "----------------------------------",
        ]
        any_chased = False
        for t in strong_orb:
            star = "*" if t["already_hit_target"] else " "
            if t["already_hit_target"]:
                any_chased = True
            t_lines.append(f"{t['sym']:<10} {t['live']:>6.2f}  {t['stop']:>6.2f}  {t['target']:>6.2f}{star}")
        lines.append(f"<pre>{html.escape(chr(10).join(t_lines))}</pre>")
        if any_chased:
            lines.append("<i>* already past 1.5R target — don't chase</i>")

        actionable = [t for t in strong_orb if not t["already_hit_target"]] or strong_orb
        combo = best_500_combo(actionable, budget=500.0)
        if combo:
            total_cost = sum(x["live"] for x in combo)
            combo_str = " + ".join(f"<b>1 {x['sym']}</b> (<code>₹{x['live']:.0f}</code>)" for x in combo)
            lines.append(f"💰 <b>Top ₹500 Fit:</b> {combo_str} = <code>₹{total_cost:.2f}</code>")
    else:
        lines.append("\n🟢 <b>CLEAN BREAKOUTS:</b> None holding green above range yet.")

    # Compact status table for all remaining stocks (faded + watching + weak)
    others_rows = []
    for t in faded_orb:
        others_rows.append((t["sym"], t["live"], t["chg"], "FADED"))
    for s, px, chg, lo, hi in near_breakout:
        others_rows.append((s, px, chg, f">{hi:.1f}"))
    for s, px, chg in weak:
        others_rows.append((s, px, chg, "WEAK"))
    if others_rows:
        lines.append("\n📋 <b>OTHER STOCKS</b>")
        o_lines = [
            "STOCK       LIVE    CHG%   STATUS",
            "----------------------------------",
        ]
        for s, px, chg, st in others_rows:
            o_lines.append(f"{s:<10} {px:>6.2f} {chg:>+6.1f}%  {st}")
        lines.append(f"<pre>{html.escape(chr(10).join(o_lines))}</pre>")

    lines.append("⚠️ <i>MIS 1x • Max 2 ≤ ₹500 • Exit by 15:10 IST</i>")

    # Casual Hinglish bro-talk companion message
    all_seen = strong_orb + faded_orb + [{"sym": s, "live": px, "chg": chg} for s, px, chg, _, _ in near_breakout] + [{"sym": s, "live": px, "chg": chg} for s, px, chg in weak]
    greens = [x for x in all_seen if x["chg"] >= 0]
    reds = [x for x in all_seen if x["chg"] < 0]
    greens.sort(key=lambda x: x["chg"], reverse=True)
    reds.sort(key=lambda x: x["chg"])

    bro_lines = [
        f"Yo Veeraj! 👋 Subah ka chaos settle ho gaya ({now.strftime('%H:%M IST')}) — chal aaj ka scene dekh:\n",
        "📋 <b>Aaj ki 10 stocks list:</b>",
        "🟢 Green: " + (", ".join(f"{x['sym']} ({x['chg']:+.1f}%)" for x in greens) or "koi nahi"),
        "🔴 Red: " + (", ".join(f"{x['sym']} ({x['chg']:+.1f}%)" for x in reds) or "koi nahi") + "\n",
    ]

    if strong_orb:
        actionable = [t for t in strong_orb if not t["already_hit_target"]] or strong_orb
        picks = best_500_combo(actionable, budget=500.0)
        if picks:
            tot = sum(p["live"] for p in picks)
            bro_lines.append(f"🎯 <b>₹500 ke hisaab se ye {len(picks)} setups sabse clean lag rahe hain (1x MIS):</b>\n")
            for idx, p in enumerate(picks):
                num = NUM_EMOJI[idx]
                chase = "\n   ⚡ <i>Note: Ye already 1.5R target paar kar gaya, chase mat karna!</i>" if p["already_hit_target"] else ""
                bro_lines.append(
                    f"{num} <b>{p['sym']}</b> (abhi <code>₹{p['live']:.2f}</code>, {p['chg']:+.2f}%)\n"
                    f"   • Entry: <code>~₹{p['entry']:.2f}</code> ({p['hit_time']} pe breakout)\n"
                    f"   • Stop-loss: <code>₹{p['stop']:.2f}</code>\n"
                    f"   • Target (1.5R): <code>₹{p['target']:.2f}</code>{chase}\n"
                )
            bro_lines.append(f"💵 Dono ka total: <code>₹{tot:.2f}</code> (₹500 ke andar fit!)\n")
        else:
            bro_lines.append("🎯 Breakout toh aaya hai par ₹500 combo check karna padega.\n")
    else:
        bro_lines.append("😴 Abhi tak koi clean green breakout nahi aaya — jabardasti trade nahi lena, thoda wait karte hain!\n")

    bro_lines.append("⚠️ <i>Sirf data &amp; math hai — order lene se pehle Time Machine check zaroor karenge.</i>")
    bro_lines.append("💬 <b>Aaja Antigravity chat pe — dono ko check karke 9:50 pe final call lete hain!</b> 🚀")
    return title, "\n".join(lines), "\n".join(bro_lines)


def build_close_reminder(now: datetime) -> tuple[str, str, str]:
    title = f"NSE Square-Off Reminder ({now.strftime('%H:%M IST')})"
    body = (
        f"🚨 <b>MIS SQUARE-OFF REMINDER — <code>{now.strftime('%H:%M IST')}</code></b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📱 Open <b>Paytm Money → Positions</b> RIGHT NOW:\n\n"
        "• Square off ANY open <b>Intraday (MIS)</b> position before <code>15:10 IST</code>.\n"
        "• Avoid the <code>₹59</code> (₹50 + GST) broker auto-square-off penalty at <code>15:15</code>.\n"
        "• Log today's net P&amp;L in <code>challenge_ledger.md</code>."
    )
    bro = (
        f"Oye bhai! ⏰ <code>{now.strftime('%H:%M IST')}</code> baj gaye!\n\n"
        "Paytm Money khol ke check kar — koi bhi Intraday (MIS) position open ho toh <b>3:10 PM se pehle exit maar de</b>, warna ₹59 penalty lag jaayegi.\n\n"
        "💬 Exit karke chat pe aaja — aaj ka profit/loss ledger mein update karte hain!"
    )
    return title, body, bro


def build_day_end_report(watchlist: list[tuple[str, str]], now: datetime) -> tuple[str, str, str]:
    title = f"NSE Day-End Wrap ({now.strftime('%d %b, %H:%M IST')})"
    rows = []
    for sym, _ in watchlist:
        try:
            ch = im.fetch_chart(sym, range_str="1d", interval="5m")
            meta = ch.get("meta") or {}
            close_px = float(meta.get("regularMarketPrice") or 0)
            prev_c = float(meta.get("chartPreviousClose") or meta.get("previousClose") or 0)
            day_hi = float(meta.get("regularMarketDayHigh") or close_px)
            day_lo = float(meta.get("regularMarketDayLow") or close_px)
            chg = ((close_px - prev_c) / prev_c * 100.0) if prev_c else 0.0
            rows.append({
                "sym": sym[:-3],
                "close": close_px,
                "chg": chg,
                "hi": day_hi,
                "lo": day_lo,
                "range_pct": ((day_hi - day_lo) / day_lo * 100.0) if day_lo else 0.0,
            })
        except Exception:
            continue
        time.sleep(0.15)

    rows.sort(key=lambda x: x["chg"], reverse=True)
    greens = [r for r in rows if r["chg"] >= 0]
    reds = [r for r in rows if r["chg"] < 0]

    t_lines = [
        "STOCK       CLOSE    CHG%   RNG",
        "---------------------------------",
    ]
    for r in rows:
        t_lines.append(f"{r['sym']:<10} {r['close']:>6.2f} {r['chg']:>+6.2f}%  {r['range_pct']:>3.1f}%")

    lines = [
        "🏁 <b>NSE ₹500 Challenge — Day-End Wrap</b>",
        f"🗓 <code>{now.strftime('%a, %d %b %Y • Market Closed')}</code>",
        f"<pre>{html.escape(chr(10).join(t_lines))}</pre>",
        f"🟢 Green: <b>{len(greens)}</b>  |  🔴 Red: <b>{len(reds)}</b>",
        "📒 <i>Update today's trade &amp; lesson in challenge_ledger.md.</i>",
    ]

    top = rows[0] if rows else None
    bot = rows[-1] if rows else None
    top_str = f"<b>{top['sym']}</b> ({top['chg']:+.2f}%, ₹{top['close']:.2f})" if top else "-"
    bot_str = f"<b>{bot['sym']}</b> ({bot['chg']:+.2f}%, ₹{bot['close']:.2f})" if bot else "-"
    bro = (
        f"Market band bhai! 🏁 ({now.strftime('%a %d %b')})\n\n"
        f"Aaj apni 10 stocks list mein <b>{len(greens)} green</b> aur <b>{len(reds)} red</b> band hue:\n"
        f"🏆 Best mover: {top_str}\n"
        f"📉 Weakest: {bot_str}\n\n"
        "Aaj jo bhi trade liya (ya skip kiya), chat pe aake ledger mein note kar lete hain — phir chill kar, kal fresh dekhenge! 😎"
    )
    return title, "\n".join(lines), bro


def send_whatsapp_callmebot(title: str, html_body: str) -> bool:
    phone = (os.environ.get("WHATSAPP_PHONE") or "").strip().lstrip("+")
    apikey = (os.environ.get("WHATSAPP_CALLMEBOT_KEY") or "").strip()
    if not phone or not apikey:
        return False
    text = strip_html(html_body)
    if len(text) > 1500:
        text = text[:1490] + "\n..."
    params = urllib.parse.urlencode({"phone": phone, "text": text, "apikey": apikey})
    url = f"https://api.callmebot.com/whatsapp.php?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": im.UA}, method="GET")
    with urllib.request.urlopen(req, timeout=20) as r:
        print(f"WhatsApp (CallMeBot) sent -> HTTP {r.status}")
    return True


def send_ntfy(title: str, html_body: str) -> bool:
    topic = (os.environ.get("NTFY_TOPIC") or "").strip()
    if not topic:
        return False
    url = f"https://ntfy.sh/{urllib.parse.quote(topic)}"
    req = urllib.request.Request(
        url,
        data=strip_html(html_body).encode("utf-8"),
        headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        print(f"ntfy.sh sent -> HTTP {r.status}")
    return True


def send_telegram(title: str, html_body: str) -> bool:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": html_body,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"Telegram sent -> HTTP {r.status}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram HTTP {e.code}: {detail}") from e
    return True


def send_gmail(title: str, html_body: str) -> bool:
    user = (os.environ.get("GMAIL_USER") or "").strip()
    app_pw = (os.environ.get("GMAIL_APP_PASSWORD") or "").strip()
    to_addr = (os.environ.get("ALERT_TO_EMAIL") or user).strip()
    if not user or not app_pw or not to_addr:
        return False
    msg = email.message.EmailMessage()
    msg["Subject"] = title
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(strip_html(html_body))
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=20) as srv:
        srv.login(user, app_pw)
        srv.send_message(msg)
    print(f"Gmail sent -> {to_addr}")
    return True


ALLOWED_WINDOWS_IST = {
    "premarket": ("08:30", "09:20"),
    "orb": ("09:35", "11:00"),
    "close_reminder": ("14:55", "15:25"),
    "day_end": ("15:30", "17:00"),
}


def main() -> int:
    p = argparse.ArgumentParser(description="NSE Cloud Morning Brief & Phone Notifier")
    p.add_argument("--mode", choices=["auto", "premarket", "orb", "close_reminder", "day_end"], default="auto")
    p.add_argument("--watchlist", default="trader/rotation_watchlist.txt")
    p.add_argument("--now", default=None, help="Pin IST timestamp ('YYYY-MM-DD HH:MM') for testing")
    p.add_argument("--dry-run", action="store_true", help="Print brief without sending notifications")
    p.add_argument("--force-holiday", action="store_true", help="Run even on NSE holidays/weekends")
    p.add_argument("--enforce-window", action="store_true", help="Skip if fired outside allowed IST window (protects against delayed cloud crons)")
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
        elif hhmm < "15:25":
            mode = "close_reminder"
        else:
            mode = "day_end"

    if args.enforce_window and mode in ALLOWED_WINDOWS_IST:
        hhmm = now.strftime("%H:%M")
        win_start, win_end = ALLOWED_WINDOWS_IST[mode]
        if not (win_start <= hhmm <= win_end):
            print(f"Skipping stale delayed run: {mode} fired at {hhmm} IST (allowed window {win_start}-{win_end} IST).")
            return 0

    if mode == "close_reminder":
        title, html_body, bro_body = build_close_reminder(now)
    else:
        wl = load_rotation_list(args.watchlist)
        if mode == "premarket":
            title, html_body, bro_body = build_premarket_report(wl, now)
        elif mode == "day_end":
            title, html_body, bro_body = build_day_end_report(wl, now)
        else:
            title, html_body, bro_body = build_orb_report(wl, now, pinned=bool(args.now))

    print(strip_html(html_body) + "\n---\n" + strip_html(bro_body) + "\n")

    if args.dry_run:
        print("(dry-run: notifications skipped)")
        return 0

    sent_any = False
    had_error = False
    for fn in (send_whatsapp_callmebot, send_ntfy, send_telegram, send_gmail):
        try:
            if fn(title, html_body):
                sent_any = True
                # Also send casual Hinglish bro-talk follow-up on Telegram
                if fn is send_telegram and bro_body:
                    time.sleep(0.5)
                    send_telegram(title, bro_body)
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
