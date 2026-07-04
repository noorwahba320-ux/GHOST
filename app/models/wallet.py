from app import db
from app.models.sms import SMSCDR
from datetime import datetime
from sqlalchemy import case, func


class Wallet(db.Model):
    __tablename__ = 'wallets'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    balance = db.Column(db.Float, default=0.0)
    total_earned = db.Column(db.Float, default=0.0)
    total_withdrawn = db.Column(db.Float, default=0.0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('wallet', uselist=False))

    def __repr__(self):
        return f'<Wallet user_id={self.user_id} balance={self.balance}>'

    @staticmethod
    def get_or_create(user_id):
        wallet = Wallet.query.filter_by(user_id=user_id).first()
        if not wallet:
            wallet = Wallet(user_id=user_id, balance=0.0)
            db.session.add(wallet)
            db.session.commit()
        return wallet


class WithdrawalRequest(db.Model):
    __tablename__ = 'withdrawal_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(50))
    account_details = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')   # pending / approved / rejected / paid
    admin_note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime)

    user = db.relationship('User', backref='withdrawal_requests')

    def __repr__(self):
        return f'<WithdrawalRequest user_id={self.user_id} amount={self.amount} status={self.status}>'


# ---------------------------------------------------------------
# REAL-TIME BALANCE ENGINE
# agent earning per CDR row = client_payout (if number was assigned
# to a client) else agent_payout (Admin range payout)
# ---------------------------------------------------------------

def get_agent_total_earning(agent_id):
    """Sum of real earning across ALL CDR rows for this agent."""
    earning_expr = case(
        (SMSCDR.client_id.isnot(None), SMSCDR.client_payout),
        else_=SMSCDR.agent_payout
    )
    total = db.session.query(func.sum(earning_expr)).filter(
        SMSCDR.user_id == agent_id
    ).scalar()
    return total or 0.0


def get_agent_withdrawn_total(agent_id):
    """Sum of approved + paid withdrawal requests (money already out)."""
    total = db.session.query(func.sum(WithdrawalRequest.amount)).filter(
        WithdrawalRequest.user_id == agent_id,
        WithdrawalRequest.status.in_(['approved', 'paid'])
    ).scalar()
    return total or 0.0


def get_agent_pending_withdrawal_total(agent_id):
    """Sum of pending withdrawal requests (locked, not yet deducted)."""
    total = db.session.query(func.sum(WithdrawalRequest.amount)).filter(
        WithdrawalRequest.user_id == agent_id,
        WithdrawalRequest.status == 'pending'
    ).scalar()
    return total or 0.0


def get_agent_balance(agent_id):
    """
    Live available balance = total earning - already withdrawn (approved/paid)
    Pending requests are NOT subtracted here, they are shown separately
    so the agent can see what's locked vs what's still free to request.
    """
    earning = get_agent_total_earning(agent_id)
    withdrawn = get_agent_withdrawn_total(agent_id)
    return round(earning - withdrawn, 4)


def get_agent_available_balance(agent_id):
    """Balance minus whatever is currently locked in a pending request."""
    balance = get_agent_balance(agent_id)
    pending = get_agent_pending_withdrawal_total(agent_id)
    return round(balance - pending, 4)