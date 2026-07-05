"""
Debug command to test the full Codal API pipeline step by step.

Usage:
    python manage.py debug_codal فولاد
    python manage.py debug_codal خودرو
"""
import json

from django.core.management.base import BaseCommand

from reports.models import Company, Announcement
from reports.services import (
    _normalize_persian,
    fetch_announcements_from_codal,
    get_or_fetch_announcements,
)


class Command(BaseCommand):
    help = "عیب‌یابی گام‌به‌گام API کدال برای یه نماد"

    def add_arguments(self, parser):
        parser.add_argument("symbol", type=str, help="نماد شرکت (مثلاً فولاد)")

    def handle(self, *args, **options):
        symbol = options["symbol"].strip()

        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(f"  عیب‌یابی کدال برای نماد: {symbol}")
        self.stdout.write("=" * 60)
        self.stdout.write("")

        # ─── Step 1: Normalize ───
        self.stdout.write(self.style.HTTP_INFO("── قدم ۱: نرمالایز کردن نماد ──"))
        normalized = _normalize_persian(symbol)
        changed = symbol != normalized
        self.stdout.write(f"  قبل:  «{symbol}»")
        self.stdout.write(f"  بعد:  «{normalized}»")
        if changed:
            self.stdout.write(self.style.WARNING("  ⚠️  تغییر کرد! (حرف عربی بود)"))
        else:
            self.stdout.write(self.style.SUCCESS("  ✅ تغییر نکرد (درسته)"))
        self.stdout.write("")

        # ─── Step 2: DB Company ───
        self.stdout.write(self.style.HTTP_INFO("── قدم ۲: جستجوی شرکت در دیتابیس ──"))
        try:
            company = Company.objects.get(symbol=normalized)
            self.stdout.write(self.style.SUCCESS(f"  ✅ پیدا شد: {company.name}"))
            self.stdout.write(f"     صنعت: {company.sector}")
        except Company.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"  ❌ شرکت «{normalized}» در دیتابیس نیست!"))
            self.stdout.write(self.style.WARNING("  → اول populate_companies بزن"))
            return
        self.stdout.write("")

        # ─── Step 3: Raw API Call (to see exactly what Codal returns) ───
        self.stdout.write(self.style.HTTP_INFO("── قدم ۳: فراخوانی خام API کدال ──"))
        self.stdout.write(f"  در حال درخواست برای «{normalized}» ...")
        import requests
        from reports.services import CODAL_SEARCH_URL, DEFAULT_PARAMS, HEADERS
        raw_params = {**DEFAULT_PARAMS, "Symbol": normalized, "PageNumber": 1}
        try:
            raw_resp = requests.get(CODAL_SEARCH_URL, params=raw_params, headers=HEADERS, timeout=15)
            self.stdout.write(f"  Status Code: {raw_resp.status_code}")
            raw_data = raw_resp.json()
            raw_keys = list(raw_data.keys())
            self.stdout.write(f"  Response Keys: {raw_keys}")
            letters_raw = raw_data.get("Letters", [])
            self.stdout.write(f"  Letters Count: {len(letters_raw)}")
            if letters_raw:
                self.stdout.write(f"  First Letter:")
                self.stdout.write(f"    Title: {letters_raw[0].get('Title', '')[:80]}")
                self.stdout.write(f"    Symbol: {letters_raw[0].get('Symbol', '')}")
                self.stdout.write(f"    Code: {letters_raw[0].get('LetterCode', '')}")
            else:
                self.stdout.write(self.style.WARNING("  ⚠️  Letters خالیه! اول ۵۰۰ کاراکتر پاسخ:"))
                self.stdout.write(json.dumps(raw_data, ensure_ascii=False, indent=2)[:500])
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ خطا: {type(e).__name__}: {e}"))
            return
        self.stdout.write("")

        # ─── Step 3b: Full Pipeline Fetch ───
        self.stdout.write(self.style.HTTP_INFO("── قدم ۳‌ب: فراخوانی کامل لوله (fetch_announcements) ──"))
        try:
            results = fetch_announcements_from_codal(normalized)
            self.stdout.write(self.style.SUCCESS(f"  ✅ پاسخ دریافت شد: {len(results)} اطلاعیه"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ خطا: {type(e).__name__}: {e}"))
            return

        if results:
            self.stdout.write(f"  اولین نتیجه:")
            self.stdout.write(f"    عنوان: {results[0]['title'][:60]}...")
            self.stdout.write(f"    تاریخ: {results[0]['publish_date']}")
            self.stdout.write(f"    کد:    {results[0]['letter_code']}")
            self.stdout.write(f"    لینک:  {results[0]['direct_link'][:70]}...")
        else:
            self.stdout.write(self.style.WARNING("  ⚠️  API نتیجه‌ای برنگرداند (آرایه خالی)"))
        self.stdout.write("")

        # ─── Step 4: DB Save ───
        self.stdout.write(self.style.HTTP_INFO("── قدم ۴: ذخیره در دیتابیس ──"))
        if results:
            from reports.services import save_announcements_to_db
            saved = save_announcements_to_db(results)
            self.stdout.write(self.style.SUCCESS(f"  ✅ {saved} رکورد جدید ذخیره شد"))
        else:
            self.stdout.write(self.style.WARNING("  ⏭️  نتیجه‌ای برای ذخیره نیست"))
        self.stdout.write("")

        # ─── Step 5: Full Pipeline ───
        self.stdout.write(self.style.HTTP_INFO("── قدم ۵: تست لوله کامل (get_or_fetch) ──"))
        try:
            announcements = get_or_fetch_announcements(normalized, force_refresh=True)
            self.stdout.write(self.style.SUCCESS(f"  ✅ {len(announcements)} اطلاعیه از دیتابیس خوانده شد"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ❌ خطا: {e}"))
            return

        # ─── Summary ───
        self.stdout.write("")
        self.stdout.write("=" * 60)
        db_count = Announcement.objects.filter(symbol=normalized).count()
        self.stdout.write(self.style.SUCCESS(
            f"  نتیجه نهایی: {db_count} اطلاعیه برای «{normalized}» در دیتابیس"
        ))
        self.stdout.write("=" * 60)