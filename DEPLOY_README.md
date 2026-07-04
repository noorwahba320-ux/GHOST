# تشغيل Power SMS Panel على VPS / دومين

## 1) رفع المشروع على السيرفر
```bash
scp -r Power-SMS-panel-main root@YOUR_SERVER_IP:/opt/
ssh root@YOUR_SERVER_IP
cd /opt/Power-SMS-panel-main
```

## 2) تثبيت المتطلبات (لو أول مرة)
```bash
apt update
apt install -y python3 python3-venv python3-pip nginx
```

## 3) التركيب
```bash
chmod +x deploy.sh
./deploy.sh
nano .env      # عدّل PORT و SECRET_KEY و DATABASE_URL
```

## 4) معرفة/تحديد البورت من اللوج
البورت بيتحدد من `.env` (المتغير `PORT`). أول ما تشغّل السيرفر، gunicorn هيسجل رقم البورت في اللوج تلقائيًا:
```bash
source venv/bin/activate
gunicorn -c gunicorn_conf.py run:app
```
هتلاقي في `logs/error.log` سطر زي ده:
```
Power SMS Panel - starting on PORT = 5000
```
ده هو رقم البورت اللي السيرفر شغال عليه فعليًا — استخدمه في nginx.

## 5) تشغيله كخدمة دايمة (systemd)
عدّل المسارات جوه `power-sms.service` (فيه CHANGE_ME) وبعدين:
```bash
cp power-sms.service /etc/systemd/system/power-sms.service
systemctl daemon-reload
systemctl enable power-sms
systemctl start power-sms
systemctl status power-sms
journalctl -u power-sms -f      # متابعة اللوج لحظيًا، هتشوف رقم البورت هنا كمان
```

## 6) ربط الدومين عبر nginx
عدّل `nginx_power-sms.conf`:
- غيّر `YOUR_DOMAIN.com` لدومينك
- غيّر رقم البورت `127.0.0.1:5000` ليطابق نفس PORT اللي في `.env`

```bash
cp nginx_power-sms.conf /etc/nginx/sites-available/power-sms
ln -s /etc/nginx/sites-available/power-sms /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx
```

## 7) تفعيل SSL (اختياري لكن موصى به)
```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d YOUR_DOMAIN.com
```

## ملاحظات
- تسجيل الدخول الافتراضي: `admin / admin123` — **غيّره فورًا** بعد أول دخول.
- لو غيّرت PORT في `.env`، لازم تحدّث نفس الرقم في `nginx_power-sms.conf` وتعمل `systemctl restart power-sms nginx`.
- قاعدة البيانات الافتراضية SQLite (`abyss_sms.db`)، لو عايز PostgreSQL غيّر `DATABASE_URL` في `.env`.
