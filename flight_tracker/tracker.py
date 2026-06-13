#!/usr/bin/env python3
"""
Thanksgiving Japan Flight Tracker
Searches Amadeus API daily and emails when deals appear.
"""
import json, os, re, smtplib, sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

# ── Secrets (GitHub Actions env vars) ────────────────────────────────────────
AMADEUS_KEY    = os.environ['AMADEUS_CLIENT_ID']
AMADEUS_SECRET = os.environ['AMADEUS_CLIENT_SECRET']
SMTP_USER      = os.environ['SMTP_FROM_EMAIL']
SMTP_PASS      = os.environ['SMTP_APP_PASSWORD']
NOTIFY_TO      = os.environ['NOTIFY_EMAIL']

AMADEUS_BASE = os.environ.get('AMADEUS_BASE_URL', 'https://api.amadeus.com')
SEEN_FILE    = os.path.join(os.path.dirname(__file__), 'seen_deals.json')

# ── Search parameters ─────────────────────────────────────────────────────────
ORIGINS   = ['PHX', 'TUS']               # Phoenix Sky Harbor, Tucson Intl
DESTS     = ['NRT', 'KIX']               # Tokyo Narita, Osaka/Kyoto Kansai
DEP_DATES = ['2026-11-21', '2026-11-22', '2026-11-23']
RET_DATES = ['2026-12-03', '2026-12-04', '2026-12-05']
TRAVELERS    = 4
MAX_PPP      = 900    # max $ per person round-trip
MAX_LEG_HRS  = 20     # max one-way total duration (incl. layovers)

DEST_LABELS = {
    'NRT': 'Tokyo (Narita — NRT)',
    'HND': 'Tokyo (Haneda — HND)',
    'KIX': 'Osaka / Kyoto (Kansai — KIX)',
}
ORIGIN_LABELS = {
    'PHX': 'Phoenix Sky Harbor (PHX)',
    'TUS': 'Tucson Intl (TUS)',
    'AZA': 'Phoenix-Mesa Gateway (AZA)',
}

# ── Amadeus auth ──────────────────────────────────────────────────────────────
_tok = {'value': None, 'exp': 0}

def get_token():
    if _tok['value'] and datetime.now().timestamp() < _tok['exp']:
        return _tok['value']
    r = requests.post(
        f'{AMADEUS_BASE}/v1/security/oauth2/token',
        data={'grant_type': 'client_credentials',
              'client_id': AMADEUS_KEY, 'client_secret': AMADEUS_SECRET},
        timeout=30,
    )
    r.raise_for_status()
    d = r.json()
    _tok['value'] = d['access_token']
    _tok['exp']   = datetime.now().timestamp() + d['expires_in'] - 60
    return _tok['value']

# ── Helpers ───────────────────────────────────────────────────────────────────
def iso_to_hours(s):
    """'PT18H30M' → 18.5"""
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?', s or '')
    if not m:
        return 0.0
    return int(m.group(1) or 0) + int(m.group(2) or 0) / 60.0

def per_person_price(offer):
    for tp in offer.get('travelerPricings', []):
        if tp.get('travelerType') == 'ADULT':
            return float(tp['price']['total'])
    return float(offer['price']['grandTotal']) / TRAVELERS

def max_leg_hours(offer):
    return max(iso_to_hours(it.get('duration')) for it in offer['itineraries'])

def leg_stops(itinerary):
    return len(itinerary['segments']) - 1

def checked_bags_included(offer):
    for tp in offer.get('travelerPricings', []):
        for seg in tp.get('fareDetailsBySegment', []):
            qty = seg.get('includedCheckedBags', {}).get('quantity', 0)
            return qty
    return 0

def deal_id(offer):
    segs_out = offer['itineraries'][0]['segments']
    segs_ret = offer['itineraries'][-1]['segments'] if len(offer['itineraries']) > 1 else []
    return '|'.join([
        segs_out[0]['departure']['iataCode'],
        segs_out[-1]['arrival']['iataCode'],
        segs_out[0]['departure']['at'][:10],
        segs_ret[0]['departure']['at'][:10] if segs_ret else '',
        offer['price']['grandTotal'],
        (offer.get('validatingAirlineCodes') or ['??'])[0],
    ])

