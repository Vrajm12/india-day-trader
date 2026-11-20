# Cloud Automation Setup (GitHub Actions → WhatsApp / Phone Push / Email)

Runs **100% FREE on GitHub's cloud servers** — works even when your laptop is **shut down / offline**.
Automatically skips weekends and official 2026/2027 NSE/BSE holidays (including Tuesday, 24 Nov 2026 Guru Nanak Jayanti).

## Schedule (Mon–Fri, IST)
- **09:00 IST:** Pre-market snapshot of your 10-stock rotation list (`trader/rotation_watchlist.txt`)
- **~09:45 IST** *(triggered `09:40 IST`)*: **Post-chaos ORB brief** (after `09:15–09:30` opening chaos settles) with `or-mid` stop & `1.5R` target previews — lands right before your `09:50 IST` entry review
- **15:05 IST:** Intraday (`MIS`) square-off reminder (before `15:10 IST` flat-by / `15:15` broker penalty)

---

## Add Your Phone Notification Secrets on GitHub

Open your repo → **Settings → Secrets and variables → Actions → New repository secret** and add any **one or more** channels below (all configured channels fire together):

### Option 1 — **WhatsApp (CallMeBot — FREE, 30-second setup)**
1. Save the CallMeBot WhatsApp number **`+34 644 71 98 38`** in your phone contacts (verify latest official number on `callmebot.com/blog/free-api-whatsapp-messages/`).
2. Send this exact WhatsApp message to it:
   `I allow callmebot to send me messages`
3. CallMeBot will reply in ~30 seconds with your personal **API Key**.
4. Add 2 GitHub Repository Secrets:
   - `WHATSAPP_PHONE`: your number with India country code, no `+` or spaces (e.g., `9198XXXXXXXX`)
   - `WHATSAPP_CALLMEBOT_KEY`: the API key CallMeBot sent you

> **Tip:** CallMeBot is a free community relay and can occasionally pause/rate-limit. Adding **ntfy** (Option 2) or **Gmail** (Option 3) as a backup takes 30 seconds and guarantees you never miss a `09:45 IST` alert!

### Option 2 — **ntfy.sh Phone Push (FREE, Instant Backup)**
1. Install the free **ntfy** app on Android (Play Store) or iPhone (App Store).
2. Open ntfy → tap **`+`** → subscribe to a unique secret topic name (e.g., `veeraj-nse-500-x9k2p`).
3. Add 1 GitHub Secret:
   - `NTFY_TOPIC`: `veeraj-nse-500-x9k2p`

### Option 3 — **Gmail Email (FREE)**
1. Enable 2-Step Verification on Google → create a 16-char **App Password** (`myaccount.google.com/apppasswords`).
2. Add GitHub Secrets:
   - `GMAIL_USER`: your Gmail address
   - `GMAIL_APP_PASSWORD`: the 16-character App Password
   - `ALERT_TO_EMAIL`: *(optional)* destination email (defaults to `GMAIL_USER`)

### Option 4 — **Telegram Bot (FREE)**
1. Message `@BotFather` → `/newbot` → copy bot token.
2. Message your new bot once, then get your chat ID at `https://api.telegram.org/bot<TOKEN>/getUpdates`.
3. Add GitHub Secrets: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

---

## Test Right Now (1 Click)
Go to **GitHub → Actions → NSE Rs 500 Rotation Phone Alerts → Run workflow** → pick `orb` or `premarket` → click **Run workflow**. Your WhatsApp / phone will buzz within ~15–20 seconds!
