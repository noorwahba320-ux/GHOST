import threading
import time
import re
import logging
from datetime import datetime

log = logging.getLogger("Fetcher")

_stop_events = {}
_threads = {}
_sessions = {}

BUILTIN_PANELS = {
    "ChoiceSMS":   {"url": "http://51.77.52.79/ints",         "ptype": "ints"},
    "FlynSMS":     {"url": "http://91.232.105.47/ints",       "ptype": "ints"},
    "Gaza":        {"url": "http://144.217.71.192/ints",      "ptype": "ints"},
    "GoatPanel":   {"url": "http://167.114.117.67/ints",      "ptype": "ints"},
    "HADI_SMS":    {"url": "http://2.59.169.96/ints",         "ptype": "ints"},
    "ImsPanel":    {"url": "https://www.imssms.org",          "ptype": "ims"},
    "KmSms":       {"url": "http://54.36.173.235/ints",       "ptype": "ints"},
    "Konekta":     {"url": "https://konektapremium.net",      "ptype": "konekta"},
    "MsiSMS":      {"url": "http://145.239.130.45/ints",      "ptype": "ints"},
    "NumberPanel": {"url": "http://51.89.99.105/NumberPanel", "ptype": "numberpanel"},
    "ProofSMS":    {"url": "http://217.182.195.194/ints",     "ptype": "proofsms"},
    "PurplePanel": {"url": "http://85.195.94.50/sms",         "ptype": "standard"},
    "RoxySMS":     {"url": "http://www.roxysms.net",          "ptype": "roxy"},
    "Seven1Tel":   {"url": "http://94.23.120.156/ints",       "ptype": "ints"},
    "SharkSMS":    {"url": "http://65.109.111.158/ints",      "ptype": "ints"},
    "TrueSMS":     {"url": "https://truesms.net",             "ptype": "standard"},
    "VoiceGate":   {"url": "http://51.89.7.175/sms",          "ptype": "voicegate"},
    "Wolf":        {"url": "http://213.32.24.208/ints",       "ptype": "ints"},
    "GreenSMS":    {"url": "http://139.99.9.4/ints",          "ptype": "ints"},
    "FireSMS":     {"url": "http://54.39.104.241/ints",       "ptype": "ints"},
    "SniperPanel": {"url": "http://135.125.222.224/ints",     "ptype": "ints"},
    "MAIT":        {"url": "http://168.119.13.175/ints",      "ptype": "ints"},
    "TimeSMS":     {"url": "https://www.timesms.org",         "ptype": "timesms"},
}

def _detect_otp(text):
    if not text:
        return None
    text = re.sub(r"<#>\s*", "", str(text))
    m = re.search(r"(\d{3,4}-\d{3,4})(?!\d)", text)
    if m:
        return m.group(1)
    m = re.search(
        r"(?:code|otp|pin|passcode|verif\w*|codigo|كود|رمز|رقم|Password|Confirmation)"
        r"[^\d]*(\d{4,8})", text, re.I)
    if m:
        return m.group(1)
    m = re.search(r":\s*(\d{4,8})\b", text)
    if m:
        return m.group(1)
    for m in re.finditer(r"(?<![/\-\d])(\d{4,6})(?![/\-\d])", text):
        c = m.group(1)
        if re.match(r"^20[0-9]{2}$", c):
            continue
        return c
    return None

def _save_otp(app, provider_id, number, otp, sender, message):
    with app.app_context():
        from app.models.provider import OTPLog
        from app.models.sms import SMSNumber, SMSCDR
        from app import db

        num_clean = re.sub(r"\D", "", str(number))

        # ── Duplicate check: same number + same OTP = always duplicate ──
        # No time window — if this exact OTP for this exact number was ever
        # logged before, skip it. Only a DIFFERENT OTP on the same number
        # counts as a new entry.
        existing = OTPLog.query.filter_by(
            number=num_clean,
            otp=otp
        ).first()

        if existing:
            log.info(f"Duplicate OTP skipped: {num_clean} → {otp}")
            return

        sms_number = SMSNumber.query.filter(
            SMSNumber.number.like(f"%{num_clean[-10:]}")
        ).first()

        user_id = None
        if sms_number:
            user_id = sms_number.client_id or sms_number.agent_id

        entry = OTPLog(
            provider_id=provider_id,
            number=num_clean,
            otp=otp,
            sender=sender,
            message=message,
            number_id=sms_number.id if sms_number else None,
            user_id=user_id
        )
        db.session.add(entry)

        # ── Also write into SMSCDR so Agent CDR Reports + SMS Test Panel ──
        # show this OTP. Without this, only the Admin OTP Logs page sees it.
        if sms_number:
            cdr = SMSCDR(
                number_id=sms_number.id,
                range_id=sms_number.range_id,
                user_id=sms_number.agent_id,
                client_id=sms_number.client_id,
                caller_id=sender,
                destination=num_clean,
                cli=sender,
                message=message,
                created_at=datetime.utcnow(),
                currency='USD',
                agent_payout=sms_number.agent_payout or 0.0,
                client_payout=sms_number.client_payout or 0.0,
                profit=(sms_number.client_payout or 0.0) - (sms_number.agent_payout or 0.0),
                sms_type='received',
                status='completed'
            )
            db.session.add(cdr)

        db.session.commit()
        log.info(f"OTP saved: {num_clean} → {otp}")


