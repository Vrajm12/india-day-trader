"""Shared Indian equity market utilities for NSE & BSE (IST, INR, Yahoo Finance, NSE archives).

Pure Python standard library only. Zero API keys required.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dtime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), name="IST")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
YAHOO_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")

MARKET_OPEN = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
PREOPEN_START = dtime(9, 0)
DEFAULT_FLAT_BY = "15:15"

# Official NSE/BSE Equity Segment Holidays (2026 verified from nseindia.com; 2027 major fixed + estimated national holidays)
NSE_HOLIDAYS = {
    # 2026 official NSE/BSE equity holidays
    date(2026, 1, 26): "Republic Day",
    date(2026, 3, 3): "Holi",
    date(2026, 3, 26): "Shri Ram Navami",
    date(2026, 3, 31): "Shri Mahavir Jayanti",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    date(2026, 5, 1): "Maharashtra Day",
    date(2026, 5, 28): "Bakri Id",
    date(2026, 6, 26): "Muharram",
    date(2026, 9, 14): "Ganesh Chaturthi",
    date(2026, 10, 2): "Mahatma Gandhi Jayanti",
    date(2026, 10, 20): "Dussehra",
    date(2026, 11, 10): "Diwali-Balipratipada",
    date(2026, 11, 24): "Prakash Gurpurb Sri Guru Nanak Dev",
    date(2026, 12, 25): "Christmas",
    # 2027 fixed national holidays (exchange circular updates festival dates each Dec)
    date(2027, 1, 26): "Republic Day",
    date(2027, 4, 14): "Dr. Baba Saheb Ambedkar Jayanti",
    date(2027, 5, 1): "Maharashtra Day",
    date(2027, 8, 15): "Independence Day",
    date(2027, 10, 2): "Mahatma Gandhi Jayanti",
    date(2027, 12, 25): "Christmas",
}

DEFAULT_CONFIG = {
    "currency": "INR",
    "default_exchange": "NSE",
    "budget": 50000,
    "cash_buffer_pct": 10,
    "max_position_pct": 50,
    "max_order_inr": 25000,
    "min_order_inr": 500,
    "max_loss_per_trade_inr": 500,
    "max_daily_loss_inr": 1500,
    "max_trades_per_day": 3,
    "max_orders_per_day": 10,
    "min_reward_risk": 1.0,
    "require_stop": True,
    "no_entries_before": "09:30",
    "no_entries_after": "14:45",
    "flat_by": "15:15",
    "product": "MIS",
    "broker": "zerodha",
    "paper": True,
    "blocked": [],
    "allow_fno": False,
    "allow_margin": False,
    "allow_short": False,
    "brokerage_per_order_inr": 20.0,
}


def now_ist(pin: str | None = None) -> datetime:
    """Return current IST datetime, or parse a pinned 'YYYY-MM-DD HH:MM' / 'YYYY-MM-DD' string."""
    if not pin:
        return datetime.now(IST)
    s = pin.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == "%Y-%m-%d":
                dt = dt.replace(hour=15, minute=30)
            return dt.replace(tzinfo=IST)
        except ValueError:
            continue
    raise ValueError(f"Invalid --now IST timestamp: {pin!r} (use 'YYYY-MM-DD HH:MM')")


def parse_hhmm(val: str) -> dtime:
    parts = val.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid HH:MM time: {val!r}")
    return dtime(int(parts[0]), int(parts[1]))


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d not in NSE_HOLIDAYS


def holiday_name(d: date) -> str | None:
    return NSE_HOLIDAYS.get(d)


def next_trading_day(d: date) -> date:
    cur = d + timedelta(days=1)
    while not is_trading_day(cur):
        cur += timedelta(days=1)
    return cur


def market_status(now: datetime | None = None) -> dict:
    dt = now or now_ist()
    d = dt.date()
    t = dt.time().replace(second=0, microsecond=0)
    hol = holiday_name(d)
    if d.weekday() >= 5:
        nxt = next_trading_day(d)
        return {
            "open": False,
            "phase": "weekend",
            "reason": f"NSE/BSE closed ({d.strftime('%A')})",
            "now_ist": dt.strftime("%Y-%m-%d %H:%M IST"),
            "next_open": f"{nxt.isoformat()} 09:15 IST",
        }
    if hol:
        nxt = next_trading_day(d)
        return {
            "open": False,
            "phase": "holiday",
            "reason": f"NSE/BSE closed ({hol})",
            "now_ist": dt.strftime("%Y-%m-%d %H:%M IST"),
            "next_open": f"{nxt.isoformat()} 09:15 IST",
        }
    if t < PREOPEN_START:
        return {
            "open": False,
            "phase": "before_open",
            "reason": "NSE/BSE closed, before pre-open (09:00 IST)",
            "now_ist": dt.strftime("%Y-%m-%d %H:%M IST"),
            "next_open": f"{d.isoformat()} 09:15 IST",
        }
    if PREOPEN_START <= t < MARKET_OPEN:
        return {
            "open": False,
            "phase": "pre_open",
            "reason": "NSE/BSE pre-open session (09:00-09:15 IST)",
            "now_ist": dt.strftime("%Y-%m-%d %H:%M IST"),
            "next_open": f"{d.isoformat()} 09:15 IST",
        }
    if MARKET_OPEN <= t < MARKET_CLOSE:
        return {
            "open": True,
            "phase": "open",
            "reason": "NSE/BSE open (regular session 09:15-15:30 IST)",
            "now_ist": dt.strftime("%Y-%m-%d %H:%M IST"),
            "next_close": f"{d.isoformat()} 15:30 IST",
        }
    nxt = next_trading_day(d)
    return {
        "open": False,
        "phase": "after_close",
        "reason": "NSE/BSE closed, after 15:30 IST",
        "now_ist": dt.strftime("%Y-%m-%d %H:%M IST"),
        "next_open": f"{nxt.isoformat()} 09:15 IST",
    }


def normalize_ticker(raw: str, default_exchange: str = "NSE") -> str:
    """Normalize Indian stock symbol to Yahoo Finance canonical format (.NS or .BO).

    Examples:
      'RELIANCE' -> 'RELIANCE.NS' (or '.BO' if default_exchange='BSE')
      'NSE:TCS' -> 'TCS.NS'
      'BSE:RELIANCE' -> 'RELIANCE.BO'
      '500325.BO' -> '500325.BO'
      '^NSEI' -> '^NSEI'
    """
    s = raw.strip().upper()
    if not s:
        raise ValueError("Empty ticker symbol")
    if s.startswith("^"):
        return s
    if s.startswith("NSE:"):
        base = s[4:].strip()
        if base.endswith(".NS") or base.endswith(".BO"):
            base = base[:-3]
        return f"{base}.NS"
    if s.startswith("BSE:"):
        base = s[4:].strip()
        if base.endswith(".NS") or base.endswith(".BO"):
            base = base[:-3]
        return f"{base}.BO"
    if s.endswith(".NS") or s.endswith(".BO"):
        return s
    # Pure numeric 6-digit codes are BSE scrip codes
    if re.fullmatch(r"\d{6}", s):
        return f"{s}.BO"
    suffix = ".BO" if default_exchange.upper() == "BSE" else ".NS"
    return f"{s}{suffix}"


def split_ticker(symbol: str) -> tuple[str, str]:
    """Return (base_symbol, exchange) e.g. ('RELIANCE', 'NSE') or ('TCS', 'BSE')."""
    s = symbol.strip().upper()
    if s.endswith(".BO"):
        return s[:-3], "BSE"
    if s.endswith(".NS"):
        return s[:-3], "NSE"
    if s.startswith("BSE:"):
        return s[4:], "BSE"
    if s.startswith("NSE:"):
        return s[4:], "NSE"
    return s, "NSE"


def format_inr(amount: float | int, decimals: int = 2) -> str:
    """Format an INR amount using standard readable grouping with Rs. / ₹ prefix."""
    sign = "-" if amount < 0 else ""
    val = abs(float(amount))
    if decimals == 0:
        return f"{sign}Rs {val:,.0f}"
    return f"{sign}Rs {val:,.{decimals}f}"


def estimate_intraday_charges(buy_value: float, sell_value: float, brokerage_per_order: float = 20.0, exchange: str = "NSE") -> dict:
    """Approximate Indian equity intraday (MIS) statutory + brokerage charges in INR."""
    turnover = buy_value + sell_value
    # Discount broker typical: min(0.03% of leg, Rs 20) per executed order
    brok_buy = min(buy_value * 0.0003, brokerage_per_order)
    brok_sell = min(sell_value * 0.0003, brokerage_per_order)
    brokerage = round(brok_buy + brok_sell, 2)
    stt = round(sell_value * 0.00025, 2)  # 0.025% on sell side for equity intraday
    exch_rate = 0.0000297 if exchange.upper() == "NSE" else 0.0000375
    exchange_txn = round(turnover * exch_rate, 2)
    sebi = round(turnover * 0.000001, 2)  # Rs 10 per crore
    stamp = round(buy_value * 0.00003, 2)  # 0.003% on buy side
    gst = round(0.18 * (brokerage + exchange_txn + sebi), 2)
    total = round(brokerage + stt + exchange_txn + sebi + stamp + gst, 2)
    return {
        "brokerage": brokerage,
        "stt": stt,
        "exchange_txn": exchange_txn,
        "sebi": sebi,
        "stamp_duty": stamp,
        "gst": gst,
        "total": total,
    }


def load_json(path: str, default=None):
    if not path or not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path: str, data) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def load_config(path: str = "trader/config.json") -> dict:
    cfg = dict(DEFAULT_CONFIG)
    user = load_json(path)
    if isinstance(user, dict):
        cfg.update(user)
    return cfg


def http_get(url: str, headers: dict | None = None, timeout: int = 15, retries: int = 1) -> bytes:
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
                    try:
                        data = gzip.decompress(data)
                    except OSError:
                        pass
                return data
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 and attempt < retries:
                time.sleep(3.0)
                continue
            if e.code >= 500 and attempt < retries:
                time.sleep(1.0)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.0)
                continue
            raise
    raise last_err


def yahoo_get_json(path: str, timeout: int = 15) -> dict:
    """Fetch a Yahoo Finance JSON path with query2 -> query1 fallback."""
    last_err = None
    for host in YAHOO_HOSTS:
        url = f"https://{host}{path}"
        try:
            raw = http_get(url, timeout=timeout, retries=1)
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (400, 404):
                raise
            continue
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Yahoo Finance request failed for {path}: {last_err}")


def fetch_chart(symbol: str, range_str: str = "1d", interval: str = "5m", default_exchange: str = "NSE") -> dict:
    """Fetch Yahoo v8 chart JSON for an NSE/BSE symbol."""
    ys = normalize_ticker(symbol, default_exchange=default_exchange)
    q = urllib.parse.quote(ys, safe="^.-")
    data = yahoo_get_json(f"/v8/finance/chart/{q}?range={range_str}&interval={interval}&includePrePost=false")
    res = (data.get("chart") or {}).get("result") or []
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise RuntimeError(f"No chart data for {ys}: {err.get('description', 'unknown error')}")
    return res[0]


def fetch_spark(symbols: list[str], range_str: str = "1mo", interval: str = "1d") -> dict:
    """Fetch Yahoo spark batch JSON for up to 20 symbols."""
    joined = ",".join(urllib.parse.quote(s, safe="^.-") for s in symbols)
    return yahoo_get_json(f"/v8/finance/spark?symbols={joined}&range={range_str}&interval={interval}")


def parse_bars(chart_result: dict, interval_minutes: int | None = None, now: datetime | None = None) -> list[dict]:
    """Parse Yahoo v8 chart result into clean IST OHLCV bars.

    Drops null rows, off-grid live ticks (when interval_minutes is set), and incomplete bars.
    """
    timestamps = chart_result.get("timestamp") or []
    quotes = ((chart_result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quotes.get("open") or []
    highs = quotes.get("high") or []
    lows = quotes.get("low") or []
    closes = quotes.get("close") or []
    vols = quotes.get("volume") or []

    cutoff = now or now_ist()
    bars = []
    for i, ts in enumerate(timestamps):
        if ts is None:
            continue
        o = opens[i] if i < len(opens) else None
        h = highs[i] if i < len(highs) else None
        l = lows[i] if i < len(lows) else None
        c = closes[i] if i < len(closes) else None
        v = vols[i] if i < len(vols) else 0
        if None in (o, h, l, c):
            continue
        dt = datetime.fromtimestamp(ts, tz=IST)
        if interval_minutes:
            # Drop off-grid live tick (e.g. 10:17:23 when interval is 5m)
            if dt.second != 0 or (dt.minute % interval_minutes) != 0:
                continue
            bar_end = dt + timedelta(minutes=interval_minutes)
            if bar_end > cutoff:
                continue
            # Restrict to NSE/BSE regular equity hours 09:15 to 15:30 IST
            t = dt.time()
            if t < MARKET_OPEN or t >= MARKET_CLOSE:
                continue
        bars.append({
            "ts": ts,
            "dt": dt,
            "date": dt.date().isoformat(),
            "time": dt.strftime("%H:%M"),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": int(v or 0),
        })
    return bars
