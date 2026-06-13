#!/usr/bin/env python3
"""
Orbit Church Sermon Sync
Detects new Sunday YouTube uploads, uses Claude to format content for
The Church Co, and emails a ready-to-paste draft.
"""
import json, os, smtplib, sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import anthropic
import requests

# ── Secrets ───────────────────────────────────────────────────────────────────
YOUTUBE_KEY   = os.environ['YOUTUBE_API_KEY']
ANTHROPIC_KEY = os.environ['ANTHROPIC_API_KEY']
SMTP_USER     = os.environ['SMTP_FROM_EMAIL']
SMTP_PASS     = os.environ['SMTP_APP_PASSWORD']
NOTIFY_TO     = os.environ['NOTIFY_EMAIL']

CHANNEL_HANDLE = 'orbitchurch'
SEEN_FILE      = os.path.join(os.path.dirname(__file__), 'seen_sermons.json')


# ── YouTube helpers ───────────────────────────────────────────────────────────
def get_channel_id():
    r = requests.get(
        'https://www.googleapis.com/youtube/v3/channels',
        params={'forHandle': CHANNEL_HANDLE, 'part': 'id', 'key': YOUTUBE_KEY},
        timeout=15,
    )
    r.raise_for_status()
    items = r.json().get('items', [])
    return items[0]['id'] if items else None


def get_recent_videos(channel_id, hours=52):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    r = requests.get(
        'https://www.googleapis.com/youtube/v3/search',
        params={
            'channelId':      channel_id,
            'part':           'snippet',
            'order':          'date',
            'type':           'video',
            'publishedAfter': since,
            'maxResults':     10,
            'key':            YOUTUBE_KEY,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get('items', [])


def get_video_details(video_id):
    r = requests.get(
        'https://www.googleapis.com/youtube/v3/videos',
        params={
            'id':   video_id,
            'part': 'snippet,contentDetails',
            'key':  YOUTUBE_KEY,
        },
        timeout=15,
    )
    r.raise_for_status()
    items = r.json().get('items', [])
    return items[0] if items else None


def best_thumbnail(thumbnails: dict) -> str:
    for quality in ('maxres', 'standard', 'high', 'medium', 'default'):
        if quality in thumbnails:
            return thumbnails[quality]['url']
    return ''


# ── Claude content parsing ────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a church communications assistant helping prepare sermon content
for The Church Co website. Extract and format sermon metadata from YouTube video information.
Always return valid JSON only — no markdown, no explanation."""

USER_PROMPT = """Here is a YouTube sermon video from Orbit Church:

Title: {title}
Published: {published}
Description:
{description}

Extract and return a JSON object with these exact keys:
- "sermon_title": Clean sermon title (remove any series prefix like "Part 1 |" etc.)
- "series_name": Sermon series name (look for it in the title or description; if unclear, infer from topic)
- "series_subtitle": One-line subtitle for the series (can be empty string if not clear)
- "speaker": Pastor/speaker full name
- "scripture": Primary scripture reference (book chapter:verse format, e.g. "John 3:16")
- "description": 2–3 sentence description for the church website (engaging, no timestamps or links)
- "sermon_notes_intro": 1–2 sentence intro paragraph for sermon notes page (optional, empty string if not applicable)
- "tags": Array of 3–5 topic tags (lowercase, e.g. ["faith", "prayer", "identity"])
- "date": Sermon date in YYYY-MM-DD format
- "is_sermon": true if this looks like a Sunday sermon, false if it's something else (promo, announcement, etc.)"""


def parse_with_claude(video: dict) -> dict:
    snippet   = video['snippet']
    video_id  = video['id']
    title     = snippet['title']
    desc      = snippet.get('description', '')
    published = snippet['publishedAt']

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    msg = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{
            'role':    'user',
            'content': USER_PROMPT.format(
                title=title, published=published, description=desc[:3000]
            ),
        }],
    )

    parsed = json.loads(msg.content[0].text)
    parsed['youtube_url']    = f'https://www.youtube.com/watch?v={video_id}'
    parsed['thumbnail_url']  = best_thumbnail(snippet.get('thumbnails', {}))
    parsed['raw_title']      = title
    return parsed


