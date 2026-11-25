# Exact-Time Cloud Alerts (`cron-job.org` → GitHub Actions → Telegram)

GitHub's built-in `on: schedule` cron can lag by 1–10+ hours, while GitHub's `workflow_dispatch` API runs in **~9 seconds flat**.
Using free **cron-job.org** to hit `workflow_dispatch` gives you **exact-to-the-second IST Telegram alerts**, 100% free, even when your laptop is shut down.

---

## Step 1: Create a Fine-Grained GitHub Token (30 sec)
1. Open: `https://github.com/settings/personal-access-tokens/new`
2. **Token name:** `cronjob-nse-alerts`
3. **Expiration:** `90 days` (or `1 year`)
4. **Repository access:** `Only select repositories` → pick **`Vrajm12/india-day-trader`**
5. **Permissions → Repository permissions → Actions:** **`Read and write`** *(leave everything else No access)*
6. Click **Generate token** and copy the `github_pat_...` token.

---

## Step 2: Create 4 Exact-Time Jobs on `cron-job.org` (2 min)
Sign up free at **`https://cron-job.org`** → click **Create Cronjob** 4 times using these exact values:

### Common Settings (Same for All 4 Jobs)
- **URL:**
  ```text
  https://api.github.com/repos/Vrajm12/india-day-trader/actions/workflows/nse-morning-alert.yml/dispatches
  ```
- **Timezone:** `Asia/Kolkata` *(IST — no UTC conversion needed!)*
- **Execution days:** Monday–Friday (`Mon, Tue, Wed, Thu, Fri`)
- **Advanced tab → Request method:** `POST`
- **Advanced tab → Headers** (add 3 headers):
  - `Authorization`: `Bearer github_pat_YOUR_TOKEN_HERE`
  - `Accept`: `application/vnd.github+json`
  - `Content-Type`: `application/json`

### The 4 Exact Times & Request Bodies (Advanced tab → Request body)
| Job Title | Time (IST, Mon–Fri) | Request Body (JSON) |
| --- | --- | --- |
| `NSE 08:58 Pre-Market` | `08:58` | `{"ref":"main","inputs":{"mode":"premarket"}}` |
| `NSE 09:42 ORB Brief` | `09:42` | `{"ref":"main","inputs":{"mode":"orb"}}` |
| `NSE 15:03 Square-Off` | `15:03` | `{"ref":"main","inputs":{"mode":"close_reminder"}}` |
| `NSE 15:35 Day-End Wrap` | `15:35` | `{"ref":"main","inputs":{"mode":"day_end"}}` |

*(NSE/BSE holidays are skipped automatically inside `scripts/morning_brief.py`.)*

---

## Step 3: Test Immediately (5 sec)
Click **TEST RUN** on any job in `cron-job.org` → you should see **HTTP `204 No Content`** and your Telegram bot will ping within ~10 seconds!