def _fetch_loop(app, provider_id, stop_event):
    session_info = None

    while not stop_event.is_set():
        with app.app_context():
            from app.models.provider import Provider
            provider = Provider.query.get(provider_id)
            if not provider or not provider.is_active:
                break
            name           = provider.name
            url            = provider.url
            ptype          = provider.ptype
            username       = provider.username
            password       = provider.password
            fetch_interval = provider.fetch_interval

        try:
            from panel_fetchers import (
                ints_login, ints_fetch,
                ims_login, ims_fetch,
                konekta_login, konekta_fetch,
                panel_login, panel_fetch,
                new_panel_login, new_panel_fetch,
                timesms_login, timesms_fetch,
                proofsms_fetch,
            )

            if session_info is None:
                log.info(f"[{name}] Logging in...")
                try:
                    if ptype == "ints":
                        session_info = ints_login(name, username, password, url)
                    elif ptype == "ims":
                        session_info = ims_login(username, password, url)
                    elif ptype == "konekta":
                        session_info = konekta_login(username, password)
                    elif ptype == "standard":
                        session_info = panel_login(name, username, password, url)
                    elif ptype == "timesms":
                        session_info = timesms_login(name, username, password, url)
                    elif ptype in ("roxy", "voicegate", "numberpanel", "proofsms"):
                        session_info = new_panel_login(name, username, password, url)
                    else:
                        session_info = ints_login(name, username, password, url)
                    log.info(f"[{name}] Login OK")
                except Exception as e:
                    log.error(f"[{name}] Login failed: {e}")
                    stop_event.wait(30)
                    continue

            try:
                if ptype == "ints":
                    rows = ints_fetch(name, session_info, url)
                elif ptype == "ims":
                    rows = ims_fetch(session_info, url)
                elif ptype == "konekta":
                    rows = konekta_fetch(session_info)
                elif ptype == "standard":
                    rows = panel_fetch(session_info, url)
                elif ptype == "timesms":
                    rows = timesms_fetch(name, session_info, url)
                elif ptype in ("roxy", "voicegate", "numberpanel", "proofsms"):
                    rows = new_panel_fetch(name, session_info, url)
                else:
                    rows = ints_fetch(name, session_info, url)
            except Exception as e:
                log.error(f"[{name}] Fetch error: {e}")
                session_info = None
                stop_event.wait(15)
                continue

            if rows is None:
                log.info(f"[{name}] Session expired, re-logging...")
                session_info = None
                continue

            if rows:
                for row in rows:
                    if isinstance(row, list):
                        number  = str(row[2]) if len(row) > 2 else ""
                        sender  = str(row[3]) if len(row) > 3 else ""
                        message = str(row[5]) if len(row) > 5 else ""
                    elif isinstance(row, dict):
                        number  = str(row.get("number", ""))
                        sender  = str(row.get("cli", ""))
                        message = str(row.get("sms", ""))
                    else:
                        continue

                    if not number:
                        continue

                    otp = _detect_otp(message)
                    if not otp:
                        continue

                    _save_otp(app, provider_id, number, otp, sender, message)

        except Exception as e:
            log.error(f"[{name}] Loop error: {e}")
            session_info = None

        stop_event.wait(fetch_interval)

    log.info(f"[{name}] Stopped")

def start_provider(app, provider_id):
    stop_provider(provider_id)
    stop_event = threading.Event()
    _stop_events[provider_id] = stop_event
    t = threading.Thread(
        target=_fetch_loop,
        args=(app, provider_id, stop_event),
        daemon=True,
        name=f"provider_{provider_id}"
    )
    t.start()
    _threads[provider_id] = t
    log.info(f"Provider {provider_id} started")

def stop_provider(provider_id):
    if provider_id in _stop_events:
        _stop_events[provider_id].set()
        del _stop_events[provider_id]
    if provider_id in _threads:
        del _threads[provider_id]
    log.info(f"Provider {provider_id} stopped")

def is_running(provider_id):
    if provider_id not in _stop_events:
        return False
    if _stop_events[provider_id].is_set():
        return False
    t = _threads.get(provider_id)
    return t is not None and t.is_alive()

def start_all_providers(app):
    with app.app_context():
        from app.models.provider import Provider
        providers = Provider.query.filter_by(is_active=True).all()
        for p in providers:
            start_provider(app, p.id)
        log.info(f"Auto-started {len(providers)} providers")