from app import db
from datetime import datetime


class PanelSettings(db.Model):
    """Singleton row (id=1) holding white-label branding for the panel."""
    __tablename__ = 'panel_settings'

    id = db.Column(db.Integer, primary_key=True)
    panel_name = db.Column(db.String(100), default='FLASH SMS')
    logo_filename = db.Column(db.String(255))  # stored under app/static/img/uploads/
    primary_color = db.Column(db.String(9), default='#4f46e5')   # --accent
    secondary_color = db.Column(db.String(9), default='#38bdf8')  # --accent-light
    theme = db.Column(db.String(30), default='default')  # panel-wide visual theme, see THEMES
    test_account_max_numbers = db.Column(db.Integer, default=200)  # cap on numbers the Test account may hold
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Available panel themes: each is a fully different look (palette + card
    # style), not just a color swap. Keyed by the value stored in `theme`.
    THEMES = {
        'default': {
            'label': 'Flash (Default)',
            'desc': 'The classic indigo/cyan Flash SMS look.',
            'swatch': ['#0a0e27', '#4f46e5', '#38bdf8'],
        },
        'midnight': {
            'label': 'Midnight',
            'desc': 'Deep black-blue, violet accents. Flat & sharp: square corners, no shadows, glowing left-border cards.',
            'swatch': ['#05070f', '#8b5cf6', '#22d3ee'],
        },
        'sunset': {
            'label': 'Sunset',
            'desc': 'Warm charcoal, orange/pink accents. Soft & rounded: pill-shaped cards with a gentle amber glow.',
            'swatch': ['#1a1210', '#f97316', '#ec4899'],
        },
        'emerald': {
            'label': 'Emerald',
            'desc': 'Slate background, green/teal accents. Calm & minimal: completely flat cards with a slim top accent bar.',
            'swatch': ['#0b1512', '#10b981', '#34d399'],
        },
        'crimson': {
            'label': 'Crimson',
            'desc': 'Near-black, red/amber accents. Bold & dramatic: sharp corners, heavy shadow, extra-bold headers.',
            'swatch': ['#120707', '#dc2626', '#f59e0b'],
        },
        'light': {
            'label': 'Daylight',
            'desc': 'Clean white theme, indigo/cyan accents. Soft daylight shadows and generous rounding for bright rooms.',
            'swatch': ['#f3f4f6', '#4338ca', '#0ea5e9'],
        },
    }

    @staticmethod
    def get():
        settings = PanelSettings.query.get(1)
        if not settings:
            settings = PanelSettings(id=1)
            db.session.add(settings)
            db.session.commit()
        return settings
