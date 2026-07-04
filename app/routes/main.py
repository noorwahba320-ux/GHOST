from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, Response, session
from flask_login import login_required, current_user
from app import db
from app.models.sms import SMDRange, SMSNumber, SMSCDR
from app.models.activity import News
from app.models.user import User, Role
from datetime import datetime, timedelta
from sqlalchemy import func
from app.utils import local_today, local_day_bounds, mask_codes
import csv
import io

main_bp = Blueprint('main', __name__)


@main_bp.route('/agent/')
@main_bp.route('/agent/dashboard')
@login_required
def dashboard():
    # "Today" is anchored to local (Africa/Cairo) midnight, not UTC midnight,
    # so counters like "Today SMS" reset at local 12:00 AM as expected.
    today = local_today()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    today_start, today_end = local_day_bounds(today)
    yesterday_start, yesterday_end = local_day_bounds(yesterday)

    news = News.query.filter_by(is_active=True).order_by(News.created_at.desc()).limit(5).all()
    # NOTE: the "welcome voice" flag is read/consumed in base.html, not here.

    # ── Admin: system-wide overview, no personal SMS counters ──
    if current_user.is_admin():
        total_agents = User.query.filter(User.role.has(name='agent')).count()
        total_clients = User.query.filter(User.role.has(name='client')).count()
        total_numbers = SMSNumber.query.count()
        ranges_count = SMDRange.query.filter_by(is_active=True).count()
        total_sms = SMSCDR.query.count()
        active_users = User.query.filter_by(is_active=True).count()

        chart_data = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            d_start, d_end = local_day_bounds(day)
            count = SMSCDR.query.filter(SMSCDR.created_at >= d_start, SMSCDR.created_at < d_end).count()
            chart_data.append({'date': day.strftime('%Y-%m-%d'), 'count': count})

        return render_template('main/dashboard.html',
            is_admin_view=True,
            total_agents=total_agents,
            total_clients=total_clients,
            total_numbers=total_numbers,
            ranges_count=ranges_count,
            total_sms=total_sms,
            active_users=active_users,
            news=news,
            chart_data=chart_data
        )

    # ── Test123 demo account: only Today SMS, no earnings/wallet at all ──
    if current_user.is_test_account():
        today_sms = SMSCDR.query.filter(
            SMSCDR.user_id == current_user.id,
            SMSCDR.created_at >= today_start, SMSCDR.created_at < today_end
        ).count()
        numbers_count = SMSNumber.query.filter_by(agent_id=current_user.id).count()

        chart_data = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            d_start, d_end = local_day_bounds(day)
            count = SMSCDR.query.filter(
                SMSCDR.user_id == current_user.id,
                SMSCDR.created_at >= d_start, SMSCDR.created_at < d_end
            ).count()
            chart_data.append({'date': day.strftime('%Y-%m-%d'), 'count': count})

        return render_template('main/dashboard.html',
            is_test_view=True,
            is_admin_view=False,
            today_sms=today_sms,
            numbers_count=numbers_count,
            news=news,
            chart_data=chart_data
        )

    # ── Client: only Today SMS / Yesterday SMS, no earnings, no API, no extras ──
    if current_user.is_client():
        cdr_filter = (SMSCDR.client_id == current_user.id)

        today_sms = SMSCDR.query.filter(
            cdr_filter,
            SMSCDR.created_at >= today_start, SMSCDR.created_at < today_end
        ).count()
        yesterday_sms = SMSCDR.query.filter(
            cdr_filter,
            SMSCDR.created_at >= yesterday_start, SMSCDR.created_at < yesterday_end
        ).count()

        chart_data = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            d_start, d_end = local_day_bounds(day)
            count = SMSCDR.query.filter(
                cdr_filter,
                SMSCDR.created_at >= d_start, SMSCDR.created_at < d_end
            ).count()
            chart_data.append({'date': day.strftime('%Y-%m-%d'), 'count': count})

        return render_template('main/dashboard.html',
            is_admin_view=False,
            is_client_view=True,
            today_sms=today_sms,
            yesterday_sms=yesterday_sms,
            news=news,
            chart_data=chart_data
        )

    # ── Agent: personal SMS counters + earnings + client overview ──
    cdr_filter = (SMSCDR.user_id == current_user.id)
    payout_col = SMSCDR.agent_payout

    today_sms = SMSCDR.query.filter(
        cdr_filter,
        SMSCDR.created_at >= today_start, SMSCDR.created_at < today_end
    ).count()
    today_earnings = db.session.query(func.sum(payout_col)).filter(
        cdr_filter,
        SMSCDR.created_at >= today_start, SMSCDR.created_at < today_end
    ).scalar() or 0.0

    yesterday_sms = SMSCDR.query.filter(
        cdr_filter,
        SMSCDR.created_at >= yesterday_start, SMSCDR.created_at < yesterday_end
    ).count()
    yesterday_earnings = db.session.query(func.sum(payout_col)).filter(
        cdr_filter,
        SMSCDR.created_at >= yesterday_start, SMSCDR.created_at < yesterday_end
    ).scalar() or 0.0

    week_sms = SMSCDR.query.filter(
        cdr_filter,
        SMSCDR.created_at >= week_ago
    ).count()
    week_earnings = db.session.query(func.sum(payout_col)).filter(
        cdr_filter,
        SMSCDR.created_at >= week_ago
    ).scalar() or 0.0

    first_of_month = today.replace(day=1)
    month_total = SMSCDR.query.filter(
        cdr_filter,
        SMSCDR.created_at >= first_of_month
    ).count()
    month_earnings = db.session.query(func.sum(payout_col)).filter(
        cdr_filter,
        SMSCDR.created_at >= first_of_month
    ).scalar() or 0.0

    ranges_count = SMDRange.query.filter_by(is_active=True).count()
    numbers_count = SMSNumber.query.filter_by(agent_id=current_user.id).count()
    clients_count = User.query.filter_by(agent_id=current_user.id).count()
    recent_clients = User.query.filter_by(agent_id=current_user.id).order_by(User.created_at.desc()).limit(5).all()

    chart_data = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        d_start, d_end = local_day_bounds(day)
        count = SMSCDR.query.filter(
            cdr_filter,
            SMSCDR.created_at >= d_start, SMSCDR.created_at < d_end
        ).count()
        chart_data.append({'date': day.strftime('%Y-%m-%d'), 'count': count})

    return render_template('main/dashboard.html',
        is_admin_view=False,
        is_client_view=False,
        today_sms=today_sms,
        today_earnings=today_earnings,
        yesterday_sms=yesterday_sms,
        yesterday_earnings=yesterday_earnings,
        week_sms=week_sms,
        week_earnings=week_earnings,
        month_total=month_total,
        month_earnings=month_earnings,
        ranges_count=ranges_count,
        numbers_count=numbers_count,
        clients_count=clients_count,
        news=news,
        recent_clients=recent_clients,
        chart_data=chart_data
    )


