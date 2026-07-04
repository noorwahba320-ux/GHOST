from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from app.models.activity import ActivityLog
from datetime import datetime, timedelta
from functools import wraps
import re
import secrets

auth_bp = Blueprint('auth', __name__)

# Single-device session enforcement for client accounts (Test123 exempt).
# If no heartbeat is seen from the active device for this long, its session
# is considered dead and a new login is allowed through normally.
SESSION_STALE_MINUTES = 20
# Cooldown enforced after a same-account login collision is detected,
# including right after the original device logs out.
CONCURRENT_LOCK_MINUTES = 5

# Rate limiting decorator
def rate_limit(max_attempts=5, window=300):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            ip = request.remote_addr
            key = f'login_attempts:{ip}'

            # Simple in-memory rate limiting
            if not hasattr(rate_limit, 'attempts'):
                rate_limit.attempts = {}

            now = datetime.utcnow()
            if key in rate_limit.attempts:
                attempts, first_attempt = rate_limit.attempts[key]
                if now - first_attempt < timedelta(seconds=window):
                    if attempts >= max_attempts:
                        flash('Too many login attempts. Please try again later.', 'danger')
                        return redirect(url_for('auth.login'))
                    # Increment counter for this attempt
                    rate_limit.attempts[key] = (attempts + 1, first_attempt)
                else:
                    # Window expired — reset counter
                    rate_limit.attempts[key] = (1, now)
            else:
                rate_limit.attempts[key] = (1, now)

            return f(*args, **kwargs)
        return decorated_function
    return decorator

