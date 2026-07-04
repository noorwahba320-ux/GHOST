"""
sms_monitor.py  —  FLASH SMS Monitor
======================================
يجيب الرسائل من المصادر الخارجية (Panel4 + TimeSMS)
ويعمل forward للأرقام المحجوزة تلقائياً.
"""
import re, json, time, requests
from datetime import datetime, timedelta, date
from urllib.parse import quote_plus
from functools import wraps
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.sms import SMSNumber, SMSCDR
from app.models.activity import ActivityLog

monitor_bp = Blueprint('monitor', __name__, url_prefix='/monitor')

# ─── helpers ────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10)",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

def _clean_html(t):
    return re.sub(r'<[^>]+>', '', str(t or '')).strip()

def _clean_num(n):
    return re.sub(r'\D', '', str(n or ''))

def admin_required(f):
    @wraps(f)
    def d(*a, **kw):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*a, **kw)
    return d

# ─── Panel 4 fetcher ────────────────────────────────────────────────────────

CFG_P4 = {
    "name": "Panel 4",
    "base": "http://145.239.130.45",
    "ajax_path": "/ints/agent/res/data_smscdr.php",
    "login_page": "/ints/login",
    "login_post": "/ints/signin",
    "username": "Commando4",
    "password": "Commando4",
    "timeout": 10,
    "idx_date": 0, "idx_number": 2, "idx_sms": 5,
}

_p4_session = None
_p4_logged_in = False


def _p4_login():
    global _p4_session, _p4_logged_in
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        r = s.get(CFG_P4["base"] + CFG_P4["login_page"], timeout=CFG_P4["timeout"])
        m = re.search(r'What is (\d+) \+ (\d+)', r.text)
        if not m:
            if "logout" in r.text.lower():
                _p4_session, _p4_logged_in = s, True
                return True
            return False
        payload = {
            "username": CFG_P4["username"],
            "password": CFG_P4["password"],
            "capt": str(int(m.group(1)) + int(m.group(2))),
        }
        r2 = s.post(CFG_P4["base"] + CFG_P4["login_post"], data=payload, timeout=CFG_P4["timeout"])
        ok = any(k in r2.text.lower() for k in ("dashboard", "logout", "agent"))
        _p4_session, _p4_logged_in = s, ok
        return ok
    except Exception as e:
        print(f"[Panel4] login error: {e}")
        return False


def fetch_panel4():
    """Fetch today's CDR from Panel 4. Returns list of dicts."""
    global _p4_session, _p4_logged_in
    if not _p4_logged_in:
        if not _p4_login():
            return [], "Login failed"

    today = date.today()
    td = f"{today.strftime('%Y-%m-%d')} 00:00:00"
    td2 = f"{(today + timedelta(days=1)).strftime('%Y-%m-%d')} 23:59:59"
    ts = int(time.time() * 1000)
    q = (
        f"fdate1={quote_plus(td)}&fdate2={quote_plus(td2)}"
        f"&frange=&fclient=&fnum=&fcli=&fgdate=&fgmonth=&fgrange=&fgclient=&fgnumber=&fgcli="
        f"&fg=0&sEcho=1&iColumns=9&sColumns=%2C%2C%2C%2C%2C%2C%2C%2C"
        f"&iDisplayStart=0&iDisplayLength=5000"
        f"&mDataProp_0=0&mDataProp_1=1&mDataProp_2=2&mDataProp_3=3&mDataProp_4=4"
        f"&mDataProp_5=5&mDataProp_6=6&mDataProp_7=7&mDataProp_8=8"
        f"&sSearch=&bRegex=false&iSortCol_0=0&sSortDir_0=desc&iSortingCols=1&_={ts}"
    )
    url = CFG_P4["base"] + CFG_P4["ajax_path"] + "?" + q
    try:
        r = _p4_session.get(url, timeout=12)
        if r.status_code == 403 or "login" in r.url.lower():
            _p4_logged_in = False
            if _p4_login():
                r = _p4_session.get(url, timeout=12)
            else:
                return [], "Session expired, re-login failed"
        data = r.json()
    except Exception as e:
        _p4_logged_in = False
        return [], str(e)

    rows = []
    for k in ("data", "aaData", "rows"):
        if isinstance(data, dict) and k in data:
            rows = data[k]; break
    if not rows and isinstance(data, list):
        rows = data

    msgs = []
    ix_d, ix_n, ix_s = CFG_P4["idx_date"], CFG_P4["idx_number"], CFG_P4["idx_sms"]
    for row in rows:
        if isinstance(row, (list, tuple)):
            d = _clean_html(row[ix_d] if len(row) > ix_d else "")
            n = _clean_num(row[ix_n]  if len(row) > ix_n else "")
            s = _clean_html(row[ix_s] if len(row) > ix_s else "")
        elif isinstance(row, dict):
            d = _clean_html(row.get("date", row.get("dt", "")))
            n = _clean_num(row.get("number", row.get("msisdn", row.get("num", ""))))
            s = _clean_html(row.get("sms", row.get("message", row.get("msg", ""))))
        else:
            continue

        if d and n and len(n) >= 8 and s and len(s) > 3:
            msgs.append({"id": f"p4_{n}_{d}", "number": n, "text": s, "date": d, "source": "panel4"})

    return msgs, "ok"


