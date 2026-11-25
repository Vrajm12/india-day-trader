/**
 * Cloudflare Worker: NSE Rs 500 Rotation Telegram Alerts (Exact-Second IST Cron)
 *
 * Schedules (UTC -> IST, Mon-Fri):
 *   28 3 * * 1-5  -> 08:58 IST (premarket)
 *   12 4 * * 1-5  -> 09:42 IST (orb — post-chaos breakout brief for 09:50 review)
 *   33 9 * * 1-5  -> 15:03 IST (close_reminder — MIS square-off before 15:10)
 *   5 10 * * 1-5  -> 15:35 IST (day_end — post-close wrap)
 *
 * Required Worker Secrets (set in Cloudflare Dashboard -> Worker -> Settings -> Variables & Secrets):
 *   TELEGRAM_BOT_TOKEN
 *   TELEGRAM_CHAT_ID
 */

const WATCHLIST = [
  "SUZLON.NS",
  "IOC.NS",
  "PNB.NS",
  "TATASTEEL.NS",
  "ONGC.NS",
  "VEDL.NS",
  "POWERGRID.NS",
  "BANKBARODA.NS",
  "ITC.NS",
  "ETERNAL.NS",
];

// Official 2026 NSE/BSE Equity Holidays + 2027 major fixed national holidays
const NSE_HOLIDAYS = {
  "2026-01-26": "Republic Day",
  "2026-03-03": "Holi",
  "2026-03-26": "Shri Ram Navami",
  "2026-03-31": "Shri Mahavir Jayanti",
  "2026-04-03": "Good Friday",
  "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
  "2026-05-01": "Maharashtra Day",
  "2026-05-28": "Bakri Id",
  "2026-06-26": "Muharram",
  "2026-09-14": "Ganesh Chaturthi",
  "2026-10-02": "Mahatma Gandhi Jayanti",
  "2026-10-20": "Dussehra",
  "2026-11-10": "Diwali-Balipratipada",
  "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
  "2026-12-25": "Christmas",
  "2027-01-26": "Republic Day",
  "2027-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
  "2027-05-01": "Maharashtra Day",
  "2027-08-15": "Independence Day",
  "2027-10-02": "Mahatma Gandhi Jayanti",
  "2027-12-25": "Christmas",
};

const CRON_TO_MODE = {
  "28 3 * * 1-5": "premarket",
  "12 4 * * 1-5": "orb",
  "33 9 * * 1-5": "close_reminder",
  "5 10 * * 1-5": "day_end",
};

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
const NUM_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function getIstParts(dateObj = new Date()) {
  const istMs = dateObj.getTime() + 5.5 * 3600 * 1000;
  const d = new Date(istMs);
  const year = d.getUTCFullYear();
  const month = d.getUTCMonth();
  const day = d.getUTCDate();
  const dow = d.getUTCDay();
  const hour = d.getUTCHours();
  const minute = d.getUTCMinutes();
  const pad = (n) => String(n).padStart(2, "0");
  return {
    year,
    month,
    day,
    dow,
    hour,
    minute,
    dateStr: `${year}-${pad(month + 1)}-${pad(day)}`,
    hhmm: `${pad(hour)}:${pad(minute)}`,
    shortDate: `${DAYS[dow]}, ${pad(day)} ${MONTHS[month]}`,
    fullDate: `${DAYS[dow]}, ${pad(day)} ${MONTHS[month]} ${year}`,
    dayMon: `${pad(day)} ${MONTHS[month]}`,
    minutesOfDay: hour * 60 + minute,
  };
}

function escapeHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function padR(s, w) {
  return String(s).padEnd(w, " ");
}

function padL(s, w) {
  return String(s).padStart(w, " ");
}

function fmtSigned(n, dec = 2) {
  return `${n >= 0 ? "+" : ""}${n.toFixed(dec)}`;
}

function roundTick(px) {
  return Math.round(px * 20) / 20;
}

