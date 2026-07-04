import logging
import re
from datetime import datetime, timezone

import requests
from django.conf import settings
from django.db import models as db_models

from .models import Announcement, Company

logger = logging.getLogger(__name__)

# --- آدرس API کدال (بر اساس کتابخانه codalpy و codaler) ---
CODAL_SEARCH_URL = "https://search.codal.ir/api/search/v2/q"

# --- پارامترهای پیش‌فرض (بر اساس سورس‌کد واقعی codalpy) ---
# مرجع: https://github.com/yghaderi/codalpy/blob/master/codalpy/utils/query.py
DEFAULT_PARAMS = {
    "Category": -1,
    "PublisherType": 1,        # ناشران — این پارامتر الزامی است
    "LetterType": -1,
    "Audited": True,
    "NotAudited": True,
    "Mains": True,
    "Childs": False,
    "Consolidatable": True,
    "NotConsolidatable": True,
    "AuditorRef": -1,
    "CompanyState": 0,         # 0 = فعال
    "CompanyType": -1,
    "TracingNo": -1,
    "Publisher": False,
    "IsNotAudited": False,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/112.0.0.0 Safari/537.36"
    ),
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


def fetch_announcements_from_codal(
    symbol: str, length: int = -1, page: int = 1
) -> list[dict]:
    """
    ارسال درخواست GET به API کدال و دریافت لیست اطلاعیه‌ها.

    مرجع: https://github.com/yghaderi/codalpy
    مرجع: https://github.com/mostafaasadi/codaler

    Args:
        symbol: نام نماد بورسی (مثلاً "فولاد")
        length: تعداد نتایج درخواستی (پیش‌فرض -1 = همه)
        page: شماره صفحه (پیش‌فرض ۱)

    Returns:
        لیست دیکشنری‌های حاوی اطلاعات اطلاعیه‌ها

    Raises:
        requests.RequestException: در صورت بروز خطای شبکه
    """
    params = {
        **DEFAULT_PARAMS,
        "Symbol": symbol,
        "Length": length,
        "PageNumber": page,
    }

    logger.info(
        "ارسال درخواست GET به API کدال برای نماد: %s | پارامترها: %s",
        symbol,
        params,
    )

    response = requests.get(
        CODAL_SEARCH_URL,
        params=params,
        headers=HEADERS,
        timeout=getattr(settings, "CODAL_REQUEST_TIMEOUT", 30),
    )
    response.raise_for_status()

    data = response.json()

    if "Letters" not in data:
        logger.warning("پاسخ API کدال فیلد Letters ندارد. پاسخ: %s", str(data)[:300])
        return []

    letters = data.get("Letters", [])
    results = []

    for item in letters:
        tracing_no = item.get("TracingNo")
        if not tracing_no:
            continue

        publish_date = _parse_codal_date(item.get("PublishDateTime", ""))
        letter_code = item.get("LetterCode", "")

        # ساخت لینک مستقیم (codalpy از فیلد Url استفاده می‌کند)
        raw_url = item.get("Url", "")
        if raw_url:
            if raw_url.startswith("/"):
                direct_link = f"https://www.codal.ir{raw_url}"
            else:
                direct_link = raw_url
        else:
            direct_link = (
                f"https://codal.ir/ReportList.aspx?"
                f"search&Symbol={symbol}"
                f"&LetterCode={letter_code}"
                f"&TracingNo={tracing_no}"
            )

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
    اگر رکوردی وجود نداشت، از API کدال می‌گیرد و ذخیره می‌کند.
    """
    existing = Announcement.objects.filter(symbol=symbol).order_by("-publish_date")

    if existing.exists():
        logger.info(
            "یافت شد %d رکورد موجود در دیتابیس برای نماد %s",
            existing.count(),
            symbol,
        )
        return list(existing)

    logger.info("رکوردی در دیتابیس یافت نشد. استخراج از کدال برای نماد: %s", symbol)

    try:
        announcements_data = fetch_announcements_from_codal(symbol)
    except requests.RequestException as e:
        logger.error("خطا در ارتباط با API کدال: %s", str(e))
        raise

    save_announcements_to_db(announcements_data)

    return list(
        Announcement.objects.filter(symbol=symbol).order_by("-publish_date")
    )


def search_companies(query: str, limit: int = 12, sector: str = "") -> list[dict]:
    """
    جستجوی هوشمند شرکت‌ها با امتیازدهی:

    1. شروع با نماد (exact) → score 100
    2. شروع با نام شرکت → score 90
    3. شامل نماد → score 70
    4. شامل نام شرکت → score 50
    5. شامل کلمه‌ای از نام → score 30
    """
    if not query or len(query) < 1:
        return []

    query_clean = query.strip()
    query_lower = query_clean.lower()

    # فیلتر صنعت
    queryset = Company.objects.all()
    if sector:
        queryset = queryset.filter(sector=sector)

    # برداشت اولیه (حداکثر ۵۰ تا برای امتیازدهی)
    raw_results = list(queryset.filter(
        db_models.Q(symbol__icontains=query_lower) |
        db_models.Q(name__icontains=query_lower)
    )[:50])

    scored = []
    for c in raw_results:
        sym_lower = c.symbol.lower()
        name_lower = c.name.lower()
        score = 0
        match_type = "contains"

        if sym_lower == query_lower:
            score = 100
            match_type = "exact_symbol"
        elif sym_lower.startswith(query_lower):
            score = 85
            match_type = "starts_symbol"
        elif name_lower.startswith(query_lower):
            score = 90
            match_type = "starts_name"
        elif query_lower in sym_lower:
            score = 70
            match_type = "contains_symbol"
        elif query_lower in name_lower:
            score = 60
            match_type = "contains_name"
        else:
            # بررسی هر کلمه از کوئری
            words = query_lower.split()
            word_matches = sum(1 for w in words if w in sym_lower or w in name_lower)
            if word_matches > 0:
                score = int(30 * word_matches / len(words))
                match_type = "fuzzy"

        if score > 0:
            scored.append({
                "symbol": c.symbol,
                "name": c.name,
                "sector": c.sector,
                "sector_icon": c.sector_icon,
                "score": score,
                "match_type": match_type,
            })

    # مرتب‌سازی بر اساس امتیاز
    scored.sort(key=lambda x: -x["score"])

    return scored[:limit]


def get_all_sectors() -> list[dict]:
    """
    دریافت لیست تمام صنایع با تعداد شرکت‌ها.
    """
    from django.db.models import Count

    sectors = (
        Company.objects
        .values("sector", "sector_icon")
        .annotate(count=Count("symbol"))
        .order_by("-count")
    )

    return [
        {"name": s["sector"], "icon": s["sector_icon"], "count": s["count"]}
        for s in sectors
        if s["sector"]
    ]


def resolve_search_query(query: str) -> str:
    """
    اگر کاربر نام شرکت را تایپ کرد، نماد مربوطه را برمی‌گرداند.
    در غیر این صورت همان عبارت را برمی‌گرداند.
    """
    query_clean = query.strip()

    # اول جستجوی دقیق بر اساس نماد
    try:
        company = Company.objects.get(symbol=query_clean)
        return company.symbol
    except Company.DoesNotExist:
        pass

    # جستجو بر اساس نام شرکت
    matches = Company.objects.filter(name__icontains=query_clean)[:1]
    if matches:
        return matches[0].symbol

    return query_clean