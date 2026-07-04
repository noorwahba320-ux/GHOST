from app import db
from datetime import datetime


class AgentBankAccount(db.Model):
    __tablename__ = 'agent_bank_accounts'

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    method = db.Column(db.String(30), nullable=False)   # USDT / Bank / Other
    label = db.Column(db.String(100))                    # e.g. "Binance USDT (TRC20)"
    account_details = db.Column(db.Text, nullable=False)  # address / account no / etc.

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    agent = db.relationship('User', backref='bank_accounts')

    def __repr__(self):
        return f'<AgentBankAccount agent_id={self.agent_id} method={self.method}>'

    def to_dict(self):
        return {
            'id': self.id,
            'method': self.method,
            'label': self.label,
            'account_details': self.account_details,
            'is_active': self.is_active,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


class CreditNote(db.Model):
    __tablename__ = 'credit_notes'

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    period_start = db.Column(db.DateTime, nullable=False)
    period_end = db.Column(db.DateTime, nullable=False)

    amount = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(10), default='USDT')

    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=False)

    status = db.Column(db.String(20), default='pending')   # pending / paid
    remarks = db.Column(db.String(255))

    agent = db.relationship('User', backref='credit_notes')

    def __repr__(self):
        return f'<CreditNote agent_id={self.agent_id} amount={self.amount} status={self.status}>'

    def to_dict(self):
        return {
            'id': self.id,
            'period_start': self.period_start.strftime('%Y-%m-%d'),
            'period_end': self.period_end.strftime('%Y-%m-%d'),
            'amount': self.amount,
            'currency': self.currency,
            'issued_at': self.issued_at.strftime('%Y-%m-%d %H:%M:%S'),
            'due_date': self.due_date.strftime('%Y-%m-%d'),
            'status': self.status,
            'remarks': self.remarks
        }