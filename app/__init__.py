import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from sqlalchemy import event
from sqlalchemy.engine import Engine
from config import config

db = SQLAlchemy()
login_manager = LoginManager()
bcrypt = Bcrypt()


# ── Fix: "database is locked" 500 errors ──────────────────────────────────
# The app runs many background threads (one per SMS provider + the
# scheduler jobs) that all write to the same SQLite file concurrently with
# normal web requests. SQLite's default locking mode + a short busy timeout
# means any overlap raises "database is locked", which the 500 handler
# turns into "An internal error occurred" and can also make an authenticated
# request fail mid-flight (looking like a random logout). WAL mode lets
# readers and a writer work at the same time, and a longer busy_timeout
# makes writers wait instead of failing immediately.
@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    if type(dbapi_connection).__module__.startswith('sqlite3'):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    db.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)
    CORS(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please login to continue.'
    login_manager.login_message_category = 'warning'

    from app.models.user import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.developer import dev_bp
    from app.routes.sms_monitor import monitor_bp
    from app.routes.provider import provider_bp
    from app.routes.billing import billing_bp
    from app.routes.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(dev_bp)
    app.register_blueprint(monitor_bp)
    app.register_blueprint(provider_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.before_request
    def _enforce_live_session():
        """Kill the session immediately if the logged-in user was deleted
        or deactivated by an admin, instead of letting the stale cookie
        keep them logged in until it naturally expires.

        Also enforces single-device sessions for client accounts (Test123
        exempt): if another device has since taken over the account's
        active session, this stale device is logged out too. Otherwise,
        it sends a lightweight heartbeat so this device's session isn't
        mistaken for dead by a login attempt from elsewhere.
        """
        from flask_login import current_user, logout_user
        from flask import session as flask_session
        from datetime import datetime
        if current_user.is_authenticated:
            from app.models.user import User
            fresh = User.query.get(current_user.id)
            if fresh is None or not fresh.is_active:
                logout_user()
                flask_session.clear()
                return

            if fresh.is_client() and not fresh.is_test_account():
                device_token = flask_session.get('device_token')
                if fresh.active_session_token and device_token != fresh.active_session_token:
                    # Another device has claimed the account; this one is stale.
                    logout_user()
                    flask_session.clear()
                elif device_token and fresh.active_session_token == device_token:
                    fresh.active_session_last_seen = datetime.utcnow()
                    db.session.commit()

    @app.after_request
    def _no_store_authenticated_pages(response):
        """Prevent the browser (esp. mobile) from serving a cached copy of
        an authenticated page via the back button after Sign Out."""
        from flask_login import current_user
        if getattr(current_user, 'is_authenticated', False):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
        return response

    @app.context_processor
    def inject_panel_settings():
        from app.models.settings import PanelSettings
        try:
            return {'panel_settings': PanelSettings.get()}
        except Exception:
            return {'panel_settings': None}

    @app.context_processor
    def inject_logo_url_helper():
        from flask import url_for as _url_for

        def logo_url(filename):
            """logo_filename is either a local path under static/img/uploads
            (older/non-serverless deploys) or a full https:// URL returned
            by Vercel Blob. Render whichever it is correctly."""
            if not filename:
                return ''
            if filename.startswith('http://') or filename.startswith('https://'):
                return filename
            return _url_for('static', filename='img/uploads/' + filename)

        return {'logo_url': logo_url}

    with app.app_context():
        db.create_all()

        # ── Lightweight column migration ────────────────────────────────
        # db.create_all() only creates tables that don't exist yet; it won't
        # add new columns to a table that already exists on disk. Cover the
        # `theme` column added to panel_settings so upgrades to existing
        # installs don't crash with "no such column: panel_settings.theme".
        try:
            from sqlalchemy import inspect as _sa_inspect, text as _sa_text
            inspector = _sa_inspect(db.engine)
            if 'panel_settings' in inspector.get_table_names():
                existing_cols = {c['name'] for c in inspector.get_columns('panel_settings')}
                if 'theme' not in existing_cols:
                    with db.engine.begin() as conn:
                        conn.execute(_sa_text(
                            "ALTER TABLE panel_settings ADD COLUMN theme VARCHAR(30) DEFAULT 'default'"
                        ))
                if 'test_account_max_numbers' not in existing_cols:
                    with db.engine.begin() as conn:
                        conn.execute(_sa_text(
                            "ALTER TABLE panel_settings ADD COLUMN test_account_max_numbers INTEGER DEFAULT 200"
                        ))

            # Single-device session enforcement columns on users
            if 'users' in inspector.get_table_names():
                existing_user_cols = {c['name'] for c in inspector.get_columns('users')}
                users_migrations = {
                    'active_session_token': "ALTER TABLE users ADD COLUMN active_session_token VARCHAR(64)",
                    'active_session_last_seen': "ALTER TABLE users ADD COLUMN active_session_last_seen DATETIME",
                    'concurrent_lock_until': "ALTER TABLE users ADD COLUMN concurrent_lock_until DATETIME",
                }
                with db.engine.begin() as conn:
                    for col_name, ddl in users_migrations.items():
                        if col_name not in existing_user_cols:
                            conn.execute(_sa_text(ddl))
        except Exception:
            pass

        from app.models.user import User, Role
        from app.models.sms import AgentRangeLimit
        from app.models.wallet import Wallet, WithdrawalRequest
        from app.models.billing import AgentBankAccount, CreditNote
        from app.models.settings import PanelSettings

        # Roles create
        for role_name, display in [
            ('admin', 'Administrator'),
            ('agent', 'Agent'),
            ('client', 'Client'),
            ('developer', 'Developer')
        ]:
            if not Role.query.filter_by(name=role_name).first():
                db.session.add(Role(name=role_name, display_name=display))
        db.session.commit()

        # Auto create admin
        admin_role = Role.query.filter_by(name='admin').first()
        DEFAULT_ADMIN_USERNAME = 'CraDiadev123'
        DEFAULT_ADMIN_PASSWORD = 'CraDiadev123'

        # One-time migration: an older deploy of this panel may already have
        # an admin row seeded with the old default username 'admin'. Rename
        # it (and reset its password) instead of creating a duplicate admin,
        # so existing installs pick up the new credentials on restart.
        legacy_admin = User.query.filter_by(username='admin').first()
        if legacy_admin and legacy_admin.is_admin():
            legacy_admin.username = DEFAULT_ADMIN_USERNAME
            legacy_admin.password_hash = bcrypt.generate_password_hash(DEFAULT_ADMIN_PASSWORD).decode('utf-8')
            db.session.commit()

        if not User.query.filter_by(username=DEFAULT_ADMIN_USERNAME).first():
            admin = User(
                username=DEFAULT_ADMIN_USERNAME,
                email='admin@panel.com',
                password_hash=bcrypt.generate_password_hash(DEFAULT_ADMIN_PASSWORD).decode('utf-8'),
                role=admin_role,
                is_active=True
            )
            db.session.add(admin)
            db.session.commit()

        # Auto create the public Test123 demo account — must always exist,
        # not just after an admin visits the Test Account settings page,
        # otherwise nobody can actually log in with it.
        # It intentionally never gets an api_token: it's a message-testing
        # account only, with no API access.
        agent_role = Role.query.filter_by(name='agent').first()
        if not User.query.filter_by(username='Test123').first():
            test_user = User(
                username='Test123',
                email='test@flashsms.internal',
                password_hash=bcrypt.generate_password_hash('Test123').decode('utf-8'),
                role=agent_role,
                is_active=True
            )
            db.session.add(test_user)
            db.session.commit()

        # ── Serverless (Vercel) guard ───────────────────────────────────
        # On Vercel each request is its own short-lived function instance
        # with no persistent process, so background threads (SMS provider
        # pollers) and an in-process APScheduler simply won't work — the
        # thread/scheduler dies the moment the request ends, and a new one
        # would be spun up on every single invocation, hammering the
        # provider panels. Vercel sets the VERCEL env var automatically,
        # so we use it to skip both here and expose them instead as HTTP
        # endpoints triggered by Vercel Cron (see routes/cron.py).
        IS_SERVERLESS = bool(os.environ.get('VERCEL'))

        if not IS_SERVERLESS:
            from app.fetcher import start_all_providers
            start_all_providers(app)

    # ---- Weekly Credit Note auto-generator (APScheduler) ----
    if not IS_SERVERLESS and (os.environ.get('WERKZEUG_RUN_MAIN') != 'true' or not app.debug):
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from app.scheduler_jobs import generate_weekly_credit_notes

            scheduler = BackgroundScheduler(daemon=True)
            from app.routes.admin import auto_reclaim_inactive_numbers
            scheduler.add_job(
                func=lambda: generate_weekly_credit_notes(app),
                trigger='interval',
                hours=24,
                id='weekly_credit_note_job',
                replace_existing=True
            )
            scheduler.add_job(
                func=lambda: auto_reclaim_inactive_numbers(app),
                trigger='interval',
                hours=24,
                id='auto_reclaim_inactive_job',
                replace_existing=True
            )
            scheduler.start()
        except Exception as e:
            print(f'Scheduler failed to start: {e}')

    if IS_SERVERLESS:
        from app.routes.cron import cron_bp
        app.register_blueprint(cron_bp)

    return app