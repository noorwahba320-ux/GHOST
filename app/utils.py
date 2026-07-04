"""
app/utils.py
Shared helpers:

1. Local-day boundaries (Africa/Cairo) — used so that "Today" counters
   (Today SMS, daily add-number limits, etc.) reset at local midnight
   instead of server/UTC midnight. `created_at` columns are stored as
   naive UTC (datetime.utcnow()), so we convert the local midnight
   boundary to UTC before comparing.

2. OTP/code masking — used on the shared public Test123 demo account so
   that real OTP codes inside SMS text are not fully readable by anyone
   who logs into the demo.
"""

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo('Africa/Cairo')


def upload_logo_to_blob(file_storage, ext):
    """Upload a logo file to Vercel Blob storage over its HTTP API and
    return the public URL, or None if it's not configured/fails.

    Needed because Vercel's filesystem is read-only at request time, so
    a plain `file.save(path)` to app/static doesn't persist there. Enable
    a Blob store on the Vercel project (Storage tab) and it auto-injects
    BLOB_READ_WRITE_TOKEN into the project's env vars.
    """
    import os
    import requests

    token = os.environ.get('BLOB_READ_WRITE_TOKEN')
    if not token:
        return None

    pathname = f'logos/logo-{int(datetime.utcnow().timestamp())}.{ext}'
    content_type_map = {
        'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
        'svg': 'image/svg+xml', 'webp': 'image/webp',
    }

    resp = requests.put(
        f'https://blob.vercel-storage.com/{pathname}',
        data=file_storage.read(),
        headers={
            'Authorization': f'Bearer {token}',
            'x-api-version': '7',
            'Content-Type': content_type_map.get(ext, 'application/octet-stream'),
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get('url')

UTC_TZ = ZoneInfo('UTC')


def local_today():
    """Today's date in the panel's local timezone (Africa/Cairo)."""
    return datetime.now(LOCAL_TZ).date()


def local_day_bounds(target_date=None):
    """
    Return (start_utc, end_utc) as naive UTC datetimes marking the start
    (inclusive) and end (exclusive) of a local calendar day. Compare
    `created_at >= start_utc` and `created_at < end_utc` instead of
    `func.date(created_at) == target_date`, so the boundary lines up with
    local midnight rather than UTC midnight.
    """
    if target_date is None:
        target_date = local_today()
    start_local = datetime.combine(target_date, time.min, tzinfo=LOCAL_TZ)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(UTC_TZ).replace(tzinfo=None)
    end_utc = end_local.astimezone(UTC_TZ).replace(tzinfo=None)
    return start_utc, end_utc


_CODE_RE = re.compile(r'\d{3,}')


def mask_codes(text):
    """
    Mask numeric OTP codes inside an SMS message. Keeps the first digit
    only and stars out the rest (e.g. '482913' -> '4•••••'), so the
    shared/public Test account cannot be used to read real one-time
    passwords, while the rest of the message stays readable.
    """
    if not text:
        return text

    def _mask(match):
        digits = match.group(0)
        if len(digits) <= 2:
            return digits
        return digits[0] + '•' * (len(digits) - 1)

    return _CODE_RE.sub(_mask, text)
