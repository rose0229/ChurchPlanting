# Thanksgiving Japan Flight Tracker

Runs every morning via GitHub Actions. Searches Amadeus live flight inventory
for Phoenix/Tucson → Tokyo/Osaka deals and emails you when prices drop under
your target.

## Search criteria

| Setting | Value |
|---|---|
| Origins | PHX (Phoenix Sky Harbor), TUS (Tucson) |
| Destinations | NRT (Tokyo Narita), KIX (Osaka/Kyoto Kansai) |
| Departure window | Nov 21–23, 2026 |
| Return window | Dec 3–5, 2026 |
| Travelers | 4 adults |
| Max price | $900/person round-trip |
| Max flight time | 20 hours per leg (incl. layovers) |

**Kyoto note:** No airport is in Kyoto. KIX (Osaka Kansai) is closest — 75 min
by the Haruka Express train. NRT/HND (Tokyo) is ~2.5 hr to Kyoto by Shinkansen.

---

## One-time setup

### 1. Get free Amadeus API credentials

1. Sign up at **https://developers.amadeus.com** (free)
2. Go to **My Apps → Create new app**
3. Under the app, click **Request production access** (self-service, usually approved instantly)
4. Copy your **API Key (Client ID)** and **API Secret (Client Secret)**

> The test environment (`test.api.amadeus.com`) returns synthetic data that
> doesn't reflect real prices. You need production credentials for real results.

### 2. Create a Gmail App Password

Your script sends alerts via Gmail SMTP. It needs an App Password — **not** your
regular Gmail password.

1. Go to **myaccount.google.com → Security → 2-Step Verification** (must be on)
2. Scroll to the bottom → **App passwords**
3. Name it "Flight Tracker", click **Create**
4. Copy the 16-character password — you'll only see it once

### 3. Add GitHub Secrets

In this repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `AMADEUS_CLIENT_ID` | Amadeus API Key (production) |
| `AMADEUS_CLIENT_SECRET` | Amadeus API Secret (production) |
| `SMTP_FROM_EMAIL` | Gmail address to send from |
| `SMTP_APP_PASSWORD` | 16-character Gmail App Password |
| `NOTIFY_EMAIL` | Email address to receive alerts |

### 4. Enable and test the workflow

1. Go to the **Actions** tab in this repo
2. Click **Thanksgiving Japan Flight Tracker**
3. Click **Run workflow** → **Run workflow** to trigger a manual test run
4. Check the run logs — you'll see each route being searched
5. Check your inbox for an alert (only sent when new deals are found)

---

## Schedule

Runs daily at **2 PM UTC** (7 AM Phoenix time in winter, 8 AM in summer).

## How deduplication works

`seen_deals.json` tracks flight IDs (route + dates + price + carrier) that have
already triggered an alert. It's committed back to the repo after each run. You'll
only get an email when a new deal appears that you haven't been notified about before.

To reset and re-alert on all current deals, clear `seen_deals.json` to `[]` and push.

## Going.com

Going (formerly Scott's Cheap Flights) doesn't expose an API to subscribers —
their team curates deals manually and delivers them via email. Keep your Going
alerts running separately; this tool gives you daily independent coverage via
the Amadeus flight inventory API.

## Adjusting search parameters

Edit the constants at the top of `flight_tracker/tracker.py`:

```python
ORIGINS   = ['PHX', 'TUS']
DESTS     = ['NRT', 'KIX']
DEP_DATES = ['2026-11-21', '2026-11-22', '2026-11-23']
RET_DATES = ['2026-12-03', '2026-12-04', '2026-12-05']
TRAVELERS = 4
MAX_PPP   = 900
```

> **API limit note:** The Amadeus free tier allows ~2,000 calls/month. The
> current config runs 36 searches/day (2 origins × 2 dests × 3 dep × 3 ret),
> using ~1,080 calls/month — well within the limit. Expanding the search
> (more airports, more dates) may exceed the free tier.
