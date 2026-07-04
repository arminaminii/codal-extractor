import logging
import re
from datetime import datetime, timezone

import requests
from django.conf import settings

from .models import Announcement

logger = logging.getLogger(__name__)

# --- URL و هدرهای ثابت API کدال ---
CODAL_SEARCH_URL = "https://search.codal.ir/api/search/v2/q"

DEFAULT_QUERY_PARAMS = {
    "Publisher": "false",
    "Category": "-1",
    "CompanyState": "-1",
    "CompanyType": "-1",
    "AuditorRef": "-1",
    "PageChanging": "true",
    "AuditType": "-1",
    "Consolidatable": "true",
    "NotAudited": "true",
    "IsNotAudited": "false",
    "Childs": "true",
    "Mains": "true",
    "TracingNo": "-1",
    "CompanySearchType": "0",
    "SymbolSearchType": "0",
    "LetterType": "-1",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://codal.ir/",
    "Origin": "https://codal.ir",
}


def _parse_codal_date(date_str: str) -> datetime | None:
    """
    تاریخ کدال در فرمت /Date(1234567890000)/ برمی‌گرداند.
    این تابع آن را به شیء datetime تبدیل می‌کند.
    """
    if not date_str:
        return None

    match = re.search(r"\((\d+)", date_str)
    if match:
        timestamp_ms = int(match.group(1))
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    return None


def _build_direct_link(symbol: str, letter_code: str, tracing_no: int) -> str:
    """
    ساخت لینک مستقیم هر گزارش بر اساس الگوی URL کدال.
    """
    return (
        f"https://codal.ir/ReportList.aspx?"
        f"search&Symbol={symbol}"
        f"&LetterCode={letter_code}"
        f"&CompanyState=-1"
        f"&CompanyType=-1"
        f"&PageNumber=1"
        f"&AuditorRef=-1"
        f"&PageChanging=true"
        f"&Category=-1"
        f"&Length=-1"
        f"&AuditType=-1"
        f"&NotAudited=false"
        f"&IsNotAudited=true"
        f"&Childs=true"
        f"&Mains=true"
        f"&TracingNo={tracing_no}"
    )


def fetch_announcements_from_codal(symbol: str, length: int = 50, page: int = 1) -> list[dict]:
    """
    ارسال درخواست به API کدال و دریافت لیست اطلاعیه‌ها.

    Args:
        symbol: نام نماد بورسی (مثلاً "فولاد")
        length: تعداد نتایج درخواستی (پیش‌فرض ۵۰)
        page: شماره صفحه (پیش‌فرض ۱)

    Returns:
        لیست دیکشنری‌های حاوی اطلاعات اطلاعیه‌ها

    Raises:
        requests.RequestException: در صورت بروز خطای شبکه
        ValueError: در صورت نامعتبر بودن پاسخ
    """
    params = {
        **DEFAULT_QUERY_PARAMS,
        "Symbol": symbol,
        "Length": str(length),
        "PageNumber": str(page),
    }

    logger.info("ارسال درخواست به API کدال برای نماد: %s", symbol)

    response = requests.get(
        CODAL_SEARCH_URL,
        params=params,
        headers=HEADERS,
        timeout=getattr(settings, "CODAL_REQUEST_TIMEOUT", 30),
    )
    response.raise_for_status()

    data = response.json()

    if "Letters" not in data:
        logger.warning("پاسخ API کدال فیلد Letters ندارد. پاسخ: %s", str(data)[:200])
        return []

    letters = data.get("Letters", [])
    results = []

    for item in letters:
        tracing_no = item.get("TracingNo")
        if not tracing_no:
            continue

        publish_date = _parse_codal_date(item.get("PublishDateTime", ""))

        letter_code = item.get("LetterCode", "")

        # ساخت لینک مستقیم
        direct_link = _build_direct_link(
            symbol=symbol,
            letter_code=letter_code,
            tracing_no=tracing_no,
        )

        # اگر URL مستقیم در پاسخ وجود داشت، آن را جایگزین کن
        if item.get("Url"):
            direct_link = item["Url"]

        results.append(
            {
                "tracking_id": tracing_no,
                "symbol": symbol,
                "title": item.get("Title", item.get("Subject", "")),
                "publish_date": publish_date,
                "direct_link": direct_link,
                "letter_code": letter_code,
            }
        )

    logger.info("دریافت %d اطلاعیه برای نماد %s از API کدال", len(results), symbol)
    return results


def save_announcements_to_db(announcements_data: list[dict]) -> int:
    """
    ذخیره یا بروزرسانی اطلاعیه‌ها در دیتابیس با استفاده از bulk_create / update_or_create.

    Args:
        announcements_data: لیست دیکشنری‌های خروجی تابع fetch_announcements_from_codal

    Returns:
        تعداد رکوردهای ذخیره/بروزرسانی شده
    """
    if not announcements_data:
        return 0

    saved_count = 0

    for item in announcements_data:
        _, created = Announcement.objects.update_or_create(
            tracking_id=item["tracking_id"],
            defaults={
                "symbol": item["symbol"],
                "title": item["title"],
                "publish_date": item["publish_date"],
                "direct_link": item["direct_link"],
                "letter_code": item.get("letter_code", ""),
            },
        )
        if created:
            saved_count += 1

    logger.info(
        "ذخیره/بروزرسانی %d رکورد جدید از مجموع %d اطلاعیه",
        saved_count,
        len(announcements_data),
    )
    return saved_count


def get_or_fetch_announcements(symbol: str) -> list[Announcement]:
    """
    تابع اصلی: ابتدا دیتابیس را چک می‌کند.
    اگر رکوردی وجود نداشت یا قدیمی بود، از API کدال می‌گیرد و ذخیره می‌کند.

    Args:
        symbol: نام نماد بورسی

    Returns:
        لیست آبجکت‌های Announcement از دیتابیس
    """
    # ۱. بررسی دیتابیس
    existing = Announcement.objects.filter(symbol=symbol).order_by("-publish_date")

    if existing.exists():
        logger.info(
            "یافت شد %d رکورد موجود در دیتابیس برای نماد %s",
            existing.count(),
            symbol,
        )
        return list(existing)

    # ۲. استخراج از API کدال
    logger.info("رکوردی در دیتابیس یافت نشد. استخراج از کدال برای نماد: %s", symbol)

    try:
        announcements_data = fetch_announcements_from_codal(symbol)
    except requests.RequestException as e:
        logger.error("خطا در ارتباط با API کدال: %s", str(e))
        raise

    # ۳. ذخیره در دیتابیس
    save_announcements_to_db(announcements_data)

    # ۴. خواندن از دیتابیس و بازگرداندن
    return list(
        Announcement.objects.filter(symbol=symbol).order_by("-publish_date")
    )