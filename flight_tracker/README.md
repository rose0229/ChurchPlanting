# Thanksgiving Japan Flight Tracker

Runs every morning via GitHub Actions. Searches live Skyscanner data (via
Sky Scrapper on RapidAPI) for Phoenix/Tucson → Tokyo/Osaka deals and emails
you when prices drop under your target.

## Search criteria

| Setting | Value |
|---|---|
| Origins | PHX (Phoenix Sky Harbor), TUS (Tucson) |
| Destinations | NRT (Tokyo Narita), KIX (Osaka/Kyoto Kansai) |
| Departure window | Nov 21–23, 2026 |
| Return window | Dec 3–5, 2026 |
| Travelers | 4 adults |
| Max price | $900/person round-trip |
| Max flight time | 20 hours per one-way leg |

**Kyoto note:** KIX (Osaka Kansai) is closest — 75 min by Haruka Express train.
NRT/HND (Tokyo) is ~2.5 hr to Kyoto by Shinkansen.

---

## One-time setup

### 1. Get a free RapidAPI key

1. Go to **rapidapi.com** and click **Sign Up** (use your Google account — 30 seconds)
2. Search for **"Sky Scrapper"** (by apiheya) in the API Hub
3. Click **Subscribe to Test** on the Basic (free) plan
4. Your API key appears under **Apps → Default App → Authorization**
5. Copy the key

> The Basic free plan covers ~500 requests/month. This tracker uses ~120/month
> (4 searches/day). You can check the exact limit on the Sky Scrapper pricing page.

### 2. Create a Gmail App Password

The script sends alerts via Gmail SMTP — it needs an App Password, not your
regular password.

1. Go to **myaccount.google.com → Security → 2-Step Verification** (must be on)
2. Scroll to **App passwords** at the bottom
3. Name it "Flight Tracker" → click **Create**
4. Copy the 16-character password (shown only once)

### 3. Add GitHub Secrets

In this repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `RAPIDAPI_KEY` | Your RapidAPI key from step 1 |
| `SMTP_FROM_EMAIL` | Gmail address to send from |
| `SMTP_APP_PASSWORD` | 16-character App Password from step 2 |
| `NOTIFY_EMAIL` | Email address to receive alerts |

### 4. Enable and test

1. Go to **Actions** tab in this repo
2. Click **Thanksgiving Japan Flight Tracker**
3. Click **Run workflow** to trigger a manual test run immediately
4. Check the run logs — you'll see each route being searched
5. An email is only sent when new deals are found, so no email on a dry run is normal

---

## How it works

Each day the tracker searches all 4 routes (PHX/TUS → NRT/KIX) against one
departure/return date pair. The date pair rotates through all 9 combinations
(3 departure × 3 return dates) over a 9-day cycle — meaning every specific
date combination gets checked roughly every 9 days.

This keeps API usage at ~4 calls/day (~120/month), well within the free tier.

`seen_deals.json` tracks which deals have already triggered an alert (by
route + dates + price + carrier). It's committed back to the repo after each
run. To reset and re-alert on all current deals, clear the file to `[]` and push.

## Going.com

Going (formerly Scott's Cheap Flights) doesn't expose an API to subscribers —
deals come via email from their team. Keep your Going alerts running separately;
this tracker supplements them with independent daily API searches.

## Adjusting parameters

Edit the constants at the top of `flight_tracker/tracker.py`:

```python
ORIGINS   = ['PHX', 'TUS']
DESTS     = ['NRT', 'KIX']
DEP_DATES = ['2026-11-21', '2026-11-22', '2026-11-23']
RET_DATES = ['2026-12-03', '2026-12-04', '2026-12-05']
TRAVELERS = 4
MAX_PPP   = 900
```
