#!/bin/bash
set -e

APP_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$APP_DIR"

echo "==> إنشاء virtual environment"
python3 -m venv venv
source venv/bin/activate

echo "==> تثبيت المكتبات"
pip install --upgrade pip
pip install -r requirements.txt

echo "==> إنشاء فولدر اللوجات"
mkdir -p logs

if [ ! -f .env ]; then
    echo "==> إنشاء ملف .env من القالب"
    cp .env.example .env
    echo "!! لازم تعدّل ملف .env دلوقتي (خصوصًا PORT و SECRET_KEY) قبل ما تكمل"
fi

echo ""
echo "==> خلصت التثبيت."
echo "شغّل السيرفر يدويًا للتجربة بالأمر ده:"
echo "  source venv/bin/activate && gunicorn -c gunicorn_conf.py run:app"
echo ""
echo "البورت اللي هيشتغل عليه هيبان في logs/error.log على شكل:"
echo "  Power SMS Panel - starting on PORT = XXXX"