@auth_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        captcha = request.form.get('capt', '')

        # Validate required fields
        if not username or not password:
            flash('Please enter username and password.', 'danger')
            return render_template('auth/login.html')

        # Generate captcha question
        captcha_num1 = session.get('captcha_num1', 0)
        captcha_num2 = session.get('captcha_num2', 0)
        correct_answer = session.get('captcha_answer', 0)

        # Verify captcha
        try:
            if int(captcha) != correct_answer:
                flash('Incorrect captcha answer. Please try again.', 'danger')
                import random
                session['captcha_num1'] = random.randint(1, 9)
                session['captcha_num2'] = random.randint(1, 9)
                session['captcha_answer'] = session['captcha_num1'] + session['captcha_num2']
                return render_template('auth/login.html')
        except ValueError:
            flash('Invalid captcha. Please enter a number.', 'danger')
            import random
            session['captcha_num1'] = random.randint(1, 9)
            session['captcha_num2'] = random.randint(1, 9)
            session['captcha_answer'] = session['captcha_num1'] + session['captcha_num2']
            return render_template('auth/login.html')

        # Find user
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if not user.is_active:
                flash('Your account has been deactivated.', 'warning')
                return render_template('auth/login.html')

            # Check if account is locked
            if user.locked_until and user.locked_until > datetime.utcnow():
                flash('Your account is locked. Please try again later.', 'danger')
                return render_template('auth/login.html')

            # Single-device enforcement for client accounts (Test123 exempt)
            if user.is_client() and not user.is_test_account():
                now = datetime.utcnow()

                # Cooldown from a previous collision (also covers: the active
                # device just logged out and someone immediately retries)
                if user.concurrent_lock_until and user.concurrent_lock_until > now:
                    remaining = max(1, int((user.concurrent_lock_until - now).total_seconds() // 60) + 1)
                    flash(f'This account is already in use on another device. Please try again in {remaining} minute(s).', 'danger')
                    return render_template('auth/login.html')

                # Another device currently has a live session
                session_is_live = (
                    user.active_session_token and user.active_session_last_seen and
                    (now - user.active_session_last_seen) < timedelta(minutes=SESSION_STALE_MINUTES)
                )
                if session_is_live:
                    user.concurrent_lock_until = now + timedelta(minutes=CONCURRENT_LOCK_MINUTES)
                    db.session.commit()
                    flash(f'This account is already logged in on another device. Please try again in {CONCURRENT_LOCK_MINUTES} minutes.', 'danger')
                    return render_template('auth/login.html')

            # Ensure api_token exists (the Test123 demo account is excluded —
            # it never gets API access)
            if not user.api_token and not user.is_test_account():
                user.generate_api_token()

            # Reset login attempts
            user.login_attempts = 0
            user.locked_until = None
            user.last_login = datetime.utcnow()
            db.session.commit()

            # Log activity
            ActivityLog.log(
                user.id,
                'login',
                f'User logged in',
                ip_address=request.remote_addr,
                user_agent=request.user_agent.string
            )

            # Claim this device as the account's single active session
            if user.is_client() and not user.is_test_account():
                device_token = secrets.token_urlsafe(32)
                user.active_session_token = device_token
                user.active_session_last_seen = datetime.utcnow()
                user.concurrent_lock_until = None
                db.session.commit()
                session['device_token'] = device_token

            login_user(user, remember=False)
            session.permanent = False
            session['play_welcome_voice'] = True

            flash(f'Welcome {user.username}!', 'success')

            # Redirect to next page or dashboard
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            return redirect(url_for('main.dashboard'))

        else:
            # Handle failed login
            if user:
                user.login_attempts += 1
                if user.login_attempts >= 5:
                    user.locked_until = datetime.utcnow() + timedelta(minutes=15)
                    flash('Too many failed attempts. Account locked for 15 minutes.', 'danger')
                else:
                    remaining = 5 - user.login_attempts
                    flash(f'Invalid credentials. {remaining} attempts remaining.', 'danger')
                db.session.commit()
            else:
                flash('Invalid username or password.', 'danger')

    # Generate new captcha
    import random
    session['captcha_num1'] = random.randint(1, 9)
    session['captcha_num2'] = random.randint(1, 9)
    session['captcha_answer'] = session['captcha_num1'] + session['captcha_num2']

    return render_template('auth/login.html')

@auth_bp.route('/logout', methods=['GET','POST'])
@login_required
def logout():
    user_id = current_user.id

    # Release this device's claim on the account's single active session.
    # Only clear it if it's actually this device's token — never touch a
    # collision cooldown (concurrent_lock_until) here, it must survive logout.
    if current_user.is_client() and not current_user.is_test_account():
        if current_user.active_session_token and current_user.active_session_token == session.get('device_token'):
            current_user.active_session_token = None
            current_user.active_session_last_seen = None
            db.session.commit()

    logout_user()
    session.clear()

    # Best-effort activity log — must never block or fail the actual logout
    try:
        ActivityLog.log(
            user_id,
            'logout',
            f'User logged out',
            ip_address=request.remote_addr
        )
    except Exception:
        db.session.rollback()

    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        # Validation
        errors = []

        if len(username) < 6:
            errors.append('Username must be at least 6 characters.')
        if not re.match(r'^[A-Za-z0-9_]+$', username):
            errors.append('Username can only contain letters, numbers, and underscores.')

        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
            errors.append('Please enter a valid email address.')

        if len(password) < 6:
            errors.append('Password must be at least 6 characters.')
        if password != password_confirm:
            errors.append('Passwords do not match.')

        if User.query.filter_by(username=username).first():
            errors.append('Username already exists.')

        if User.query.filter_by(email=email).first():
            errors.append('Email already registered.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('auth/register.html')

        # Create user
        from app.models.user import Role
        client_role = Role.query.filter_by(name='client').first()

        # إذا ما وجد role، أنشئه
        if not client_role:
            client_role = Role(
                name='client',
                display_name='Client',
                permissions='[]'
            )
            db.session.add(client_role)
            db.session.commit()

        user = User(
            username=username,
            email=email,
            role_id=client_role.id,
            is_active=True
        )
        user.set_password(password)
        user.generate_api_token()

        db.session.add(user)
        db.session.commit()

        ActivityLog.log(
            user.id,
            'register',
            f'New user registered',
            ip_address=request.remote_addr
        )

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')

# Error handlers
@auth_bp.app_errorhandler(401)
def unauthorized(e):
    flash('Please log in to access this page.', 'warning')
    return redirect(url_for('auth.login', next=request.path))

@auth_bp.app_errorhandler(403)
def forbidden(e):
    flash('You do not have permission to access this page.', 'danger')
    return redirect(url_for('main.dashboard'))

@auth_bp.app_errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404

@auth_bp.app_errorhandler(500)
def server_error(e):
    db.session.rollback()
    flash('An internal error occurred. Please try again later.', 'danger')
    return redirect(url_for('main.dashboard'))
