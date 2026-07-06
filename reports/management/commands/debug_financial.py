"""
Debug command: complete analysis of a Codal financial report.

Usage:
    python manage.py debug_financial <tracking_id>
    python manage.py debug_financial <tracking_id> --raw

Finds the announcement, fetches its report page(s),
extracts datasource, and shows detailed structure info.

The --raw flag dumps the full raw datasource JSON.
"""

import json
import sys

from django.core.management.base import BaseCommand

from reports.models import Announcement
from reports.services import (
    extract_datasource,
    _build_sheet_urls,
    _normalize_persian,
    parse_financial_report,
)


class Command(BaseCommand):
    help = "تحلیل کامل ساختار گزارش مالی کدال (برای دیباگ)"

    def add_arguments(self, parser):
        parser.add_argument("tracking_id", type=int, help="شناسه رهگیری اطلاعیه")
        parser.add_argument(
            "--raw", action="store_true",
            help="_dump کامل datasource JSON",
        )

    def handle(self, *args, **options):
        tid = options["tracking_id"]
        dump_raw = options["raw"]

        # ─── Find announcement ───
        try:
            ann = Announcement.objects.get(tracking_id=tid)
        except Announcement.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"اطلاعیه {tid} در دیتابیس نیست"))
            return

        self.stdout.write(f"{'='*70}")
        self.stdout.write(f"عنوان:  {ann.title[:80]}")
        self.stdout.write(f"نماد:   {ann.symbol}")
        self.stdout.write(f"کد:     {ann.letter_code}")
        self.stdout.write(f"لینک:   {ann.direct_link[:120]}")
        self.stdout.write(f"{'='*70}")
        self.stdout.write("")

        # ─── Show what URLs will be tried ───
        is_decision = "Decision.aspx" in ann.direct_link
        self.stdout.write(self.style.HTTP_INFO(
            f"نوع صفحه: {'Decision.aspx ✅' if is_decision else 'سایر'}"
        ))

        if is_decision:
            sheet_urls = _build_sheet_urls(ann.direct_link, max_sheet_id=5)
            self.stdout.write(f"URLهای sheetId که امتحان می‌شوند:")
            for sid, url in sheet_urls:
                self.stdout.write(f"  sheetId={sid}: {url[:120]}")
        self.stdout.write("")

        # ─── Fetch datasource ───
        self.stdout.write(self.style.HTTP_INFO("در حال دریافت datasource..."))
        try:
            ds = extract_datasource(ann.direct_link)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"خطا: {type(e).__name__}: {e}"))
            return

        # ─── Top-level datasource info ───
        self.stdout.write(self.style.SUCCESS(f"✅ datasource دریافت شد"))
        self.stdout.write(f"  عنوان:     {ds.get('title_Fa', '(ندارد)')}")
        self.stdout.write(f"  دوره:      {ds.get('periodEndToDate', '(ندارد)')}")
        self.stdout.write(f"  پایان سال: {ds.get('yearEndToDate', '(ندارد)')}")
        self.stdout.write(f"  حسابرسی:   {'بله' if ds.get('isAudited') else 'خیر'}")
        self.stdout.write(f"  تلفیقی:    {'بله' if ds.get('isConsolidated') else 'خیر'}")
        self.stdout.write(f"  تعداد شیت‌ها: {len(ds.get('sheets', []))}")
        self.stdout.write("")

        if dump_raw:
            self.stdout.write(self.style.HTTP_INFO("── Raw JSON ──"))
            self.stdout.write(json.dumps(ds, ensure_ascii=False, indent=2))
            return

        # ─── Sheet-by-sheet analysis ───
        for si, sheet in enumerate(ds.get("sheets", [])):
            code = sheet.get("code", "?")
            title = sheet.get("title_Fa", "(بدون عنوان)")
            tables = sheet.get("tables", [])
            total_cells = sum(len(t.get("cells", [])) for t in tables)

            self.stdout.write(self.style.HTTP_INFO(f"{'─'*60}"))
            self.stdout.write(
                f"  شیت {si} | code={code} | {title}"
            )
            self.stdout.write(
                f"  {len(tables)} جدول | {total_cells} سلول"
            )
            self.stdout.write(self.style.HTTP_INFO(f"{'─'*60}"))

            for ti, table in enumerate(tables):
                table_title = table.get("title_Fa", "")
                cells = table.get("cells", [])
                if not cells:
                    self.stdout.write(self.style.WARNING(
                        f"    جدول {ti}: (بدون سلول) {table_title}"
                    ))
                    continue

                # Structure analysis
                has_addr = sum(1 for c in cells if c.get("address"))
                has_cc = sum(1 for c in cells if c.get("columnCode") is not None)
                has_pet = sum(1 for c in cells if c.get("periodEndToDate"))
                has_yet = sum(1 for c in cells if c.get("yearEndToDate"))
                has_fc = sum(1 for c in cells if c.get("financialConcept"))

                self.stdout.write(
                    f"    جدول {ti}: {table_title or '(بدون عنوان)'}"
                    f" | {len(cells)} سلول"
                )
                self.stdout.write(
                    f"      address={has_addr} columnCode={has_cc} "
                    f"periodEndToDate={has_pet} yearEndToDate={has_yet} "
                    f"financialConcept={has_fc}"
                )

                # Show first 3 cells raw
                self.stdout.write(f"      ── نمونه سلول‌ها ──")
                for ci, cell in enumerate(cells[:5]):
                    cc = cell.get("columnCode")
                    addr = cell.get("address", "")
                    val = str(cell.get("value", ""))[:50]
                    pet = str(cell.get("periodEndToDate", ""))[:30]
                    yet = str(cell.get("yearEndToDate", ""))[:30]
                    rt = cell.get("rowTypeName", "")
                    rc = cell.get("rowCode")
                    fc = cell.get("financialConcept")

                    self.stdout.write(
                        f"      [{ci}] addr={addr} cc={cc} rt={rt} rc={rc}"
                    )
                    self.stdout.write(f"           value={val}")
                    self.stdout.write(f"           pet={pet}  yet={yet}")
                    if fc:
                        self.stdout.write(f"           fc={fc}")

            self.stdout.write("")

        # ─── Parse and show result summary ───
        self.stdout.write(self.style.HTTP_INFO(f"{'='*60}"))
        self.stdout.write(self.style.HTTP_INFO("── نتیجه پارسینگ ──"))
        self.stdout.write(self.style.HTTP_INFO(f"{'='*60}"))

        parsed = parse_financial_report(ds)
        for sheet in parsed.get("sheets", []):
            cat = sheet.get("category", "?")
            title = sheet.get("title", "")[:40]
            rows_count = sum(len(t.get("rows", [])) for t in sheet.get("tables", []))
            rows_with_data = sum(
                1 for t in sheet.get("tables", [])
                for r in t.get("rows", [])
                if r.get("period_value") is not None or r.get("year_value") is not None
            )
            self.stdout.write(
                f"  [{cat:>10}] {title} → {rows_count} ردیف "
                f"({rows_with_data} با عدد)"
            )