# ── API search ────────────────────────────────────────────────────────────────
def search_flights(origin, dest, dep, ret):
    r = requests.get(
        f'{AMADEUS_BASE}/v2/shopping/flight-offers',
        headers={'Authorization': f'Bearer {get_token()}'},
        params={
            'originLocationCode':      origin,
            'destinationLocationCode': dest,
            'departureDate':           dep,
            'returnDate':              ret,
            'adults':                  TRAVELERS,
            'currencyCode':            'USD',
            'max':                     25,
        },
        timeout=30,
    )
    if r.status_code == 200:
        return r.json().get('data', [])
    print(f'  API {r.status_code}: {r.text[:200]}')
    return []

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    seen: set = set()
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            seen = set(json.load(f))

    new_deals = []

    for origin in ORIGINS:
        for dest in DESTS:
            for dep in DEP_DATES:
                for ret in RET_DATES:
                    label = f'{origin}→{dest}  {dep}/{ret}'
                    print(f'Checking {label} ...', end=' ', flush=True)
                    try:
                        offers = search_flights(origin, dest, dep, ret)
                    except Exception as e:
                        print(f'ERROR: {e}')
                        continue

                    found = 0
                    for offer in offers:
                        ppp = per_person_price(offer)
                        if ppp > MAX_PPP:
                            continue
                        if max_leg_hours(offer) > MAX_LEG_HRS:
                            continue
                        did = deal_id(offer)
                        if did in seen:
                            continue
                        seen.add(did)
                        new_deals.append({
                            'origin': origin, 'dest': dest,
                            'dep': dep, 'ret': ret,
                            'ppp': ppp, 'offer': offer,
                        })
                        found += 1
                    print(f'{found} new' if found else 'none')

    # Persist seen IDs so we don't re-alert on the same flight
    with open(SEEN_FILE, 'w') as f:
        json.dump(sorted(seen), f, indent=2)

    if new_deals:
        send_email(new_deals)
        print(f'\nAlert sent for {len(new_deals)} deal(s).')
    else:
        print('\nNo new deals found today.')

# ── Email ─────────────────────────────────────────────────────────────────────
def hm(hours):
    """18.5 → '18h 30m'"""
    h, frac = divmod(hours, 1)
    return f'{int(h)}h {int(frac*60)}m'

def send_email(deals):
    deals = sorted(deals, key=lambda d: d['ppp'])
    best  = deals[0]['ppp']

    lines = [
        f"Japan Flight Alert  —  {datetime.now().strftime('%A, %B %d, %Y')}",
        f"Found {len(deals)} new deal(s) under ${MAX_PPP}/person for your Thanksgiving trip!\n",
        '=' * 62,
    ]

    for d in deals:
        o    = d['offer']
        out  = o['itineraries'][0]
        back = o['itineraries'][1] if len(o['itineraries']) > 1 else None

        out_carriers = ', '.join(dict.fromkeys(
            s['carrierCode'] for s in out['segments']))
        out_dur   = iso_to_hours(out.get('duration', ''))
        out_stops = leg_stops(out)

        lines += [
            f"\n  ${d['ppp']:.0f}/person   |   ${float(o['price']['grandTotal']):.0f} total for {TRAVELERS} passengers",
            f"  {ORIGIN_LABELS.get(d['origin'], d['origin'])} → {DEST_LABELS.get(d['dest'], d['dest'])}",
            f"  Depart {d['dep']}   |   Return {d['ret']}",
            f"  Outbound : {hm(out_dur)}, {out_stops} stop(s), airlines: {out_carriers}",
        ]

        if back:
            back_dur   = iso_to_hours(back.get('duration', ''))
            back_stops = leg_stops(back)
            back_carr  = ', '.join(dict.fromkeys(
                s['carrierCode'] for s in back['segments']))
            lines.append(
                f"  Inbound  : {hm(back_dur)}, {back_stops} stop(s), airlines: {back_carr}")

        bags = checked_bags_included(o)
        if bags:
            lines.append(f"  Bags     : {bags} checked bag(s) INCLUDED per person")
        else:
            lines.append(
                '  Bags     : checked bags likely NOT included — confirm before booking')

    lines += [
        '\n' + '=' * 62,
        '',
        'Search & book on:',
        '  Google Flights : https://www.google.com/travel/flights',
        '  Kayak          : https://www.kayak.com',
        '  Airline website (usually cheapest — avoids OTA fees)',
        '',
        'Kyoto note: KIX is closest — 75 min by Haruka Express train.',
        'Tokyo arrivals (NRT/HND) are ~2.5 hr to Kyoto by Shinkansen.',
        '',
        'Prices are from Amadeus live inventory. Verify at checkout.',
        '',
        '— Your Thanksgiving Japan Flight Tracker',
    ]

    body = '\n'.join(lines)
    msg  = MIMEMultipart('alternative')
    msg['Subject'] = f'Japan Flight Deal: ${best:.0f}/person  ({datetime.now().strftime("%b %d")})'
    msg['From']    = SMTP_USER
    msg['To']      = NOTIFY_TO
    msg.attach(MIMEText(body, 'plain'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    print(f'Email sent to {NOTIFY_TO}')


if __name__ == '__main__':
    main()