@main_bp.route('/agent/SMSRanges')
@login_required
def sms_ranges():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    ranges_query = SMDRange.query.filter_by(is_active=True)
    search = request.args.get('search', '')
    if search:
        ranges_query = ranges_query.filter(
            db.or_(
                SMDRange.prefix.like(f'%{search}%'),
                SMDRange.country.like(f'%{search}%')
            )
        )
    ranges = ranges_query.order_by(SMDRange.country).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template('main/sms_ranges.html', ranges=ranges)


@main_bp.route('/agent/SMSTestPanel')
@login_required
def sms_test_panel():
    # Removed from the sidebar for agent/client/test accounts: this page
    # showed EVERY user's SMS/OTP records with no per-user filtering at
    # all, which leaked private codes across accounts. Admin-only now.
    if not current_user.is_admin():
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    frange = request.args.get('frange', '')

    cdr_query = SMSCDR.query

    if frange:
        cdr_query = cdr_query.filter_by(range_id=frange)

    cdr_records = cdr_query.order_by(SMSCDR.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    total_sms = SMSCDR.query.count()
    ranges = SMDRange.query.filter_by(is_active=True).order_by(SMDRange.country).all()

    return render_template('main/sms_test_panel.html',
        cdr_records=cdr_records,
        total_sms=total_sms,
        ranges=ranges
    )


@main_bp.route('/agent/MyAssignedNumbers')
@login_required
def client_my_numbers():
    if not current_user.is_client():
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    search = request.args.get('search', '')
    frange = request.args.get('frange', '')

    query = SMSNumber.query.filter_by(client_id=current_user.id)
    if search:
        query = query.filter(SMSNumber.number.like(f'%{search}%'))
    if frange:
        query = query.filter_by(range_id=frange)

    if per_page == 99999:
        all_numbers = query.order_by(SMSNumber.number).all()
        class FakePaginate:
            def __init__(self, items):
                self.items = items
                self.total = len(items)
                self.page = 1
                self.pages = 1
                self.has_prev = False
                self.has_next = False
                self.prev_num = None
                self.next_num = None
        numbers = FakePaginate(all_numbers)
    else:
        numbers = query.order_by(SMSNumber.number).paginate(
            page=page, per_page=per_page, error_out=False
        )

    total_numbers = SMSNumber.query.filter_by(client_id=current_user.id).count()

    range_ids = db.session.query(SMSNumber.range_id).filter_by(client_id=current_user.id).distinct().all()
    range_ids = [r[0] for r in range_ids]
    ranges = SMDRange.query.filter(SMDRange.id.in_(range_ids)).all() if range_ids else []

    return render_template('main/client_numbers.html',
        numbers=numbers,
        total_numbers=total_numbers,
        per_page=per_page,
        ranges=ranges
    )


@main_bp.route('/agent/DownloadMyAssignedNumbers')
@login_required
def client_download_numbers():
    if not current_user.is_client():
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))

    numbers = SMSNumber.query.filter_by(client_id=current_user.id).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Number', 'Range', 'OTP Price', 'Status', 'Assigned Date'])

    for num in numbers:
        writer.writerow([
            num.number,
            f"+{num.sms_range.prefix} - {num.sms_range.country}" if num.sms_range else '',
            num.client_payout,
            num.status,
            num.assigned_at.strftime('%Y-%m-%d %H:%M') if num.assigned_at else ''
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=my_numbers.csv'}
    )


@main_bp.route('/agent/SMSCDRReports')
@login_required
def sms_cdr_reports():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)
    if current_user.is_test_account():
        default_from = (datetime.utcnow() - timedelta(days=365)).strftime('%Y-%m-%d')
    else:
        default_from = datetime.utcnow().strftime('%Y-%m-%d')
    fdate1 = request.args.get('fdate1', default_from)
    fdate2 = request.args.get('fdate2', datetime.utcnow().strftime('%Y-%m-%d'))

    def parse_date(date_str):
        try:
            return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            try:
                return datetime.strptime(date_str, '%Y-%m-%d')
            except (ValueError, TypeError):
                return datetime.utcnow()

    date1 = parse_date(fdate1)
    date2 = parse_date(fdate2)
    date2 = date2.replace(hour=23, minute=59, second=59)

    if current_user.is_client():
        cdr_query = SMSCDR.query.filter(
            SMSCDR.client_id == current_user.id,
            SMSCDR.created_at >= date1,
            SMSCDR.created_at <= date2
        )
    else:
        cdr_query = SMSCDR.query.filter(
            SMSCDR.user_id == current_user.id,
            SMSCDR.created_at >= date1,
            SMSCDR.created_at <= date2
        )

    frange = request.args.get('frange', '')
    if frange:
        cdr_query = cdr_query.filter_by(range_id=frange)

    if not current_user.is_client() and not current_user.is_test_account():
        fclient = request.args.get('fclient', '')
        if fclient:
            cdr_query = cdr_query.filter_by(client_id=fclient)

    fnum = request.args.get('fnum', '')
    if fnum:
        cdr_query = cdr_query.join(SMSNumber).filter(SMSNumber.number.like(f'%{fnum}%'))

    cdr_query = cdr_query.order_by(SMSCDR.created_at.desc())

    if request.args.get('export') and not current_user.is_test_account():
        output = io.StringIO()
        writer = csv.writer(output)
        header = ['Date', 'Range', 'Number', 'CLI']
        if not current_user.is_client() and not current_user.is_test_account():
            header.append('Client')
        header.append('SMS')
        if not current_user.is_test_account():
            header.append('Agent Payout' if not current_user.is_client() else 'OTP Price')
        writer.writerow(header)

        for cdr in cdr_query.all():
            row = [
                cdr.created_at.strftime('%Y-%m-%d %H:%M:%S') if cdr.created_at else '',
                (cdr.range_info.name if cdr.range_info and cdr.range_info.name else (cdr.range_info.country if cdr.range_info else '')),
                cdr.sms_number.number if cdr.sms_number else '',
                cdr.cli or ''
            ]
            if not current_user.is_client() and not current_user.is_test_account():
                if cdr.client:
                    row.append(cdr.client.username)
                elif cdr.agent:
                    row.append(f'{cdr.agent.username} (agent)')
                else:
                    row.append('')
            msg = cdr.message or ''
            if current_user.is_test_account():
                msg = mask_codes(msg)
            row.append(msg)
            if not current_user.is_test_account():
                row.append(cdr.agent_payout if not current_user.is_client() else cdr.client_payout)
            writer.writerow(row)

        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=sms_cdr_report.csv'}
        )

    cdr_records = cdr_query.paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Totals must mirror whatever filters (range/client/number) are applied
    # to the table above, otherwise the summary cards show whole-period
    # numbers while the table shows a filtered subset.
    if current_user.is_client():
        totals_query = db.session.query(
            func.count(SMSCDR.id).label('total_sms'),
            func.sum(SMSCDR.client_payout).label('total_client')
        ).filter(
            SMSCDR.client_id == current_user.id,
            SMSCDR.created_at >= date1,
            SMSCDR.created_at <= date2
        )
    else:
        totals_query = db.session.query(
            func.count(SMSCDR.id).label('total_sms'),
            func.sum(SMSCDR.agent_payout).label('total_payout'),
            func.sum(SMSCDR.client_payout).label('total_client')
        ).filter(
            SMSCDR.user_id == current_user.id,
            SMSCDR.created_at >= date1,
            SMSCDR.created_at <= date2
        )

    if frange:
        totals_query = totals_query.filter(SMSCDR.range_id == frange)

    if not current_user.is_client() and not current_user.is_test_account():
        fclient = request.args.get('fclient', '')
        if fclient:
            totals_query = totals_query.filter(SMSCDR.client_id == fclient)

    if fnum:
        totals_query = totals_query.join(SMSNumber).filter(SMSNumber.number.like(f'%{fnum}%'))

    totals = totals_query.first()

    ranges = SMDRange.query.filter_by(is_active=True).all()
    clients = User.query.filter_by(agent_id=current_user.id).all() if (not current_user.is_client() and not current_user.is_test_account()) else []

    # The Test123 account is a shared public demo — mask the OTP digits in
    # the message text (in memory only, never written back to the DB) so
    # real one-time codes can't be read/used by random visitors.
    if current_user.is_test_account():
        for cdr in cdr_records.items:
            cdr.message = mask_codes(cdr.message)

    return render_template('main/sms_cdr_reports.html',
        cdr_records=cdr_records,
        totals=totals,
        ranges=ranges,
        clients=clients,
        fdate1=fdate1,
        fdate2=fdate2
    )


