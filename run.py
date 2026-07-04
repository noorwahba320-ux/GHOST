#!/usr/bin/env python3

from app import create_app, db
import os
import logging

os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    filename='logs/app.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)

app = create_app(os.environ.get('FLASK_CONFIG', 'production'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("FLASH SMS is ready!")

    port = int(os.environ.get('PORT') or os.environ.get('SERVER_PORT') or 5000)
    domain = (os.environ.get('DOMAIN') or '').strip()
    url = f"http://{domain}:{port}" if domain else f"http://<SERVER_IP>:{port}"

    startup_msg = f"FLASH SMS Panel is UP and RUNNING -> PORT={port} | DOMAIN={domain or 'not set'} | URL={url}"
    print(startup_msg)
    logging.info(startup_msg)

    app.run(host='0.0.0.0', port=port, debug=False)