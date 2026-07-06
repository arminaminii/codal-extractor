"""
Debug command: show all raw financial concept names from a Codal report.

Usage:
    python manage.py debug_financial <tracking_id>

Finds the announcement, fetches its report page, extracts datasource,
and lists ALL concept names found in each sheet so we can update aliases.
"""

import json

from django.core.management.base import BaseCommand

from reports.models import Announcement
from reports.services import extract_datasource, _normalize_persian


class Command(BaseCommand):
    help = "نمایش مفاهیم مالی خام از یک گزارش کدال (برای عیب‌یابی alias‌ها)"

    def add_arguments(self, parser):
        parser.add_argument("tracking_id", type=int, help="شناسه رهگیری اطلاعیه")

    def handle(self, *args, **options):
        tid = options["tracking_id"]

        # ─── Find announcement ───
        try:
            ann = Announcement.objects.get(tracking_id=tid)
        except Announcement.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"اطلاعیه {tid} در دیتابیس نیست"))
            return

        self.stdout.write(f"عنوان: {ann.title[:80]}")
        self.stdout.write(f"نماد:  {ann.symbol}")
        self.stdout.write(f"لینک:  {ann.direct_link[:100]}")
        self.stdout.write(f"کد نامه: {ann.letter_code}")
        self.stdout.write("")

        # ─── Fetch datasource ───
        self.stdout.write("در حال دریافت datasource ...")
        try:
            ds = extract_datasource(ann.direct_link)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"خطا: {type(e).__name__}: {e}"))
            return

        self.stdout.write(self.style.SUCCESS(f"✅ datasource دریافت شد"))
        self.stdout.write(f"تعداد شیت‌ها: {len(ds.get('sheets', []))}")
        self.stdout.write("")

        # ─── Show raw cell keys for first cell ───
        self.stdout.write(self.style.HTTP_INFO("── کلیدهای سلول اول (برای بررسی ساختار) ──"))
        for sheet in ds.get("sheets", []):
            for table in sheet.get("tables", []):
                for cell in table.get("cells", [])[:1]:
                    for key, val in cell.items():
                        val_str = str(val)[:80]
                        self.stdout.write(f"  {key}: {val_str}")
                    self.stdout.write("")
                break
            break

        # ─── List all concepts per sheet ───
        for sheet in ds.get("sheets", []):
            code = sheet.get("code", "?")
            title = sheet.get("title_Fa", "(بدون عنوان)")
            self.stdout.write(self.style.HTTP_INFO(f"{'='*60}"))
            self.stdout.write(f"  شیت {code}: {title}")
            self.stdout.write(self.style.HTTP_INFO(f"{'='*60}"))

            for ti, table in enumerate(sheet.get("tables", [])):
                table_title = table.get("title_Fa", "")
                if table_title:
                    self.stdout.write(f"  ── جدول: {table_title}")

                cells = table.get("cells", [])
                if not cells:
                    self.stdout.write(self.style.WARNING("    (سلولی یافت نشد)"))
                    continue

                # Check structure
                has_addr = any(c.get("address") for c in cells)
                has_cc = any(c.get("columnCode") is not None for c in cells)
                self.stdout.write(f"    ساختار: address={'✓' if has_addr else '✗'} columnCode={'✓' if has_cc else '✗'} ({len(cells)} سلول)")

                concepts = set()
                for cell in cells:
                    val = cell.get("value") or ""
                    fc = cell.get("financialConcept") or ""
                    cc = cell.get("columnCode")
                    label = fc or (val if cc == 1 else "")
                    if label:
                        concepts.add(_normalize_persian(label))

                for c in sorted(concepts):
                    self.stdout.write(f"    • {c}")

                if not concepts:
                    self.stdout.write(self.style.WARNING("    (مفهومی یافت نشد)"))

            self.stdout.write("")

        # ─── Also show raw JSON of first 3 cells for inspection ───
        self.stdout.write(self.style.HTTP_INFO("── نمونه سلول‌های خام (اول ۳ تا) ──"))
        count = 0
        for sheet in ds.get("sheets", []):
            for table in sheet.get("tables", []):
                for cell in table.get("cells", []):
                    if count >= 3:
                        break
                    self.stdout.write(json.dumps(cell, ensure_ascii=False, indent=2))
                    self.stdout.write("")
                    count += 1
                if count >= 3:
                    break
            if count >= 3:
                break