@main_bp.route('/agent/Clients')
@login_required
def clients():
    if current_user.is_client():
        flash('Access denied!', 'danger')
        return redirect(url_for('main.dashboard'))
    page = request.args.get('page', 1, type=int)
    clients_list = User.query.filter_by(agent_id=current_user.id).order_by(
        User.created_at.desc()
    ).paginate(page=page, per_page=25, error_out=False)
    return render_template('main/clients.html', clients=clients_list)


@main_bp.route('/agent/CreateClient', methods=['GET', 'POST'])
@login_required
def create_client():
    if current_user.is_client():
        flash('Access denied!', 'danger')
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        name = request.form.get('name')
        company = request.form.get('company')
        contact = request.form.get('contact')
        country = request.form.get('country')

        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'danger')
            return redirect(url_for('main.create_client'))

        if User.query.filter_by(email=email).first():
            flash('Email already exists!', 'danger')
            return redirect(url_for('main.create_client'))

        client_role = Role.query.filter_by(name='client').first()
        new_client = User(
            username=username,
            email=email,
            name=name,
            company=company,
            contact=contact,
            country=country,
            role=client_role,
            agent_id=current_user.id,
            is_active=True
        )
        new_client.set_password(password)
        db.session.add(new_client)
        db.session.commit()
        flash('Client created successfully!', 'success')
        return redirect(url_for('main.clients'))

    return render_template('main/create_client.html')


