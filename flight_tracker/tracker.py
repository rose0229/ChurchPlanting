#!/usr/bin/env python3
"""
Thanksgiving Japan Flight Tracker — Sky Scrapper / RapidAPI edition
Searches Skyscanner data daily and emails when deals appear.
"""
import json, os, re, smtplib, time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

# ── Secrets (GitHub Actions / env vars) ──────────────────────────────────────
RAPIDAPI_KEY = os.environ['RAPIDAPI_KEY']
SMTP_USER    = os.environ['SMTP_FROM_EMAIL']
SMTP_PASS    = os.environ['SMTP_APP_PASSWORD']
NOTIFY_TO    = os.environ['NOTIFY_EMAIL']

SEEN_FILE    = os.path.join(os.path.dirname(__file__), 'seen_deals.json')
API_HOST     = 'sky-scrapper.p.rapidapi.com'
HEADERS      = {'X-RapidAPI-Key': RAPIDAPI_KEY, 'X-RapidAPI-Host': API_HOST}

# ── Airport config ─────────────────────────────────────────────────────────────
# entityId values are Skyscanner internal IDs — stable, rarely change.
# To re-verify: GET /api/v1/flights/searchAirport?query=Phoenix&locale=en-US
AIRPORTS = {
    'PHX': {'skyId': 'PHX', 'entityId': '27544922', 'label': 'Phoenix Sky Harbor'},
    'TUS': {'skyId': 'TUS', 'entityId': '27543978', 'label': 'Tucson Intl'},
    'NRT': {'skyId': 'NRT', 'entityId': '95674443', 'label': 'Tokyo Narita'},
    'KIX': {'skyId': 'KIX', 'entityId': '128669717', 'label': 'Osaka / Kyoto Kansai'},
}

ORIGINS   = ['PHX', 'TUS']
DESTS     = ['NRT', 'KIX']
DEP_DATES = ['2026-11-21', '2026-11-22', '2026-11-23']  # Sat/Sun/Mon before Thanksgiving
RET_DATES = ['2026-12-03', '2026-12-04', '2026-12-05']  # Thu/Fri/Sat of following week

TRAVELERS   = 4
MAX_PPP     = 900   # max $ per person round-trip
MAX_LEG_HRS = 20    # max hours per one-way leg (incl. layovers)


# ── Flight search ─────────────────────────────────────────────────────────────
def search_roundtrip(origin_code, dest_code, dep, ret):
    o = AIRPORTS[origin_code]
    d = AIRPORTS[dest_code]
    r = requests.get(
        f'https://{API_HOST}/api/v2/flights/searchFlightsComplete',
        headers=HEADERS,
        params={
            'originSkyId':         o['skyId'],
            'originEntityId':      o['entityId'],
            'destinationSkyId':    d['skyId'],
            'destinationEntityId': d['entityId'],
            'date':                dep,
            'returnDate':          ret,
            'cabinClass':          'economy',
            'adults':              str(TRAVELERS),
            'currency':            'USD',
            'market':              'en-US',
            'countryCode':         'US',
        },
        timeout=30,
    )
    if r.status_code != 200:
        print(f'  API {r.status_code}: {r.text[:200]}')
        return []
    payload = r.json()
    return (payload.get('data') or {}).get('itineraries', [])


def hm(minutes):
    h, m = divmod(int(minutes), 60)
    return f'{h}h {m}m'


