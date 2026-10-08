import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise RuntimeError('SECRET_KEY must be configured in the deployment environment')
    db_url = os.environ.get('DATABASE_URL', 'sqlite:///flash_sms.db')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True, 'pool_recycle': 300}
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600
    LOGIN_ATTEMPT_LIMIT = 5
    LOGIN_ATTEMPT_WINDOW = 300
    CAPTCHA_ENABLED = True
    ITEMS_PER_PAGE = 25

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False

class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = 'test-only-secret-key'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

config = {'development': DevelopmentConfig, 'production': ProductionConfig, 'testing': TestingConfig, 'default': DevelopmentConfig}
