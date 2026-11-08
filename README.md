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

### پیش‌نیازها

- Git
- Python 3.12 یا جدیدتر
- دسترسی اینترنت برای نصب وابستگی‌ها و دریافت اطلاعات از کدال

فایل `db.sqlite3` در مخزن Git نگهداری نمی‌شود. در هر نصب تازه، دستورات
زیر دیتابیس را می‌سازند و فهرست شرکت‌ها را از فایل داخلی پروژه وارد می‌کنند.

### Windows PowerShell

```powershell
git clone https://github.com/arminaminii/codal-extractor.git
cd codal-extractor

git switch main
git pull --ff-only

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py populate_companies
.\.venv\Scripts\python.exe manage.py check

$env:DJANGO_DEBUG = "True"
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

### Linux / macOS

```bash
git clone https://github.com/arminaminii/codal-extractor.git
cd codal-extractor

git switch main
git pull --ff-only

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python manage.py migrate
python manage.py populate_companies
python manage.py check

export DJANGO_DEBUG=True
python manage.py runserver 127.0.0.1:8000
```

پس از اجرا، سامانه در آدرس زیر در دسترس است:

```text
http://127.0.0.1:8000/
```

### به‌روزرسانی یک نسخه موجود

در پوشه پروژه اجرا کنید:

#### Windows PowerShell

```powershell
git switch main
git pull --ff-only

.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check

$env:DJANGO_DEBUG = "True"
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

#### Linux / macOS

```bash
git switch main
git pull --ff-only

source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py check

export DJANGO_DEBUG=True
python manage.py runserver 127.0.0.1:8000
```

### اجرای تست‌ها

در Windows:

```powershell
.\.venv\Scripts\python.exe manage.py test
```

در Linux یا macOS:

```bash
source .venv/bin/activate
python manage.py test
```

### ساخت کاربر مدیر (اختیاری)

در Windows:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

در Linux یا macOS:

```bash
python manage.py createsuperuser
```

> `DJANGO_DEBUG=True` و سرور `runserver` فقط برای توسعه محلی مناسب هستند و
> نباید با همین تنظیمات در محیط production استفاده شوند.

## نحوه کار

1. کاربر نام نماد (مثلاً «فولاد») را در فرم جستجو وارد می‌کند.
2. سامانه ابتدا دیتابیس محلی را بررسی می‌کند.
3. اگر اطلاعیه‌ای وجود نداشت، در لحظه از API کدال استخراج می‌کند.
4. داده‌ها در دیتابیس ذخیره شده و به کاربر نمایش داده می‌شوند.

## مجوز
MIT
