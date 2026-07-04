# سامانه استخراج در لحظه (On-Demand) اطلاعیه‌های کدال

## معرفی
این سامانه یک اپلیکیشن مبتنی بر فریم‌ورک Django است که با دریافت نام یک نماد بورسی از کاربر، اطلاعیه‌های آن را از سایت کدال استخراج کرده و نمایش می‌دهد.

## معماری سیستم

```
کاربر (جستجوی نماد) 
    → بررسی دیتابیس (SQLite)
        → اگر وجود داشت: نمایش از دیتابیس
        → اگر نبود: درخواست به API کدال → ذخیره در دیتابیس → نمایش
```

## پشته تکنولوژی
- **فریم‌ورک:** Django 6
- **پایگاه داده:** SQLite (قابل ارتقا)
- **ارتباط شبکه:** requests
- **مدیریت داده:** Django ORM

## ساختار پروژه
```
codal-extractor/
├── codal_project/          # تنظیمات اصلی پروژه
│   ├── settings.py         # تنظیمات Django
│   ├── urls.py             # URL اصلی
│   └── wsgi.py
├── reports/                # اپلیکیشن اصلی
│   ├── models.py           # مدل Announcement
│   ├── services.py         # سرویس استخراج از کدال
│   ├── views.py            # لایه نمایش
│   ├── urls.py             # URL اپلیکیشن
│   ├── admin.py            # پنل ادمین
│   └── migrations/         # فایل‌های مهاجرت
├── templates/              # تمپلیت‌ها
│   ├── base.html           # تمپلیت پایه
│   └── reports/
│       └── search.html     # صفحه جستجو
├── static/                 # فایل‌های استاتیک
│   └── css/
│       └── style.css       # استایل‌ها
├── db.sqlite3              # پایگاه داده
├── requirements.txt        # وابستگی‌ها
└── manage.py
```

## نصب و راه‌اندازی

### ۱. کلون کردن پروژه
```bash
git clone https://github.com/arminaminii/codal-extractor.git
cd codal-extractor
```

### ۲. ساخت محیط مجازی و نصب وابستگی‌ها
```bash
python -m venv venv
source venv/bin/activate  # لینوکس/مک
pip install -r requirements.txt
```

### ۳. اجرای مهاجرت‌ها
```bash
python manage.py migrate
```

### ۴. ایجاد ادمین (اختیاری)
```bash
python manage.py createsuperuser
```

### ۵. اجرای سرور توسعه
```bash
python manage.py runserver
```

سپس مرورگر را باز کنید و به `http://127.0.0.1:8000` بروید.

## نحوه کار

1. کاربر نام نماد (مثلاً «فولاد») را در فرم جستجو وارد می‌کند.
2. سامانه ابتدا دیتابیس محلی را بررسی می‌کند.
3. اگر اطلاعیه‌ای وجود نداشت، در لحظه از API کدال استخراج می‌کند.
4. داده‌ها در دیتابیس ذخیره شده و به کاربر نمایش داده می‌شوند.

## مجوز
MIT