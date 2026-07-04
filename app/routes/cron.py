"""
app/routes/cron.py
On a normal server, app/__init__.py starts an in-process APScheduler that
runs generate_weekly_credit_notes() and auto_reclaim_inactive_numbers()
every 24h. Vercel functions have no persistent process, so that scheduler
can't run there. Instead, these same jobs are exposed as an HTTP endpoint
that Vercel Cron calls once a day (see vercel.json's "crons" section).

The endpoint is protected with a shared secret (CRON_SECRET env var) so
random people on the internet can't trigger it.
"""
import os
from flask import Blueprint, request, jsonify, current_app

cron_bp = Blueprint('cron', __name__, url_prefix='/api/cron')


@cron_bp.route('/daily', methods=['GET', 'POST'])
def run_daily_jobs():
    expected_secret = os.environ.get('CRON_SECRET')
    provided = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
    if not provided:
        provided = request.args.get('secret', '')

    if expected_secret and provided != expected_secret:
        return jsonify({'error': 'unauthorized'}), 401

    from app.scheduler_jobs import generate_weekly_credit_notes
    from app.routes.admin import auto_reclaim_inactive_numbers

    results = {}
    try:
        generate_weekly_credit_notes(current_app._get_current_object())
        results['credit_notes'] = 'ok'
    except Exception as e:
        results['credit_notes'] = f'error: {e}'

    try:
        auto_reclaim_inactive_numbers(current_app._get_current_object())
        results['auto_reclaim'] = 'ok'
    except Exception as e:
        results['auto_reclaim'] = f'error: {e}'

    return jsonify(results)
