"""
app/routes/billing.py
Complete, self-contained blueprint for:
  - Agent: Bank/USDT Accounts, Payment Requests, Credit Notes, Statements
  - Admin: Bank Accounts (view), Payment Requests (approve/reject/paid), Credit Notes (view)
This file does NOT modify main.py or admin.py.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models.sms import SMSCDR
from app.models.user import User, Role
from app.models.billing import AgentBankAccount, CreditNote
from app.models.wallet import (
    WithdrawalRequest,
    get_agent_balance,
    get_agent_available_balance,
    get_agent_pending_withdrawal_total
)
from datetime import datetime
from functools import wraps

billing_bp = Blueprint('billing', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
        if not current_user.is_admin():
            flash('Admin access required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated


def agent_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login'))
        if not (current_user.is_agent() or current_user.is_admin()):
            flash('Access denied.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated


# ============================================================
# AGENT: BANK / USDT ACCOUNTS
# ============================================================

@billing_bp.route('/agent/BankAccounts', methods=['GET', 'POST'])
@agent_required
def bank_accounts():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            method = request.form.get('method', '').strip()
            label = request.form.get('label', '').strip()
            details = request.form.get('account_details', '').strip()
            if not method or not details:
                flash('Method and account details are required.', 'danger')
                return redirect(url_for('billing.bank_accounts'))
            acc = AgentBankAccount(
                agent_id=current_user.id,
                method=method,
                label=label,
                account_details=details
            )
            db.session.add(acc)
            db.session.commit()
            flash('Account added successfully!', 'success')

        elif action == 'edit':
            acc_id = request.form.get('account_id', type=int)
            acc = AgentBankAccount.query.filter_by(id=acc_id, agent_id=current_user.id).first()
            if acc:
                acc.method = request.form.get('method', acc.method).strip()
                acc.label = request.form.get('label', acc.label).strip()
                acc.account_details = request.form.get('account_details', acc.account_details).strip()
                db.session.commit()
                flash('Account updated successfully!', 'success')
            else:
                flash('Account not found.', 'danger')

        elif action == 'delete':
            acc_id = request.form.get('account_id', type=int)
            acc = AgentBankAccount.query.filter_by(id=acc_id, agent_id=current_user.id).first()
            if acc:
                db.session.delete(acc)
                db.session.commit()
                flash('Account deleted.', 'success')

        return redirect(url_for('billing.bank_accounts'))

    accounts = AgentBankAccount.query.filter_by(agent_id=current_user.id).order_by(
        AgentBankAccount.created_at.desc()
    ).all()
    return render_template('main/bank_accounts.html', accounts=accounts)


# ============================================================
# AGENT: PAYMENT REQUESTS
# ============================================================

@billing_bp.route('/agent/PaymentRequests', methods=['GET', 'POST'])
@agent_required
def payment_requests():
    if request.method == 'POST':
        amount = request.form.get('amount', 0.0, type=float)
        account_id = request.form.get('account_id', type=int)

        available = get_agent_available_balance(current_user.id)
        account = AgentBankAccount.query.filter_by(id=account_id, agent_id=current_user.id).first()

        if not account:
            flash('Please select a valid account.', 'danger')
        elif amount <= 0:
            flash('Enter a valid amount.', 'danger')
        elif amount > available:
            flash(f'Insufficient balance. Available: {available}', 'danger')
        else:
            wr = WithdrawalRequest(
                user_id=current_user.id,
                amount=amount,
                method=account.method,
                account_details=f"{account.label or account.method}: {account.account_details}",
                status='pending'
            )
            db.session.add(wr)
            db.session.commit()
            flash('Payment request submitted successfully!', 'success')

        return redirect(url_for('billing.payment_requests'))

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    requests_q = WithdrawalRequest.query.filter_by(user_id=current_user.id).order_by(
        WithdrawalRequest.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    accounts = AgentBankAccount.query.filter_by(agent_id=current_user.id).all()

    return render_template('main/payment_requests.html',
        requests=requests_q,
        accounts=accounts,
        balance=get_agent_balance(current_user.id),
        available=get_agent_available_balance(current_user.id),
        pending_locked=get_agent_pending_withdrawal_total(current_user.id)
    )


# ============================================================
# AGENT: CREDIT NOTES
# ============================================================

@billing_bp.route('/agent/CreditNotes')
@agent_required
def credit_notes():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    notes = CreditNote.query.filter_by(agent_id=current_user.id).order_by(
        CreditNote.issued_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    return render_template('main/credit_notes.html', notes=notes)


# ============================================================
# AGENT: STATEMENTS (full ledger)
# ============================================================

@billing_bp.route('/agent/Statements')
@agent_required
def statements():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    earnings = SMSCDR.query.filter_by(user_id=current_user.id).order_by(SMSCDR.created_at.desc()).all()
    withdrawals = WithdrawalRequest.query.filter(
        WithdrawalRequest.user_id == current_user.id,
        WithdrawalRequest.status.in_(['approved', 'paid'])
    ).order_by(WithdrawalRequest.created_at.desc()).all()

    ledger = []
    for e in earnings:
        ledger.append({
            'date': e.created_at,
            'description': f'OTP earning - {e.destination or e.cli or "number"}',
            'credit': e.agent_payout or 0.0,
            'debit': 0.0
        })
    for w in withdrawals:
        ledger.append({
            'date': w.processed_at or w.created_at,
            'description': f'Withdrawal ({w.method}) - {w.status}',
            'credit': 0.0,
            'debit': w.amount or 0.0
        })

    chrono = sorted(ledger, key=lambda x: x['date'])
    running = 0.0
    for row in chrono:
        running += row['credit'] - row['debit']
        row['running_balance'] = round(running, 4)
    ledger = list(reversed(chrono))

    total = len(ledger)
    start = (page - 1) * per_page
    end = start + per_page
    page_items = ledger[start:end]

    class SimplePagination:
        def __init__(self, items, page, per_page, total):
            self.items = items
            self.page = page
            self.per_page = per_page
            self.total = total
            self.pages = max(1, (total + per_page - 1) // per_page)
            self.has_prev = page > 1
            self.has_next = page < self.pages
            self.prev_num = page - 1
            self.next_num = page + 1

        def iter_pages(self):
            return range(1, self.pages + 1)

    pagination = SimplePagination(page_items, page, per_page, total)

    return render_template('main/statements.html',
        pagination=pagination,
        current_balance=get_agent_balance(current_user.id)
    )


# ============================================================
# ADMIN: BANK / USDT ACCOUNTS (read-only, all agents)
# ============================================================

@billing_bp.route('/admin/BankAccounts')
@admin_required
def admin_bank_accounts():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    query = AgentBankAccount.query.join(User, AgentBankAccount.agent_id == User.id)
    fagent = request.args.get('fagent', '')
    if fagent:
        query = query.filter(AgentBankAccount.agent_id == fagent)

    accounts = query.order_by(AgentBankAccount.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    agents = User.query.join(Role).filter(Role.name == 'agent').all()

    return render_template('admin/bank_accounts.html', accounts=accounts, agents=agents)


# ============================================================
# ADMIN: PAYMENT REQUESTS (approve / reject / mark paid)
# ============================================================

@billing_bp.route('/admin/PaymentRequests', methods=['GET', 'POST'])
@admin_required
def admin_payment_requests():
    if request.method == 'POST':
        req_id = request.form.get('request_id', type=int)
        new_status = request.form.get('status', '').strip()
        admin_note = request.form.get('admin_note', '').strip()

        wr = WithdrawalRequest.query.get(req_id)
        if not wr:
            flash('Request not found.', 'danger')
            return redirect(url_for('billing.admin_payment_requests'))

        if new_status not in ['approved', 'rejected', 'paid']:
            flash('Invalid status.', 'danger')
            return redirect(url_for('billing.admin_payment_requests'))

        wr.status = new_status
        wr.admin_note = admin_note
        wr.processed_at = datetime.utcnow()
        db.session.commit()
        flash(f'Request #{wr.id} marked as {new_status}.', 'success')
        return redirect(url_for('billing.admin_payment_requests'))

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    query = WithdrawalRequest.query.join(User, WithdrawalRequest.user_id == User.id)
    fstatus = request.args.get('fstatus', '')
    if fstatus:
        query = query.filter(WithdrawalRequest.status == fstatus)
    fagent = request.args.get('fagent', '')
    if fagent:
        query = query.filter(WithdrawalRequest.user_id == fagent)

    requests_q = query.order_by(WithdrawalRequest.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    agents = User.query.join(Role).filter(Role.name == 'agent').all()
    pending_count = WithdrawalRequest.query.filter_by(status='pending').count()

    return render_template('admin/payment_requests.html',
        requests=requests_q, agents=agents, pending_count=pending_count
    )


# ============================================================
# ADMIN: CREDIT NOTES (view only, auto-generated by scheduler)
# ============================================================

@billing_bp.route('/admin/CreditNotes')
@admin_required
def admin_credit_notes():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    query = CreditNote.query.join(User, CreditNote.agent_id == User.id)
    fagent = request.args.get('fagent', '')
    if fagent:
        query = query.filter(CreditNote.agent_id == fagent)

    notes = query.order_by(CreditNote.issued_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    agents = User.query.join(Role).filter(Role.name == 'agent').all()

    return render_template('admin/credit_notes.html', notes=notes, agents=agents)


@billing_bp.route('/admin/CreditNotes/<int:note_id>/mark-paid', methods=['POST'])
@admin_required
def admin_credit_note_mark_paid(note_id):
    note = CreditNote.query.get(note_id)
    if note:
        note.status = 'paid'
        db.session.commit()
        flash(f'Credit Note #{note.id} marked as paid.', 'success')
    return redirect(url_for('billing.admin_credit_notes'))