# ─── TimeSMS fetcher ─────────────────────────────────────────────────────────

CFG_TS = {
    "api_url":   "http://147.135.212.197/crapi/time/viewstats",
    "api_token": "RVRVNEVBmIGEiZZbeIyOZXWFg1l5UYJIeGdpa2d2bmKDZmNcXlU=",
    "timeout":   15,
    "records":   500,
}


def fetch_timesms(days_back=1):
    """Fetch messages from TimeSMS API. Returns (list, status_str)."""
    now = datetime.now()
    params = {
        "token":   CFG_TS["api_token"],
        "dt1":     (now - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M:%S"),
        "dt2":     now.strftime("%Y-%m-%d %H:%M:%S"),
        "records": CFG_TS["records"],
    }
    try:
        r = requests.get(CFG_TS["api_url"], params=params, timeout=CFG_TS["timeout"])
        data = r.json()
        if data.get("status") != "success":
            return [], data.get("msg", "API error")
        msgs = []
        for item in data.get("data", []):
            n = _clean_num(item.get("num", ""))
            s = str(item.get("message", "")).strip()
            d = str(item.get("dt", ""))
            if n and s:
                msgs.append({"id": f"ts_{n}_{d}", "number": n, "text": s, "date": d, "source": "timesms"})
        return msgs, "ok"
    except Exception as e:
        return [], str(e)


# ─── Forwarder ───────────────────────────────────────────────────────────────

def forward_to_reserved(messages):
    """
    Match each message's number against reserved SMSNumbers.
    Creates CDR records of type 'received'. Returns stats dict.
    """
    if not messages:
        return {"forwarded": 0, "skipped": 0, "duplicate": 0}

    # Load existing external IDs to skip duplicates
    existing = set(
        r[0] for r in db.session.query(SMSCDR.caller_id)
              .filter(SMSCDR.sms_type == 'received',
                      SMSCDR.caller_id.isnot(None)).all()
    )

    forwarded = skipped = duplicate = 0

    for msg in messages:
        ext_id = msg.get("id", "")
        if ext_id in existing:
            duplicate += 1
            continue

        raw_num = msg.get("number", "")
        if not raw_num:
            skipped += 1
            continue

        # Try exact match first
        sms_num = SMSNumber.query.filter_by(number=raw_num, is_active=True).first()

        # Try suffix match (last 9 digits) for prefix differences
        if not sms_num and len(raw_num) >= 9:
            suffix = raw_num[-9:]
            sms_num = SMSNumber.query.filter(
                SMSNumber.number.like(f"%{suffix}"),
                SMSNumber.is_active == True
            ).first()

        if not sms_num or not sms_num.agent_id:
            skipped += 1
            continue

        cdr = SMSCDR(
            number_id   = sms_num.id,
            range_id    = sms_num.range_id,
            user_id     = sms_num.agent_id,
            client_id   = sms_num.client_id,
            caller_id   = ext_id,
            destination = raw_num,
            cli         = msg.get("source", "external"),
            message     = msg.get("text", ""),
            sms_type    = "received",
            status      = "completed",
            profit      = 0.0,
            agent_payout  = sms_num.agent_payout  or 0.0,
            client_payout = sms_num.client_payout or 0.0,
            currency    = "USD",
        )
        db.session.add(cdr)
        existing.add(ext_id)
        forwarded += 1

    if forwarded:
        db.session.commit()

    return {"forwarded": forwarded, "skipped": skipped, "duplicate": duplicate}


# ─── Routes ──────────────────────────────────────────────────────────────────

@monitor_bp.route('/')
@login_required
@admin_required
def index():
    received = SMSCDR.query.filter_by(sms_type='received') \
                           .order_by(SMSCDR.created_at.desc()).limit(50).all()
    today = datetime.utcnow().date()
    today_count = SMSCDR.query.filter_by(sms_type='received') \
                              .filter(db.func.date(SMSCDR.created_at) == today).count()
    total_count = SMSCDR.query.filter_by(sms_type='received').count()
    return render_template('admin/sms_monitor.html',
                           received=received,
                           today_count=today_count,
                           total_count=total_count)


@monitor_bp.route('/run', methods=['POST'])
@login_required
@admin_required
def run_cycle():
    """Manual fetch + forward — called by AJAX or form POST."""
    source = request.form.get('source', 'all')
    messages = []
    statuses = {}

    if source in ('all', 'panel4'):
        msgs, st = fetch_panel4()
        messages.extend(msgs)
        statuses['panel4'] = {'count': len(msgs), 'status': st}

    if source in ('all', 'timesms'):
        msgs, st = fetch_timesms(days_back=1)
        messages.extend(msgs)
        statuses['timesms'] = {'count': len(msgs), 'status': st}

    result = forward_to_reserved(messages)
    result['fetched'] = len(messages)
    result['sources'] = statuses

    ActivityLog.log(
        current_user.id, 'monitor_run',
        f"fetched={len(messages)} fwd={result['forwarded']} skip={result['skipped']} dup={result['duplicate']}",
        ip_address=request.remote_addr
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json:
        return jsonify({'success': True, **result})

    flash(
        f"✅ Fetched {len(messages)} msgs — Forwarded: {result['forwarded']}, "
        f"Skipped: {result['skipped']}, Duplicate: {result['duplicate']}",
        'success'
    )
    return redirect(url_for('monitor.index'))


@monitor_bp.route('/messages')
@login_required
@admin_required
def get_messages():
    """AJAX — returns latest received messages as JSON."""
    limit = request.args.get('limit', 50, type=int)
    records = SMSCDR.query.filter_by(sms_type='received') \
                          .order_by(SMSCDR.created_at.desc()).limit(limit).all()
    data = []
    for r in records:
        data.append({
            'id':      r.id,
            'number':  r.sms_number.number if r.sms_number else (r.destination or '—'),
            'message': r.message or '',
            'source':  r.cli or 'external',
            'date':    r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else '',
            'agent':   r.sms_number.agent.username if (r.sms_number and r.sms_number.agent) else '—',
        })
    today = datetime.utcnow().date()
    today_count = SMSCDR.query.filter_by(sms_type='received') \
                              .filter(db.func.date(SMSCDR.created_at) == today).count()
    total_count = SMSCDR.query.filter_by(sms_type='received').count()
    return jsonify({'success': True, 'messages': data,
                    'today_count': today_count, 'total_count': total_count})


@monitor_bp.route('/status')
@login_required
@admin_required
def get_status():
    """AJAX — quick status check for both sources."""
    p4_ok = bool(_p4_logged_in and _p4_session)
    return jsonify({
        'panel4':  {'logged_in': p4_ok,  'name': CFG_P4['name']},
        'timesms': {'logged_in': True,   'name': 'TimeSMS API'},
    })