def parse_itinerary(it, origin_code, dest_code, dep, ret):
    """Returns a deal dict or None if it doesn't meet criteria."""
    price_raw = float((it.get('price') or {}).get('raw', 0))
    if price_raw <= 0:
        return None

    ppp = price_raw / TRAVELERS
    if ppp > MAX_PPP:
        return None

    legs = it.get('legs', [])
    if not legs:
        return None

    out_leg = legs[0]
    ret_leg = legs[1] if len(legs) > 1 else None

    out_min = out_leg.get('durationInMinutes', 0)
    ret_min = ret_leg.get('durationInMinutes', 0) if ret_leg else 0

    if out_min / 60 > MAX_LEG_HRS:
        return None
    if ret_min and ret_min / 60 > MAX_LEG_HRS:
        return None

    def carrier_names(leg):
        names = [c.get('name') or c.get('id', '?')
                 for c in (leg.get('carriers') or {}).get('marketing', [])]
        return ', '.join(dict.fromkeys(names)) if names else '?'

    out_carriers = carrier_names(out_leg)
    ret_carriers = carrier_names(ret_leg) if ret_leg else None

    deal_id = '|'.join([
        origin_code, dest_code, dep, ret,
        f'{price_raw:.0f}', out_carriers,
    ])

    return {
        'ppp':          ppp,
        'total':        price_raw,
        'origin':       origin_code,
        'dest':         dest_code,
        'dep':          dep,
        'ret':          ret,
        'out_duration': hm(out_min),
        'ret_duration': hm(ret_min) if ret_min else None,
        'out_stops':    out_leg.get('stopCount', 0),
        'ret_stops':    ret_leg.get('stopCount', 0) if ret_leg else 0,
        'out_carriers': out_carriers,
        'ret_carriers': ret_carriers,
        'deal_id':      deal_id,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    seen: set = set()
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            seen = set(json.load(f))

    # Rotate through date pairs each day so every combo is checked every 9 days.
    # 4 API calls/day × 30 days ≈ 120 calls/month (within RapidAPI Basic free tier).
    cycle_len = len(DEP_DATES) * len(RET_DATES)          # 9
    cycle_day = datetime.now().timetuple().tm_yday % cycle_len
    dep_date  = DEP_DATES[cycle_day // len(RET_DATES)]
    ret_date  = RET_DATES[cycle_day % len(RET_DATES)]

    print(f'Date pair today: depart {dep_date}  /  return {ret_date}')

    new_deals = []
    for origin_code in ORIGINS:
        for dest_code in DESTS:
            print(f'  {origin_code}→{dest_code} ... ', end='', flush=True)
            time.sleep(2)
            try:
                itineraries = search_roundtrip(origin_code, dest_code, dep_date, ret_date)
            except Exception as e:
                print(f'ERROR: {e}')
                continue

            found = 0
            for it in itineraries:
                deal = parse_itinerary(it, origin_code, dest_code, dep_date, ret_date)
                if deal is None:
                    continue
                if deal['deal_id'] in seen:
                    continue
                seen.add(deal['deal_id'])
                new_deals.append(deal)
                found += 1
            print(f'{found} new' if found else 'none')

    with open(SEEN_FILE, 'w') as f:
        json.dump(sorted(seen), f, indent=2)

    if new_deals:
        send_email(new_deals)
        print(f'\nAlert sent for {len(new_deals)} deal(s).')
    else:
        print('\nNo new deals today.')


# ── Email ─────────────────────────────────────────────────────────────────────
def send_email(deals):
    deals = sorted(deals, key=lambda d: d['ppp'])
    best  = deals[0]['ppp']
    today = datetime.now().strftime('%A, %B %d, %Y')

    lines = [
        f'Japan Flight Alert  —  {today}',
        f'Found {len(deals)} new deal(s) under ${MAX_PPP}/person!\n',
        '=' * 62,
    ]

    for d in deals:
        o_label = AIRPORTS.get(d['origin'], {}).get('label', d['origin'])
        d_label = AIRPORTS.get(d['dest'],   {}).get('label', d['dest'])

        lines += [
            f"\n  ${d['ppp']:.0f}/person   |   ${d['total']:.0f} total for {TRAVELERS} people",
            f"  {o_label} → {d_label}",
            f"  Depart {d['dep']}   |   Return {d['ret']}",
            f"  Outbound : {d['out_duration']},  {d['out_stops']} stop(s),  {d['out_carriers']}",
        ]
        if d['ret_duration']:
            lines.append(
                f"  Inbound  : {d['ret_duration']},  {d['ret_stops']} stop(s)"
                + (f",  {d['ret_carriers']}" if d['ret_carriers'] else ''))

    lines += [
        '\n' + '=' * 62,
        '',
        'Book now:',
        '  Google Flights  https://www.google.com/travel/flights',
        '  Kayak           https://www.kayak.com',
        '  Airline site    (usually cheapest — avoids OTA fees)',
        '',
        'Bag tip   : Verify checked-bag policy before booking.',
        'Kyoto tip : KIX is the closest airport — 75 min by Haruka Express.',
        '            NRT/HND → Kyoto is ~2.5 hr by Shinkansen.',
        '',
        '— Thanksgiving Japan Flight Tracker',
    ]

    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"Japan Deal: ${best:.0f}/person  ({datetime.now().strftime('%b %d')})"
    msg['From']    = SMTP_USER
    msg['To']      = NOTIFY_TO
    msg.attach(MIMEText('\n'.join(lines), 'plain'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    print(f'Email sent to {NOTIFY_TO}')


if __name__ == '__main__':
    main()
