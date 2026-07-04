from app import db
from datetime import datetime

class Provider(db.Model):
    __tablename__ = 'providers'
    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(100), unique=True, nullable=False)
    url            = db.Column(db.String(200), nullable=False)
    ptype          = db.Column(db.String(50), nullable=False)
    username       = db.Column(db.String(100), nullable=False)
    password       = db.Column(db.String(100), nullable=False)
    fetch_interval = db.Column(db.Integer, default=10)
    is_active      = db.Column(db.Boolean, default=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

class OTPLog(db.Model):
    __tablename__ = 'otp_logs'
    id          = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('providers.id'))
    number      = db.Column(db.String(50), nullable=False)
    otp         = db.Column(db.String(20), nullable=False)
    sender      = db.Column(db.String(100))
    message     = db.Column(db.Text)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    number_id   = db.Column(db.Integer, db.ForeignKey('sms_numbers.id'), nullable=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    provider    = db.relationship('Provider', backref='otp_logs')
    sms_number  = db.relationship('SMSNumber', foreign_keys=[number_id])
    user        = db.relationship('User', foreign_keys=[user_id])