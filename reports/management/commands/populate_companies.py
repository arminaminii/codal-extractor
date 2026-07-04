import json
from pathlib import Path

from django.core.management.base import BaseCommand

from reports.models import Company


class Command(BaseCommand):
    help = "پر کردن جدول شرکت‌ها از فایل data/companies.json (منبع: sahebi/tse GitHub)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=None,
            help="مسیر فایل JSON. پیش‌فرض: reports/data/companies.json",
        )

    def handle(self, *args, **options):
        # مسیر فایل
        default_path = Path(__file__).resolve().parent.parent.parent / "data" / "companies.json"
        file_path = Path(options["file"]) if options["file"] else default_path

        if not file_path.exists():
            self.stderr.write(self.style.ERROR(f"فایل {file_path} یافت نشد!"))
            return

        # خواندن JSON
        with open(file_path, "r", encoding="utf-8") as f:
            companies_data = json.load(f)

        # پاک‌سازی قبلی
        Company.objects.all().delete()
        self.stdout.write("تمام رکوردهای قبلی پاک شدند.")

        # ساخت آبجکت‌ها
        company_objects = []
        seen_symbols = set()
        for item in companies_data:
            symbol = item.get("symbol", "").strip()
            if not symbol or symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)

            company_objects.append(Company(
                symbol=symbol,
                name=item.get("name", "").strip(),
                sector=item.get("sector", "").strip(),
                sector_icon=item.get("sector_icon", ""),
            ))

        # ذخیره
        Company.objects.bulk_create(company_objects)

        # آمار
        sector_counts = {}
        for c in company_objects:
            sector_counts[c.sector] = sector_counts.get(c.sector, 0) + 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"✅ {len(company_objects)} شرکت از فایل ایجاد شدند."))
        self.stdout.write(f"   منبع: {file_path.name}")
        self.stdout.write("")
        self.stdout.write("=== توزیع صنایع ===")
        for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1]):
            self.stdout.write(f"   {count:4d}  |  {sector}")