# ── Email ─────────────────────────────────────────────────────────────────────
def send_email(sermon: dict):
    lines = [
        f"New Sermon — {sermon.get('date', 'Today')}",
        f"Orbit Church · {sermon.get('series_name', '')}",
        '',
        'Everything below is formatted and ready to paste into The Church Co.',
        '=' * 62,
        '',
        'FIELDS FOR THE CHURCH CO',
        '-' * 30,
        f"Sermon Title    : {sermon['sermon_title']}",
        f"Speaker         : {sermon['speaker']}",
        f"Date            : {sermon['date']}",
        f"Scripture       : {sermon['scripture']}",
        f"Series Name     : {sermon['series_name']}",
        f"Series Subtitle : {sermon['series_subtitle']}",
        f"Tags            : {', '.join(sermon.get('tags', []))}",
        '',
        'DESCRIPTION:',
        sermon['description'],
    ]

    if sermon.get('sermon_notes_intro'):
        lines += ['', 'SERMON NOTES INTRO:', sermon['sermon_notes_intro']]

    lines += [
        '',
        '=' * 62,
        '',
        'LINKS',
        f"YouTube URL  : {sermon['youtube_url']}",
        f"Thumbnail    : {sermon['thumbnail_url']}",
        '',
        'HOW TO ADD IN THE CHURCH CO:',
        '  1. Dashboard → Sermon & Podcasts → Add New Sermon',
        '  2. Paste the YouTube URL above into the video field',
        '  3. Copy the fields above into the form',
        '  4. Right-click the thumbnail URL → Save Image As → upload it',
        '  5. Set the series (create new or select existing)',
        '  6. Publish!',
        '',
        '— Orbit Church Sermon Sync',
    ]

    body = '\n'.join(lines)
    msg  = MIMEMultipart('alternative')
    msg['Subject'] = f"New Sermon Ready: {sermon['sermon_title']}"
    msg['From']    = SMTP_USER
    msg['To']      = NOTIFY_TO
    msg.attach(MIMEText(body, 'plain'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    print(f'Email sent → {NOTIFY_TO}')


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    seen: set = set()
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            seen = set(json.load(f))

    print('Looking up Orbit Church YouTube channel...')
    channel_id = get_channel_id()
    if not channel_id:
        print('ERROR: Could not resolve @orbitchurch channel ID.')
        sys.exit(1)
    print(f'Channel ID: {channel_id}')

    print('Fetching recent videos (last 52 hours)...')
    items = get_recent_videos(channel_id)
    if not items:
        print('No new videos found.')
        with open(SEEN_FILE, 'w') as f:
            json.dump(sorted(seen), f, indent=2)
        return

    processed = 0
    for item in items:
        video_id = item['id']['videoId']
        if video_id in seen:
            print(f'  Skipping already-processed video: {video_id}')
            continue

        print(f'  Fetching details for {video_id}...')
        video = get_video_details(video_id)
        if not video:
            continue

        print(f'  Parsing with Claude: {video["snippet"]["title"]}')
        try:
            sermon = parse_with_claude(video)
        except Exception as e:
            print(f'  Claude parsing failed: {e}')
            continue

        if not sermon.get('is_sermon', True):
            print(f'  Skipping (not a sermon): {video["snippet"]["title"]}')
            seen.add(video_id)
            continue

        send_email(sermon)
        seen.add(video_id)
        processed += 1

    with open(SEEN_FILE, 'w') as f:
        json.dump(sorted(seen), f, indent=2)

    print(f'\nDone. Processed {processed} new sermon(s).')


if __name__ == '__main__':
    main()
