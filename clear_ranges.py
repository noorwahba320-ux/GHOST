#!/usr/bin/env python3
"""
سكريبت لمسح جميع SMS Ranges القديمة (بيانات التجربة) من غير ما يأثر
على المستخدمين أو أي بيانات تانية في اللوحة.

الاستخدام (من الكونسول):
    python3 clear_ranges.py
"""
from app import create_app, db
from app.models.sms import SMDRange

app = create_app()

with app.app_context():
    count = SMDRange.query.count()
    if count == 0:
        print("مفيش رينجات محفوظة أصلًا.")
    else:
        SMDRange.query.delete()
        db.session.commit()
        print(f"تم حذف {count} رينج بنجاح.")
