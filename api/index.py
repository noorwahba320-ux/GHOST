"""Vercel WSGI entrypoint. Database schema is managed with migrations, not at request startup."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app

app = create_app(os.environ.get('FLASK_CONFIG', 'production'))