async function fetchYahooChart(symbol, rangeStr, interval) {
  const hosts = ["query2.finance.yahoo.com", "query1.finance.yahoo.com"];
  let lastErr = null;
  for (const host of hosts) {
    const url = `https://${host}/v8/finance/chart/${encodeURIComponent(symbol)}?range=${rangeStr}&interval=${interval}&includePrePost=false`;
    try {
      const resp = await fetch(url, { headers: { "User-Agent": UA, Accept: "application/json" } });
      if (!resp.ok) {
        lastErr = new Error(`Yahoo HTTP ${resp.status} for ${symbol}`);
        continue;
      }
      const data = await resp.json();
      const res = data?.chart?.result?.[0];
      if (!res) {
        lastErr = new Error(`Empty chart for ${symbol}`);
        continue;
      }
      return res;
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error(`Yahoo fetch failed for ${symbol}`);
}

function parse5mBars(chart, sessionDate, cutoffMinutes) {
  const ts = chart.timestamp || [];
  const q = chart.indicators?.quote?.[0] || {};
  const opens = q.open || [];
  const highs = q.high || [];
  const lows = q.low || [];
  const closes = q.close || [];
  const bars = [];
  for (let i = 0; i < ts.length; i++) {
    if (ts[i] == null || opens[i] == null || highs[i] == null || lows[i] == null || closes[i] == null) continue;
    const p = getIstParts(new Date(ts[i] * 1000));
    if (p.dateStr !== sessionDate) continue;
    if (p.minute % 5 !== 0) continue;
    if (p.minutesOfDay < 9 * 60 + 15 || p.minutesOfDay >= 15 * 60 + 30) continue;
    if (p.minutesOfDay + 5 > cutoffMinutes) continue;
    bars.push({
      time: p.hhmm,
      minutesOfDay: p.minutesOfDay,
      open: Number(opens[i]),
      high: Number(highs[i]),
      low: Number(lows[i]),
      close: Number(closes[i]),
    });
  }
  return bars;
}

function best500Combo(candidates, budget = 500) {
  let best = [];
  let bestScore = -1e9;
  for (let i = 0; i < candidates.length; i++) {
    for (let j = i + 1; j < candidates.length; j++) {
      const a = candidates[i];
      const b = candidates[j];
      if (a.live + b.live <= budget) {
        const sc = a.chg + b.chg;
        if (sc > bestScore) {
          bestScore = sc;
          best = [a, b];
        }
      }
    }
  }
  if (best.length) return best;
  for (const c of candidates) {
    if (c.live <= budget) return [c];
  }
  return [];
}

async function buildPremarket(ist) {
  const results = await Promise.all(
    WATCHLIST.map(async (sym) => {
      try {
        const ch = await fetchYahooChart(sym, "1mo", "1d");
        const closes = (ch.indicators?.quote?.[0]?.close || []).filter((x) => x != null).map(Number);
        if (closes.length < 2) return null;
        const lastC = closes[closes.length - 1];
        const prevC = closes[closes.length - 2];
        const chg = prevC ? ((lastC - prevC) / prevC) * 100 : 0;
        const slice = closes.slice(-20);
        const ma20 = slice.reduce((a, b) => a + b, 0) / slice.length;
        return { sym: sym.replace(".NS", ""), px: lastC, chg, above: lastC > ma20 };
      } catch {
        return null;
      }
    })
  );
  const rows = results.filter(Boolean).sort((a, b) => b.chg - a.chg);
  const above = rows.filter((r) => r.above);
  const below = rows.filter((r) => !r.above);

  const tLines = ["STOCK        PREV    CHG%   20MA", "---------------------------------"];
  for (const r of rows) {
    const tag = r.above ? "UP  " : "DOWN";
    tLines.push(`${padR(r.sym, 10)} ${padL(r.px.toFixed(2), 6)} ${padL(fmtSigned(r.chg, 2) + "%", 7)}  ${tag}`);
  }

  const pro = [
    "🌅 <b>NSE ₹500 Challenge — Pre-Market</b>",
    `🗓 <code>${ist.fullDate} • ${ist.hhmm} IST</code>`,
    `<pre>${escapeHtml(tLines.join("\n"))}</pre>`,
    `🟢 Above 20MA: <b>${above.length}</b>  |  🔴 Below 20MA: <b>${below.length}</b>`,
    "⏳ <i>Next auto-alert at 09:42 IST sharp (after morning chaos settles).</i>",
  ].join("\n");

  const topNames = above.slice(0, 3).map((r) => `<b>${r.sym}</b> (<code>₹${r.px.toFixed(0)}</code>)`).join(", ") || "koi nahi";
  const bro = [
    `Yo Veeraj! ☕ Good morning (${ist.dayMon})`,
    "",
    `Aaj subah apni 10 stocks list mein <b>${above.length}</b> up-trend mein hain aur <b>${below.length}</b> neeche.`,
    `Sabse strong abhi: ${topNames}`,
    "",
    "Abhi <code>09:15–09:42</code> wala subah ka chaos settle hone de — <code>09:42 IST</code> sharp pe exact setups aur Entry / Stop / Target bhejunga. Tab aaja chat pe! 👋",
  ].join("\n");

  return [pro, bro];
}

async function buildOrb(ist) {
  const results = await Promise.all(
    WATCHLIST.map(async (sym) => {
      try {
        const ch = await fetchYahooChart(sym, "1d", "5m");
        const meta = ch.meta || {};
        const prevClose = Number(meta.chartPreviousClose || meta.previousClose || 0);
        const bars = parse5mBars(ch, ist.dateStr, ist.minutesOfDay);
        const orBars = bars.filter((b) => b.minutesOfDay < 9 * 60 + 30);
        const afterBars = bars.filter((b) => b.minutesOfDay >= 9 * 60 + 30);
        if (orBars.length < 3) return null;
        const live = Number(meta.regularMarketPrice || bars[bars.length - 1].close);
        const orHi = Math.max(...orBars.map((b) => b.high));
        const orLo = Math.min(...orBars.map((b) => b.low));
        const chg = prevClose ? ((live - prevClose) / prevClose) * 100 : 0;
        const hitBar = afterBars.find((b) => b.close > orHi) || null;

        if (hitBar) {
          const entry = hitBar.close;
          const stop = roundTick((orHi + orLo) / 2);
          const risk = Math.max(0.05, Number((entry - stop).toFixed(2)));
          const target = roundTick(entry + 1.5 * risk);
          const hitMin = hitBar.minutesOfDay + 5;
          const hitTime = `${String(Math.floor(hitMin / 60)).padStart(2, "0")}:${String(hitMin % 60).padStart(2, "0")}`;
          const item = {
            sym: sym.replace(".NS", ""),
            live,
            chg,
            entry,
            stop,
            target,
            orHi,
            orLo,
            hitTime,
            alreadyHitTarget: live >= target,
            kind: live > orHi && chg >= 0 ? "strong" : "faded",
          };
          return item;
        }
        return {
          sym: sym.replace(".NS", ""),
          live,
          chg,
          orHi,
          orLo,
          kind: live >= orHi * 0.994 ? "near" : "weak",
        };
      } catch {
        return null;
      }
    })
  );

  const items = results.filter(Boolean);
  const strong = items.filter((x) => x.kind === "strong").sort((a, b) => b.chg - a.chg);
  const faded = items.filter((x) => x.kind === "faded").sort((a, b) => b.chg - a.chg);
  const near = items.filter((x) => x.kind === "near").sort((a, b) => b.chg - a.chg);
  const weak = items.filter((x) => x.kind === "weak").sort((a, b) => b.chg - a.chg);

  const lines = [
    "📊 <b>NSE ₹500 Challenge — Post-Chaos Brief</b>",
    `🗓 <code>${ist.shortDate} • ${ist.hhmm} IST</code>  |  OR <code>09:15–09:30</code>`,
  ];

  if (strong.length) {
    lines.push(`\n🟢 <b>CLEAN BREAKOUTS — GREEN (${strong.length})</b>`);
    const tLines = ["STOCK       LIVE    STOP    1.5R", "----------------------------------"];
    let anyChased = false;
    for (const t of strong) {
      const star = t.alreadyHitTarget ? "*" : " ";
      if (t.alreadyHitTarget) anyChased = true;
      tLines.push(`${padR(t.sym, 10)} ${padL(t.live.toFixed(2), 6)}  ${padL(t.stop.toFixed(2), 6)}  ${padL(t.target.toFixed(2), 6)}${star}`);
    }
    lines.push(`<pre>${escapeHtml(tLines.join("\n"))}</pre>`);
    if (anyChased) lines.push("<i>* already past 1.5R target — don't chase</i>");
    const actionable = strong.filter((t) => !t.alreadyHitTarget);
    const combo = best500Combo(actionable.length ? actionable : strong, 500);
    if (combo.length) {
      const totalCost = combo.reduce((s, x) => s + x.live, 0);
      const comboStr = combo.map((x) => `<b>1 ${x.sym}</b> (<code>₹${x.live.toFixed(0)}</code>)`).join(" + ");
      lines.push(`💰 <b>Top ₹500 Fit:</b> ${comboStr} = <code>₹${totalCost.toFixed(2)}</code>`);
    }
  } else {
    lines.push("\n🟢 <b>CLEAN BREAKOUTS:</b> None holding green above range yet.");
  }

  const others = [
    ...faded.map((t) => ({ sym: t.sym, live: t.live, chg: t.chg, st: "FADED" })),
    ...near.map((t) => ({ sym: t.sym, live: t.live, chg: t.chg, st: `>${t.orHi.toFixed(1)}` })),
    ...weak.map((t) => ({ sym: t.sym, live: t.live, chg: t.chg, st: "WEAK" })),
  ];
  if (others.length) {
    lines.push("\n📋 <b>OTHER STOCKS</b>");
    const oLines = ["STOCK       LIVE    CHG%   STATUS", "----------------------------------"];
    for (const o of others) {
      oLines.push(`${padR(o.sym, 10)} ${padL(o.live.toFixed(2), 6)} ${padL(fmtSigned(o.chg, 1) + "%", 7)}  ${o.st}`);
    }
    lines.push(`<pre>${escapeHtml(oLines.join("\n"))}</pre>`);
  }
  lines.push("⚠️ <i>MIS 1x • Max 2 ≤ ₹500 • Exit by 15:10 IST</i>");

  const greens = items.filter((x) => x.chg >= 0).sort((a, b) => b.chg - a.chg);
  const reds = items.filter((x) => x.chg < 0).sort((a, b) => a.chg - b.chg);
  const broLines = [
    `Yo Veeraj! 👋 Subah ka chaos settle ho gaya (${ist.hhmm} IST) — chal aaj ka scene dekh:\n`,
    "📋 <b>Aaj ki 10 stocks list:</b>",
    "🟢 Green: " + (greens.map((x) => `${x.sym} (${fmtSigned(x.chg, 1)}%)`).join(", ") || "koi nahi"),
    "🔴 Red: " + (reds.map((x) => `${x.sym} (${fmtSigned(x.chg, 1)}%)`).join(", ") || "koi nahi") + "\n",
  ];
  if (strong.length) {
    const actionable = strong.filter((t) => !t.alreadyHitTarget);
    const picks = best500Combo(actionable.length ? actionable : strong, 500);
    if (picks.length) {
      const tot = picks.reduce((s, p) => s + p.live, 0);
      broLines.push(`🎯 <b>₹500 ke hisaab se ye ${picks.length} setups sabse clean lag rahe hain (1x MIS):</b>\n`);
      picks.forEach((p, idx) => {
        const chase = p.alreadyHitTarget ? "\n   ⚡ <i>Note: Ye already 1.5R paar kar gaya, chase mat karna!</i>" : "";
        broLines.push(
          `${NUM_EMOJI[idx]} <b>${p.sym}</b> (abhi <code>₹${p.live.toFixed(2)}</code>, ${fmtSigned(p.chg, 2)}%)\n` +
            `   • Entry: <code>~₹${p.entry.toFixed(2)}</code> (${p.hitTime} pe breakout)\n` +
            `   • Stop-loss: <code>₹${p.stop.toFixed(2)}</code>\n` +
            `   • Target (1.5R): <code>₹${p.target.toFixed(2)}</code>${chase}\n`
        );
      });
      broLines.push(`💵 Dono ka total: <code>₹${tot.toFixed(2)}</code> (₹500 ke andar fit!)\n`);
    }
  } else {
    broLines.push("😴 Abhi tak koi clean green breakout nahi aaya — jabardasti trade nahi lena, thoda wait karte hain!\n");
  }
  broLines.push("⚠️ <i>Sirf data &amp; math hai — order lene se pehle Time Machine check zaroor karenge.</i>");
  broLines.push("💬 <b>Aaja Antigravity chat pe — dono ko check karke 9:50 pe final call lete hain!</b> 🚀");

  return [lines.join("\n"), broLines.join("\n")];
}

function buildCloseReminder(ist) {
  const pro = [
    `🚨 <b>MIS SQUARE-OFF REMINDER — <code>${ist.hhmm} IST</code></b>`,
    "━━━━━━━━━━━━━━━━━━━━",
    "",
    "📱 Open <b>Paytm Money → Positions</b> RIGHT NOW:",
    "",
    "• Square off ANY open <b>Intraday (MIS)</b> position before <code>15:10 IST</code>.",
    "• Avoid the <code>₹59</code> (₹50 + GST) broker auto-square-off penalty at <code>15:15</code>.",
    "• Log today's net P&amp;L in <code>challenge_ledger.md</code>.",
  ].join("\n");

  const bro = [
    `Oye bhai! ⏰ <code>${ist.hhmm} IST</code> baj gaye!`,
    "",
    "Paytm Money khol ke check kar — koi bhi Intraday (MIS) position open ho toh <b>3:10 PM se pehle exit maar de</b>, warna ₹59 penalty lag jaayegi.",
    "",
    "💬 Exit karke chat pe aaja — aaj ka profit/loss ledger mein update karte hain!",
  ].join("\n");

  return [pro, bro];
}

async function buildDayEnd(ist) {
  const results = await Promise.all(
    WATCHLIST.map(async (sym) => {
      try {
        const ch = await fetchYahooChart(sym, "1d", "5m");
        const meta = ch.meta || {};
        const close = Number(meta.regularMarketPrice || 0);
        const prev = Number(meta.chartPreviousClose || meta.previousClose || 0);
        const hi = Number(meta.regularMarketDayHigh || close);
        const lo = Number(meta.regularMarketDayLow || close);
        const chg = prev ? ((close - prev) / prev) * 100 : 0;
        const rng = lo ? ((hi - lo) / lo) * 100 : 0;
        return { sym: sym.replace(".NS", ""), close, chg, rng };
      } catch {
        return null;
      }
    })
  );
  const rows = results.filter(Boolean).sort((a, b) => b.chg - a.chg);
  const greens = rows.filter((r) => r.chg >= 0);
  const reds = rows.filter((r) => r.chg < 0);

  const tLines = ["STOCK       CLOSE    CHG%   RNG", "---------------------------------"];
  for (const r of rows) {
    tLines.push(`${padR(r.sym, 10)} ${padL(r.close.toFixed(2), 6)} ${padL(fmtSigned(r.chg, 2) + "%", 7)}  ${padL(r.rng.toFixed(1) + "%", 4)}`);
  }

  const pro = [
    "🏁 <b>NSE ₹500 Challenge — Day-End Wrap</b>",
    `🗓 <code>${ist.fullDate} • Market Closed</code>`,
    `<pre>${escapeHtml(tLines.join("\n"))}</pre>`,
    `🟢 Green: <b>${greens.length}</b>  |  🔴 Red: <b>${reds.length}</b>`,
    "📒 <i>Update today's trade &amp; lesson in challenge_ledger.md.</i>",
  ].join("\n");

  const top = rows[0];
  const bot = rows[rows.length - 1];
  const topStr = top ? `<b>${top.sym}</b> (${fmtSigned(top.chg, 2)}%, ₹${top.close.toFixed(2)})` : "-";
  const botStr = bot ? `<b>${bot.sym}</b> (${fmtSigned(bot.chg, 2)}%, ₹${bot.close.toFixed(2)})` : "-";
  const bro = [
    `Market band bhai! 🏁 (${ist.shortDate})`,
    "",
    `Aaj apni 10 stocks list mein <b>${greens.length} green</b> aur <b>${reds.length} red</b> band hue:`,
    `🏆 Best mover: ${topStr}`,
    `📉 Weakest: ${botStr}`,
    "",
    "Aaj jo bhi trade liya (ya skip kiya), chat pe aake ledger mein note kar lete hain — phir chill kar, kal fresh dekhenge! 😎",
  ].join("\n");

  return [pro, bro];
}

async function sendTelegram(env, htmlBody) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) {
    throw new Error("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID secret in Cloudflare Worker");
  }
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  const body = JSON.stringify({
    chat_id: env.TELEGRAM_CHAT_ID,
    text: htmlBody,
    parse_mode: "HTML",
    disable_web_page_preview: true,
  });
  let lastErr = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
      if (resp.ok) return true;
      const errText = await resp.text();
      if (resp.status >= 500 || resp.status === 429) {
        lastErr = new Error(`Telegram HTTP ${resp.status}: ${errText}`);
        await new Promise((r) => setTimeout(r, 1500 * (attempt + 1)));
        continue;
      }
      throw new Error(`Telegram HTTP ${resp.status}: ${errText}`);
    } catch (e) {
      lastErr = e;
      await new Promise((r) => setTimeout(r, 1500 * (attempt + 1)));
    }
  }
  throw lastErr;
}

