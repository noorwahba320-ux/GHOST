"""
app/scheduler_jobs.py
Weekly auto Credit Note generator.
Runs a daily check; for each agent, if 7 days have passed since their
last credit note period ended (or since they joined, if no note yet),
it creates a new Credit Note covering that 7-day window.
Due date = generation date + 7 days.
"""

from datetime import datetime, timedelta
from app import db
from app.models.user import User, Role
from app.models.sms import SMSCDR
from app.models.billing import CreditNote


def generate_weekly_credit_notes(app):
    with app.app_context():
        agents = User.query.join(Role).filter(Role.name == 'agent').all()
        now = datetime.utcnow()

        for agent in agents:
            last_note = CreditNote.query.filter_by(agent_id=agent.id).order_by(
                CreditNote.period_end.desc()
            ).first()

            period_start = last_note.period_end if last_note else agent.created_at
            if not period_start:
                period_start = now - timedelta(days=7)

            if (now - period_start).days < 7:
                continue

            period_end = period_start + timedelta(days=7)

            total = db.session.query(db.func.sum(SMSCDR.agent_payout)).filter(
                SMSCDR.user_id == agent.id,
                SMSCDR.created_at >= period_start,
                SMSCDR.created_at < period_end
            ).scalar() or 0.0

            note = CreditNote(
                agent_id=agent.id,
                period_start=period_start,
                period_end=period_end,
                amount=round(total, 4),
                currency='USDT',
                issued_at=now,
                due_date=now + timedelta(days=7),
                status='pending'
            )
            db.session.add(note)

        db.session.commit()