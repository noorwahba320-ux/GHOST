"""
Vercel entrypoint.
Vercel's Python runtime looks for a WSGI/ASGI callable named `app` (or a
handler) inside /api/*.py and routes matching requests to it. We just
import and expose the existing Flask app factory output here — no
duplicate app logic lives in this file.
"""
import os
import sys

# Make the project root importable (this file lives in /api).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db

app = create_app(os.environ.get('FLASK_CONFIG', 'production'))

# Vercel's filesystem is read-only except /tmp, and each invocation may hit
# a fresh instance, so db.create_all() here just ensures tables exist on a
# freshly-provisioned external database (Postgres) — it's a no-op once
# they already exist.
with app.app_context():
    db.create_all()