async function runMode(mode, env, forceHoliday = false) {
  const ist = getIstParts(new Date());
  if (!forceHoliday && (ist.dow === 0 || ist.dow === 6 || NSE_HOLIDAYS[ist.dateStr])) {
    const reason = NSE_HOLIDAYS[ist.dateStr] || DAYS[ist.dow];
    console.log(JSON.stringify({ event: "skipped_holiday", date: ist.dateStr, reason, mode }));
    return { skipped: true, reason, date: ist.dateStr };
  }

  let messages;
  if (mode === "premarket") messages = await buildPremarket(ist);
  else if (mode === "orb") messages = await buildOrb(ist);
  else if (mode === "close_reminder") messages = buildCloseReminder(ist);
  else messages = await buildDayEnd(ist);

  for (const msg of messages) {
    await sendTelegram(env, msg);
  }
  console.log(JSON.stringify({ event: "sent", mode, ist: `${ist.dateStr} ${ist.hhmm}`, count: messages.length }));
  return { skipped: false, mode, ist: `${ist.dateStr} ${ist.hhmm}`, sent: messages.length };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const ist = getIstParts(new Date());
    if (url.pathname === "/health" || url.pathname === "/") {
      return Response.json({
        status: "ok",
        worker: "nse-500-alerts",
        now_ist: `${ist.dateStr} ${ist.hhmm} IST`,
        trading_day: !(ist.dow === 0 || ist.dow === 6 || NSE_HOLIDAYS[ist.dateStr]),
        secrets_configured: Boolean(env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_CHAT_ID),
        schedules_ist: ["08:58 premarket", "09:42 orb", "15:03 close_reminder", "15:35 day_end"],
      });
    }
    return new Response("Not Found", { status: 404 });
  },

  async scheduled(controller, env, ctx) {
    const mode = CRON_TO_MODE[controller.cron] || "day_end";
    ctx.waitUntil(runMode(mode, env, false));
  },
};
