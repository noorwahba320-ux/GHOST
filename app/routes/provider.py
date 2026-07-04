from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_required, current_user
from app import db
from app.models.provider import Provider, OTPLog
from app.models.sms import SMDRange, SMSNumber
from app.fetcher import start_provider, stop_provider, is_running
from functools import wraps
from datetime import datetime, timedelta
from sqlalchemy import func
import re
import io
import csv

provider_bp = Blueprint('provider', __name__)

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_admin():
            flash('Access denied!', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated

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

@provider_bp.route('/admin/providers')
@login_required
@admin_required
def providers():
    all_providers = Provider.query.order_by(Provider.created_at.desc()).all()
    return render_template('admin/providers.html',
        providers=all_providers,
        builtin_panels=BUILTIN_PANELS,
        is_running=is_running
    )

@provider_bp.route('/admin/providers/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_provider():
    if request.method == 'POST':
        name           = request.form.get('name')
        url            = request.form.get('url')
        ptype          = request.form.get('ptype')
        username       = request.form.get('username')
        password       = request.form.get('password')
        fetch_interval = int(request.form.get('fetch_interval', 10))

        if Provider.query.filter_by(name=name).first():
            flash('Provider name already exists!', 'danger')
            return redirect(url_for('provider.add_provider'))

        p = Provider(
            name=name,
            url=url,
            ptype=ptype,
            username=username,
            password=password,
            fetch_interval=fetch_interval,
            is_active=True
        )
        db.session.add(p)
        db.session.commit()

        from flask import current_app
        start_provider(current_app._get_current_object(), p.id)
        flash(f'Provider {name} added and started!', 'success')
        return redirect(url_for('provider.providers'))

    builtin_name = request.args.get('builtin', '')
    builtin_data = BUILTIN_PANELS.get(builtin_name, {})
    return render_template('admin/provider_add.html',
        builtin_name=builtin_name,
        builtin_data=builtin_data,
        builtin_panels=BUILTIN_PANELS
    )

@provider_bp.route('/admin/providers/<int:provider_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_provider(provider_id):
    p = Provider.query.get_or_404(provider_id)
    if request.method == 'POST':
        p.username       = request.form.get('username')
        p.password       = request.form.get('password')
        p.fetch_interval = int(request.form.get('fetch_interval', 10))
        db.session.commit()

        if is_running(provider_id):
            stop_provider(provider_id)
            from flask import current_app
            start_provider(current_app._get_current_object(), provider_id)

        flash(f'Provider {p.name} updated!', 'success')
        return redirect(url_for('provider.providers'))

    return render_template('admin/provider_edit.html', provider=p)

@provider_bp.route('/admin/providers/<int:provider_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_provider(provider_id):
    p = Provider.query.get_or_404(provider_id)
    stop_provider(provider_id)
    OTPLog.query.filter_by(provider_id=provider_id).delete()
    db.session.delete(p)
    db.session.commit()
    flash(f'Provider {p.name} deleted!', 'success')
    return redirect(url_for('provider.providers'))

@provider_bp.route('/admin/providers/<int:provider_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_provider(provider_id):
    p = Provider.query.get_or_404(provider_id)
    if is_running(provider_id):
        stop_provider(provider_id)
        p.is_active = False
        db.session.commit()
        return jsonify({'status': 'stopped'})
    else:
        p.is_active = True
        db.session.commit()
        from flask import current_app
        start_provider(current_app._get_current_object(), provider_id)
        return jsonify({'status': 'started'})

@provider_bp.route('/admin/otp-logs')
@login_required
@admin_required
def otp_logs():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    fdate1 = request.args.get('fdate1', '')
    fdate2 = request.args.get('fdate2', '')
    fprovider = request.args.get('fprovider', '')
    frange = request.args.get('frange', '')
    fnum = request.args.get('fnum', '')

    def parse_date(date_str):
        try:
            return datetime.strptime(date_str, '%Y-%m-%d')
        except (ValueError, TypeError):
            return None

    logs_query = OTPLog.query

    date1 = parse_date(fdate1)
    if date1:
        logs_query = logs_query.filter(OTPLog.received_at >= date1)
    date2 = parse_date(fdate2)
    if date2:
        logs_query = logs_query.filter(OTPLog.received_at <= date2.replace(hour=23, minute=59, second=59))

    if fprovider:
        logs_query = logs_query.filter_by(provider_id=fprovider)

    if frange:
        logs_query = logs_query.join(SMSNumber, OTPLog.number_id == SMSNumber.id).filter(SMSNumber.range_id == frange)

    if fnum:
        logs_query = logs_query.filter(OTPLog.number.like(f'%{fnum}%'))

    logs_query = logs_query.order_by(OTPLog.received_at.desc())

    if request.args.get('export'):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Date', 'Range', 'Number', 'OTP', 'Sender', 'Client', 'SMS', 'Provider'])
        for l in logs_query.all():
            range_label = ''
            if l.sms_number and l.sms_number.sms_range:
                range_label = l.sms_number.sms_range.name if l.sms_number.sms_range.name else l.sms_number.sms_range.country
            writer.writerow([
                l.received_at.strftime('%Y-%m-%d %H:%M:%S') if l.received_at else '',
                range_label,
                l.number,
                l.otp,
                l.sender or '',
                l.user.username if l.user else '',
                l.message or '',
                l.provider.name if l.provider else ''
            ])
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=otp_logs.csv'}
        )

    logs = logs_query.paginate(page=page, per_page=per_page, error_out=False)
    providers = Provider.query.all()
    ranges = SMDRange.query.filter_by(is_active=True).all()

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    live_start = now - timedelta(minutes=5)

    stats = {
        'today': OTPLog.query.filter(OTPLog.received_at >= today_start).count(),
        'week': OTPLog.query.filter(OTPLog.received_at >= week_start).count(),
        'live': OTPLog.query.filter(OTPLog.received_at >= live_start).count(),
        'total': OTPLog.query.count(),
        'active_providers': Provider.query.filter_by(is_active=True).count(),
        'total_providers': Provider.query.count(),
    }

    return render_template('admin/otp_logs.html', logs=logs, providers=providers, ranges=ranges, stats=stats)

@provider_bp.route('/agent/otp-inbox')
@login_required
def otp_inbox():
    page = request.args.get('page', 1, type=int)
    if current_user.is_admin():
        logs = OTPLog.query.order_by(OTPLog.received_at.desc()).paginate(
            page=page, per_page=50, error_out=False
        )
    else:
        logs = OTPLog.query.filter_by(user_id=current_user.id).order_by(
            OTPLog.received_at.desc()
        ).paginate(page=page, per_page=50, error_out=False)
    return render_template('main/otp_inbox.html', logs=logs)

@provider_bp.route('/api/otp-inbox')
@login_required
def otp_inbox_api():
    if current_user.is_admin():
        logs = OTPLog.query.order_by(OTPLog.received_at.desc()).limit(50).all()
    else:
        logs = OTPLog.query.filter_by(user_id=current_user.id).order_by(
            OTPLog.received_at.desc()
        ).limit(50).all()
    return jsonify([{
        'id':          l.id,
        'number':      l.number,
        'otp':         l.otp,
        'sender':      l.sender,
        'message':     l.message,
        'received_at': l.received_at.strftime('%Y-%m-%d %H:%M:%S')
    } for l in logs])