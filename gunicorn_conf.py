import os
import multiprocessing

# البورت بييجي من متغير البيئة PORT (موجود في .env)، ولو مش موجود بيشتغل على 5000
port = os.environ.get('PORT') or os.environ.get('SERVER_PORT') or '5000'
domain = os.environ.get('DOMAIN', '').strip()
bind = f"0.0.0.0:{port}"

workers = int(os.environ.get('WEB_CONCURRENCY', multiprocessing.cpu_count() * 2 + 1))
timeout = 120

accesslog = os.environ.get('GUNICORN_ACCESS_LOG', 'logs/access.log')
errorlog = os.environ.get('GUNICORN_ERROR_LOG', 'logs/error.log')
loglevel = 'info'
capture_output = True


def on_starting(server):
    url = f"http://{domain}:{port}" if domain else f"http://<SERVER_IP>:{port}"
    server.log.info("=========================================")
    server.log.info(f"Power SMS Panel is UP and RUNNING -> PORT={port} | DOMAIN={domain or 'not set'} | URL={url}")
    server.log.info(f"Bind address: {bind}")
    server.log.info("=========================================")