@main_bp.route('/agent/Profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        if current_user.is_test_account():
            flash('This is a shared public demo account (Test123) used by everyone — the password and profile cannot be changed.', 'danger')
            return redirect(url_for('main.profile'))
        action = request.form.get('action')
        if action == 'change_password':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            if not current_user.check_password(current_password):
                flash('Current password is wrong!', 'danger')
            elif new_password != confirm_password:
                flash('New passwords do not match!', 'danger')
            elif len(new_password) < 6:
                flash('Password must be at least 6 characters!', 'danger')
            else:
                current_user.set_password(new_password)
                db.session.commit()
                flash('Password changed successfully!', 'success')
        else:
            current_user.name = request.form.get('name')
            current_user.company = request.form.get('company')
            current_user.email = request.form.get('email')
            current_user.skype = request.form.get('skype')
            current_user.contact = request.form.get('contact')
            current_user.country = request.form.get('country')
            current_user.address = request.form.get('address')
            db.session.commit()
            flash('Profile updated successfully.', 'success')
        return redirect(url_for('main.profile'))
    return render_template('main/profile.html')


@main_bp.route('/agent/MyActivity')
@login_required
def my_activity():
    if current_user.is_test_account():
        flash('Not available on the shared Test account.', 'warning')
        return redirect(url_for('main.dashboard'))
    from app.models.activity import ActivityLog
    page = request.args.get('page', 1, type=int)
    activities = ActivityLog.query.filter_by(user_id=current_user.id).order_by(
        ActivityLog.created_at.desc()
    ).paginate(page=page, per_page=50, error_out=False)
    return render_template('main/my_activity.html', activities=activities)


@main_bp.route('/agent/Notifications')
@login_required
def notifications():
    return render_template('main/notifications.html')


@main_bp.route('/agent/cr-api')
@login_required
def cr_api():
    if current_user.is_test_account():
        flash('The Test account has no API access.', 'warning')
        return redirect(url_for('main.dashboard'))
    if current_user.is_client():
        flash('Client accounts do not have API access.', 'warning')
        return redirect(url_for('main.dashboard'))
    if not current_user.api_token:
        current_user.generate_api_token()
        db.session.commit()
    base_url = request.url_root.rstrip('/') + url_for('api.cdr_viewstats')
    return render_template('main/cr_api.html', base_url=base_url)


@main_bp.route('/agent/cr-api/regenerate', methods=['POST'])
@login_required
def cr_api_regenerate():
    current_user.generate_api_token()
    db.session.commit()
    flash('A new API token has been generated.', 'success')
    return redirect(url_for('main.cr_api'))

# ── Admin: Manage all users' API tokens ──────────────────────────────────────
@main_bp.route('/admin/api-manage')
@login_required
def admin_api_manage():
    from app.models.user import User
    if not current_user.is_admin():
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    users = User.query.filter(User.is_active == True).all()
    # make sure every user has a token
    changed = False
    for u in users:
        if not u.api_token:
            u.generate_api_token()
            changed = True
    if changed:
        db.session.commit()
    base_url = request.url_root.rstrip('/') + url_for('api.cdr_viewstats')
    return render_template('main/admin_api_manage.html', users=users, base_url=base_url)


@main_bp.route('/admin/api-manage/regenerate/<int:user_id>', methods=['POST'])
@login_required
def admin_api_regenerate(user_id):
    from app.models.user import User
    if not current_user.is_admin():
        flash('Access denied.', 'danger')
        return redirect(url_for('main.dashboard'))
    u = User.query.get_or_404(user_id)
    u.generate_api_token()
    db.session.commit()
    flash(f'New token generated for {u.username}.', 'success')
    return redirect(url_for('main.admin_api_manage'))
