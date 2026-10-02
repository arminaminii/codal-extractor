import json
import hashlib
import html as html_module
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import jdatetime
import requests
from django.conf import settings
from django.core.cache import cache
from django.db import models as db_models

from .models import Announcement, Company

logger = logging.getLogger(__name__)

_financial_report_locks: dict[str, threading.Lock] = {}
_financial_report_locks_guard = threading.Lock()

# --- Codal API URL ---
CODAL_SEARCH_URL = "https://search.codal.ir/api/search/v2/q"

# --- Default params (based on codalpy/codaler — PublisherType=1 is REQUIRED) ---
DEFAULT_PARAMS = {
    "Symbol": "",
    "Category": -1,
    "PublisherType": 1,        # ← REQUIRED (ناشران)
    "LetterType": -1,
    "Length": -1,              # -1 = همه
    "Audited": True,
    "NotAudited": True,
    "Mains": True,
    "Childs": False,
    "Consolidatable": True,
    "NotConsolidatable": True,
    "AuditorRef": -1,
    "CompanyState": 0,         # 0 = فعال
    "CompanyType": -1,
    "PageNumber": 1,
    "TracingNo": -1,
    "Publisher": False,
    "IsNotAudited": False,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://codal.ir/",
    "Origin": "https://codal.ir",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}


def _parse_codal_date(date_str: str) -> datetime | None:
    """Parse both legacy millisecond and current Jalali Codal dates."""
    if not date_str:
        return None
    match = re.search(r"\((\d+)", date_str)
    if match:
        timestamp_ms = int(match.group(1))
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

    normalized = str(date_str).translate(
        str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    )
    for date_format in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            jalali_value = jdatetime.datetime.strptime(normalized, date_format)
            return jalali_value.togregorian().replace(
                tzinfo=timezone(timedelta(hours=3, minutes=30))
            )
        except ValueError:
            continue
    return None


def _normalize_persian(text: str) -> str:
    """Fix common Arabic → Persian character issues."""
    text = text.replace("\u064a", "\u06cc")  # ی Arabic → ی Persian
    text = text.replace("\u0643", "\u06a9")  # ک Arabic → ک Persian
    text = text.replace("\u0629", "\u0647")  # ة → ه
    return text


# Codal returns max ~20 per page.
CODAL_PAGE_SIZE = 20
CODAL_MAX_PAGES = 5  # 5 pages × 20 = 100 most recent announcements
MAX_RETRIES = 3  # retries on 429 with exponential backoff


def _parse_codal_letters(symbol: str, letters_data: list) -> list[dict]:
    """Parse a list of raw letter items from Codal API into our format."""
    results = []
    for item in letters_data:
        tracing_no = item.get("TracingNo")
        if not tracing_no:
            continue

        publish_date = _parse_codal_date(item.get("PublishDateTime", ""))
        letter_code = item.get("LetterCode", "")

        raw_url = item.get("Url", "")
        if raw_url:
            direct_link = (
                f"https://www.codal.ir{raw_url}"
                if raw_url.startswith("/")
                else raw_url
            )
        else:
            direct_link = (
                f"https://codal.ir/ReportList.aspx?"
                f"search&Symbol={symbol}"
                f"&LetterCode={letter_code}"
                f"&TracingNo={tracing_no}"
            )

        results.append({
            "tracking_id": tracing_no,
            "symbol": symbol,
            "title": item.get("Title", item.get("Subject", "")),
            "publish_date": publish_date,
            "direct_link": direct_link,
            "letter_code": letter_code,
        })
    return results


def fetch_announcements_from_codal(symbol: str) -> list[dict]:
    """
    Fetch ALL announcements from Codal API for a given symbol.

    Pagination strategy:
      - Codal API returns max ~20 results per page.
      - We start at PageNumber=1 and increment until we get fewer than 20.
      - All other params stay the same (Length=-1, PublisherType=1, etc.)
      - Dedup by TracingNo in case of overlap.

    Based on: github.com/yghaderi/codalpy

    Raises:
        requests.RequestException: On network error
    """
    # Normalize symbol before sending to Codal
    symbol = _normalize_persian(symbol)
    timeout = getattr(settings, "CODAL_REQUEST_TIMEOUT", 30)

    all_results = []
    seen_tracing_nos = set()

    for page in range(1, CODAL_MAX_PAGES + 1):
        params = {
            **DEFAULT_PARAMS,
            "Symbol": symbol,
            "PageNumber": page,
        }

        # Retry loop for 429 (Too Many Requests)
        response = None
        for attempt in range(1, MAX_RETRIES + 1):
            logger.info(
                "Fetching Codal API for symbol: %s (page %d, attempt %d)",
                symbol, page, attempt,
            )
            response = requests.get(
                CODAL_SEARCH_URL,
                params=params,
                headers=HEADERS,
                timeout=timeout,
            )
            if response.status_code == 429:
                wait = 10 * (2 ** (attempt - 1))  # 10s, 20s, 40s
                logger.warning(
                    "429 rate-limit for %s page %d. Waiting %ds before retry %d/%d",
                    symbol, page, wait, attempt, MAX_RETRIES,
                )
                time.sleep(wait)
                continue
            break

        response.raise_for_status()

        data = response.json()

        if "Letters" not in data:
            logger.warning(
                "Codal API response missing 'Letters' for %s page %d. Response: %s",
                symbol, page, str(data)[:300],
            )
            break

        letters = data["Letters"]
        if not letters:
            logger.info(
                "No more results for %s at page %d — stopping.",
                symbol, page,
            )
            break

        page_results = _parse_codal_letters(symbol, letters)

        # Dedup by TracingNo
        new_count = 0
        for r in page_results:
            tid = r["tracking_id"]
            if tid not in seen_tracing_nos:
                seen_tracing_nos.add(tid)
                all_results.append(r)
                new_count += 1

        logger.info(
            "Page %d: %d raw, %d new unique (total: %d) for symbol %s",
            page, len(page_results), new_count, len(all_results), symbol,
        )

        # If we got fewer than the expected page size, we've reached the end
        if len(letters) < CODAL_PAGE_SIZE:
            break

    logger.info(
        "Total: %d unique announcements for symbol %s",
        len(all_results), symbol,
    )
    return all_results


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
        "Saved/updated %d new records out of %d announcements",
        saved_count,
        len(announcements_data),
    )
    return saved_count


def get_or_fetch_announcements(
    symbol: str, force_refresh: bool = False
) -> list[Announcement]:
    """
    Check DB first, then fetch from Codal API if needed.

    Args:
        symbol: Stock symbol (will be normalized internally)
        force_refresh: If True, always re-fetch from API and update DB.
    """
    # Normalize symbol ONCE at the top so DB queries and API calls
    # all use the same value.
    symbol = _normalize_persian(symbol)

    existing = Announcement.objects.filter(symbol=symbol).order_by("-publish_date")

    if not force_refresh and existing.exists():
        logger.info(
            "Found %d existing records in DB for symbol %s",
            existing.count(),
            symbol,
        )
        return list(existing)

    logger.info(
        "No records in DB. Fetching from Codal for symbol: %s", symbol
    )

    try:
        announcements_data = fetch_announcements_from_codal(symbol)
    except requests.RequestException as e:
        logger.error("Error connecting to Codal API: %s", str(e))
        raise

    save_announcements_to_db(announcements_data)

    return list(
        Announcement.objects.filter(symbol=symbol).order_by("-publish_date")
    )


def categorize_letter_code(letter_code: str) -> dict:
    """
    Map a Codal LetterCode to a category with label and color.

    Based on official Codal.ir letter codes:
      https://bourse-trader.ir/codalcode

    Categories:
      financial        - صورت‌های مالی (ن-۱۰, ن-۳۱, ن-۳۲, etc.)
      management       - گزارش هیئت مدیره (ن-۱۱, ن-۲)
      disclosure       - افشای اطلاعات بااهمیت (ن-۲۰, ن-۲۱, ن-۲۲, ن-۲۳)
      monthly          - گزارش فعالیت ماهانه (ن-۳۰)
      assembly         - مجامع عمومی (ن-۴۲ to ن-۵۹)
      capital_increase - افزایش سرمایه (ن-۶۰ to ن-۷۳)
      dividend         - سود نقدی / زمان‌بندی پرداخت (ن-۱۳)
      corporate        - تغییرات شرکتی (ن-۸۰, ن-۸۱, ن-۴۳, ن-۴۵)
      other            - سایر

    Returns:
        dict with keys: category, label, color
    """
    lc = (letter_code or "").strip()

    # --- Capital Increase (check FIRST — many sub-codes) ---
    CAPITAL_CODES = {
        "ن-۶۰", "ن-۶۱", "ن-۶۲", "ن-۶۳", "ن-۶۴", "ن-۶۵",
        "ن-۶۶", "ن-۶۷", "ن-۶۹", "ن-۷۰", "ن-۷۱", "ن-۷۲", "ن-۷۳",
        "N-60", "N-61", "N-62", "N-63", "N-64", "N-65",
        "N-66", "N-67", "N-69", "N-70", "N-71", "N-72", "N-73",
    }
    if lc in CAPITAL_CODES:
        return {"category": "capital_increase", "label": "افزایش سرمایه", "color": "#34d399"}

    # Keyword-based capital increase (for codes not in our list)
    if any(kw in lc for kw in ("افزایش سرمایه", "حق تقدم", "پذیره نویسی")):
        return {"category": "capital_increase", "label": "افزایش سرمایه", "color": "#34d399"}

    # --- Assembly / Shareholder Meetings ---
    ASSEMBLY_CODES = {
        "ن-۴۲", "ن-۵۰", "ن-۵۱", "ن-۵۲", "ن-۵۳", "ن-۵۴",
        "ن-۵۵", "ن-۵۶", "ن-۵۷", "ن-۵۸", "ن-۵۹",
        "N-42", "N-50", "N-51", "N-52", "N-53", "N-54",
        "N-55", "N-56", "N-57", "N-58", "N-59",
    }
    if lc in ASSEMBLY_CODES:
        return {"category": "assembly", "label": "مجامع عمومی", "color": "#a78bfa"}

    if any(kw in lc for kw in ("مجمع", "دعوت به مجمع", "تصمیمات مجمع")):
        return {"category": "assembly", "label": "مجامع عمومی", "color": "#a78bfa"}

    # --- Financial Statements ---
    FINANCIAL_CODES = {
        "ن-۱۰", "ن-۳۱", "ن-۳۲", "ن-۳۳", "ن-۳۴", "ن-۲۶",
        "N-10", "N-31", "N-32", "N-33", "N-34", "N-26",
    }
    if lc in FINANCIAL_CODES:
        return {"category": "financial", "label": "صورت‌های مالی", "color": "#22d3ee"}

    if any(kw in lc for kw in (
        "صورت مالی", "صورت\u200cهای مالی",
        "حسابرسی", "توضیحات مدیریت",
        "گزارش تفسیری",
    )):
        return {"category": "financial", "label": "صورت‌های مالی", "color": "#22d3ee"}

    # --- Management Activity Report ---
    MANAGEMENT_CODES = {"ن-۱۱", "N-11"}
    if lc in MANAGEMENT_CODES:
        return {"category": "management", "label": "گزارش هیئت مدیره", "color": "#fb923c"}

    if any(kw in lc for kw in ("هیئت مدیره", "گزارش فعالیت")):
        return {"category": "management", "label": "گزارش هیئت مدیره", "color": "#fb923c"}

    # --- Monthly Activity Report ---
    if lc in ("ن-۳۰", "N-30") or "ماهانه" in lc:
        return {"category": "monthly", "label": "گزارش ماهانه", "color": "#60a5fa"}

    # --- Dividend / Profit Distribution ---
    if lc in ("ن-۱۳", "N-13"):
        return {"category": "dividend", "label": "سود نقدی", "color": "#f472b6"}

    if any(kw in lc for kw in ("سود نقدی", "تقسیم سود", "پرداخت سود")) and "سود و زیان" not in lc:
        return {"category": "dividend", "label": "سود نقدی", "color": "#f472b6"}

    # --- Disclosure / Material Information ---
    DISCLOSURE_CODES = {"ن-۲۰", "ن-۲۱", "ن-۲۲", "ن-۲۳", "ن-۲۴", "ن-۲۵", "N-20", "N-21", "N-22", "N-23", "N-24", "N-25"}
    if lc in DISCLOSURE_CODES:
        return {"category": "disclosure", "label": "افشای اطلاعات بااهمیت", "color": "#f59e0b"}

    if any(kw in lc for kw in ("افشا", "اطلاعات با اهمیت", "شایعه", "شفاف‌سازی", "نوسان قیمت")):
        return {"category": "disclosure", "label": "افشای اطلاعات بااهمیت", "color": "#f59e0b"}

    # --- Corporate Changes ---
    CORPORATE_CODES = {"ن-۸۰", "ن-۸۱", "ن-۴۳", "ن-۴۵", "ن-۱۲", "ن-۴۱", "N-80", "N-81", "N-43", "N-45", "N-12", "N-41"}
    if lc in CORPORATE_CODES:
        return {"category": "corporate", "label": "تغییرات شرکتی", "color": "#c084fc"}

    if any(kw in lc for kw in ("تغییر نشانی", "اساسنامه", "اعضای هیئت مدیره", "کمیته حسابرسی", "کنترل داخلی")):
        return {"category": "corporate", "label": "تغییرات شرکتی", "color": "#c084fc"}

    # --- Fallback: any ن- code → financial ---
    if lc.startswith("ن-") or lc.startswith("N-"):
        return {"category": "financial", "label": "صورت‌های مالی", "color": "#22d3ee"}

    # --- Other ---
    return {"category": "other", "label": "سایر", "color": "#64748b"}


def search_companies(query: str, limit: int = 12, sector: str = "") -> list[dict]:
    """
    Smart company search with scoring:

    1. Exact symbol match → score 100
    2. Symbol starts with query → score 85
    3. Company name starts with query → score 90
    4. Symbol contains query → score 70
    5. Name contains query → score 60
    6. Fuzzy (word match) → score 30
    """
    if not query or len(query) < 1:
        return []

    query_clean = _normalize_persian(query.strip())
    query_lower = query_clean.lower()

    # Sector filter
    queryset = Company.objects.all()
    if sector:
        queryset = queryset.filter(sector=sector)

    # Initial fetch (max 50 for scoring)
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
            # Check each word from the query
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

    # Sort by score descending
    scored.sort(key=lambda x: -x["score"])

    return scored[:limit]


def get_all_sectors() -> list[dict]:
    """
    Get list of all sectors with company counts.
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


def get_companies_by_sector(sector: str) -> list[dict]:
    """
    Get all companies in a given sector, ordered by symbol.
    """
    companies = Company.objects.filter(sector=sector).order_by("symbol")
    return [
        {
            "symbol": c.symbol,
            "name": c.name,
            "sector": c.sector,
            "sector_icon": c.sector_icon,
        }
        for c in companies
    ]


def resolve_search_query(query: str) -> str:
    """
    If the user typed a company name, resolve it to the symbol.
    Otherwise return the input as-is.
    """
    query_clean = query.strip()

    # Exact symbol match first
    try:
        company = Company.objects.get(symbol=query_clean)
        return company.symbol
    except Company.DoesNotExist:
        pass

    # Search by company name
    matches = Company.objects.filter(name__icontains=query_clean)[:1]
    if matches:
        return matches[0].symbol

    return query_clean


# ═══════════════════════════════════════════════════════════════════════════════
# استخراج اطلاعات مالی از صفحات گزارش کدال
# ═══════════════════════════════════════════════════════════════════════════════

# کدهای نامه‌ای که واقعاً صورت مالی ساختاریافته دارند (دارای var datasource)
FINANCIAL_STATEMENT_CODES = {
    "ن-۱۰", "ن-۳۱", "ن-۳۲", "ن-۳۳", "ن-۳۴", "ن-۲۶",
    "N-10", "N-31", "N-32", "N-33", "N-34", "N-26",
}

CODAL_BASE_URL = "https://codal.ir"

# نقشه شیت‌ها: SheetId → نوع شیت
SHEET_CATEGORY_MAP = {
    0: "balance",    # ترازنامه
    1: "income",     # سود و زیان
    2: "cashflow",   # جریان نقد
}

# نام‌های مختلف یک مفهوم مالی در گزارش‌های مختلف شرکت‌ها
# شامل فرم‌های واقعی کدال: ها/ی، فاصله پرانتز، نیم‌فاصله
#
# ⚠️ قوانین اضافه کردن alias:
#    1. حداقل ۵ کاراکتر (جلوگیری از false positive مثل "فروش" در "کارمزد فروش")
#    2. باید SPECIFIC باشد — اگر alias داخل مفهوم دیگری هم match شود، خطرناک است
#    3. بهتر است کل عبارت باشد نه بخشی از آن
CONCEPT_ALIASES = {
    "revenue": [
        "درآمدهای عملیاتی", "درآمدهاي عملياتي",
        "درآمد عملیاتی",
        "درآمدهای بیمه ای", "درآمدهای بیمه‌ای",
        "فروش خالص", "درآمد فروش",
        "بهای فروش کالا و خدمات",
        # ⚠️ "فروش" حذف شد — ۴ کاراکتر و داخل "کارمزد فروش" و "هزینه فروش" match می‌شود
    ],
    "cogs": [
        "بهای تمام شده درآمدهای عملیاتی", "بهای تمام شده درآمدهاي عملياتي",
        "بهای تمام شده کالای فروش رفته", "بهای تمام\u200cشده کالای فروش رفته",
        "بهای تمام شده", "بهای تمام\u200cشده",
        "Cost of Goods Sold", "Cost of Revenue",
        # ⚠️ "هزینه های عملیاتی" و "هزینه‌های عملیاتی" حذف شدند —
        #   خیلی کلی هستند و ممکن است هزینه‌های غیرمرتبط را هم match کنند
    ],
    "gross_profit": [
        "سود(زیان) ناخالص", "سود (زیان) ناخالص", "سود ناخالص",
        "سود(زیان)ناخالص", "سود (زیان)ناخالص",
        "سود (زیان) ناخالص عملیاتی",
        "Gross Profit", "Gross Loss",
    ],
    "operating_profit": [
        "سود(زیان) عملیاتى", "سود(زیان) عملیاتی", "سود (زیان) عملیاتی",
        "سود(زیان) عملیات", "سود (زیان) عملیات",
        "سود عملیاتی",
        "Operating Profit", "Operating Income",
        # ⚠️ "سود (زیان) ناخالص عملیاتی" حذف شد — نامفهوم است
    ],
    "net_income": [
        "سود(زیان) خالص", "سود (زیان) خالص", "سود خالص",
        "سود(زیان)خالص", "سود (زیان)خالص",
        "سود(زیان) پس از مالیات", "سود (زیان) پس از مالیات",
        "سود خالص پس از مالیات",
        "Net Income", "Net Profit",
    ],
    "total_current_assets": [
        "جمع دارایی‌های جاری", "جمع دارایی جاری", "جمع داراییهای جاری",
        "Current Assets", "Total Current Assets",
        # ⚠️ "دارایی جاری" و "دارایی‌های جاری" حذف شدند —
        #   بدون "جمع" خیلی کلی هستند و ممکن است ردیف‌های فرعی را match کنند
    ],
    "total_noncurrent_assets": [
        "جمع دارایی‌های غیرجاری", "جمع دارایی غیرجاری", "جمع داراییهای غیرجاری",
        "Non-Current Assets",
    ],
    "total_assets": [
        "جمع کل دارایی‌ها", "جمع دارایی‌ها", "جمع داراییها",
        "جمع کل دارایی",
        "Total Assets", "Total of Assets",
    ],
    "total_current_liabilities": [
        "جمع بدهی‌های جاری", "جمع بدهی جاری", "جمع بدهیهای جاری",
        "Current Liabilities", "Total Current Liabilities",
        # ⚠️ "بدهی جاری" حذف شد — بدون "جمع" خیلی کلی است
    ],
    "total_noncurrent_liabilities": [
        "جمع بدهی‌های غیرجاری", "جمع بدهی غیرجاری", "جمع بدهیهای غیرجاری",
        "Non-Current Liabilities",
    ],
    "total_liabilities": [
        "جمع کل بدهی‌ها", "جمع بدهی‌ها", "جمع بدهیها",
        "جمع کل بدهی",
        "Total Liabilities",
    ],
    "total_equity": [
        "جمع حقوق صاحبان سهام", "حقوق صاحبان سهام",
        "جمع حقوق مالکانه", "حقوق مالکانه",
        "حقوق صاحبان سهام (بدون سود تقسیمی)",
        "Total Equity", "Equity", "Shareholders' Equity",
    ],
    "operating_cashflow": [
        "جریان نقد عملیاتی", "جریان نقد حاصل از فعالیت‌های عملیاتی",
        "جریان نقد حاصل از فعاليت‌هاي عملياتي",
        "جریان نقد حاصل از فعالیت های عملیاتی",
        "خالص جریان نقد حاصل از فعالیت‌های عملیاتی",
        "جریان خالص ورود (خروج) نقد حاصل از فعالیت‌های عملیاتی",
        "جریان خالص ورود (خروج) نقد حاصل از فعاليت‌هاي عملياتي",
        "Operating Cash Flow", "Cash from Operating Activities",
    ],
    "net_premium": [
        "حق بیمه خالص(سهم نگهداری)", "حق بیمه خالص (سهم نگهداری)",
    ],
    "net_claims_paid": [
        "خسارت و مزایای پرداختی خالص",
    ],
    "insurance_investment_income": [
        "درآمد سرمایه گذاری از محل منابع بیمه ای",
        "درآمد سرمایه‌گذاری از محل منابع بیمه‌ای",
    ],
}


def _extract_json_by_braces(html: str, var_start: int) -> tuple[str, int]:
    """
    از موقعیت var_start به بعد، ابتدا '=' و سپس '{' اول را پیدا کند
    و با شمارنده آکولاد متعادل JSON را استخراج کند.
    
    Returns:
        (json_string, end_position)
    Raises:
        ValueError: اگر نتواند پیدا کند
    """
    eq_pos = html.find('=', var_start)
    if eq_pos == -1:
        raise ValueError(f"= after var not found (pos {var_start})")

    # از بعد از = به دنبال { بگرد
    json_start = html.find('{', eq_pos)
    if json_start == -1:
        raise ValueError(f"{{ after = not found (pos {eq_pos})")

    depth = 0
    json_end = -1
    i = json_start
    in_string = False
    escape_next = False

    while i < len(html):
        ch = html[i]

        if escape_next:
            escape_next = False
            i += 1
            continue

        if ch == '\\' and in_string:
            escape_next = True
            i += 1
            continue

        if ch == '"' and not escape_next:
            in_string = not in_string
            i += 1
            continue

        if not in_string:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    json_end = i
                    break

        i += 1

    if json_end == -1:
        raise ValueError("Could not find matching closing brace for JSON")

    return html[json_start:json_end + 1], json_end


def _fetch_html(url: str, timeout: int = 30) -> str:
    """
    فچ یک URL از کدال با مدیریت خطا و retry.
    
    Returns:
        HTML content as string
    
    Raises:
        ConnectionError: خطا در اتصال
    """
    for attempt in range(MAX_RETRIES):
        try:
            logger.info("Fetching: %s (attempt %d)", url[:120], attempt + 1)
            resp = requests.get(url, headers=HEADERS, timeout=timeout,
                                allow_redirects=True)

            if resp.status_code == 429:
                wait = 10 * (2 ** attempt)
                logger.warning("429 rate-limit. Waiting %ds", wait)
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.text
        except requests.ConnectionError as e:
            raise ConnectionError(f"خطا در اتصال به کدال: {e}")
        except requests.Timeout:
            raise ConnectionError("درخواست به سرور کدال طول کشید و قطع شد.")
        except requests.RequestException as e:
            raise ConnectionError(f"خطا در دریافت گزارش: {e}")
    else:
        raise ConnectionError(
            "درخواست‌های شما بیش از حد مجاز است (429). "
            "لطفاً چند دقیقه صبر کنید و دوباره تلاش کنید."
        )


def _try_extract_datasource_from_html(html: str, url: str) -> dict | None:
    """
    تلاش برای استخراج datasource از HTML.
    
    فقط "var datasource" را جستجو می‌کند (مشابه codalpy).
    codalpy از رجکس r"var datasource = (.*?);" استفاده می‌کند.
    ما از شمارنده آکولاد متعادل استفاده می‌کنیم که امن‌تر است.
    
    Returns:
        dict اگر datasource پیدا شد و sheets داشت، None در غیر این صورت
    """
    # فقط var datasource (بدون فاصله یا با فاصله) — مشابه codalpy
    for var_pattern in ["var datasource =", "var datasource="]:
        ds_start = html.find(var_pattern)
        if ds_start == -1:
            continue

        logger.info(
            "Found '%s' at pos %d in %s",
            var_pattern.strip(), ds_start, url[:100],
        )
        try:
            json_str, _ = _extract_json_by_braces(html, ds_start)
            datasource = json.loads(json_str)

            if not isinstance(datasource, dict):
                logger.warning("Datasource is not a dict: %s", type(datasource).__name__)
                continue

            sheets = datasource.get("sheets")
            if not sheets or not isinstance(sheets, list):
                logger.warning(
                    "Datasource has no valid sheets. keys=%s",
                    list(datasource.keys())[:8],
                )
                continue

            # بررسی اینکه آیا واقعاً داده مالی دارد
            total_cells = sum(
                len(t.get("cells", []))
                for s in sheets
                for t in s.get("tables", [])
            )
            logger.info(
                "Datasource OK: %d sheet(s), %d total cells from %s",
                len(sheets), total_cells, url[:100],
            )
            return datasource

        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("JSON parse failed for '%s': %s", var_pattern.strip(), e)
            continue

    return None


def _build_sheet_urls(base_url: str, max_sheet_id: int = 5) -> list[tuple[int, str]]:
    """
    ساخت لیست (sheetId, URL) برای صفحه Decision.aspx.
    
    در کدال (مشابه codalpy):
      - sheetId=0: ترازنامه (balance sheet)
      - sheetId=1: سود و زیان (income statement)  
      - sheetId=2: جریان نقد (cash flow)
      - sheetId=3+: یادداشت‌ها و سایر
    
    Returns:
        لیست (sheetId, url)
    """
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

    parsed = urlparse(base_url)
    params = parse_qs(parsed.query, keep_blank_values=True)

    # اگر sheetId از قبل وجود دارد، فقط همان را برگردان
    existing_sid = params.get("sheetId") or params.get("SheetId")
    if existing_sid:
        return [(int(existing_sid[0]), base_url)]

    results = []
    for sid in range(max_sheet_id + 1):
        new_params = {k: v[0] for k, v in params.items()}
        new_params["sheetId"] = str(sid)
        new_query = urlencode(new_params)
        new_url = urlunparse(parsed._replace(query=new_query))
        results.append((sid, new_url))

    return results


def _build_urls_for_sheet_ids(
    base_url: str, sheet_ids: list[int]
) -> list[tuple[int, str]]:
    """Build report URLs for sheet identifiers discovered from Codal itself."""
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(base_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    results = []
    for sid in sheet_ids:
        new_params = {key: values[0] for key, values in params.items()}
        new_params.pop("SheetId", None)
        new_params["sheetId"] = str(sid)
        results.append(
            (sid, urlunparse(parsed._replace(query=urlencode(new_params))))
        )
    return results


def _discover_primary_sheet_ids(page_html: str) -> list[int]:
    """Read the authoritative financial-statement IDs from Codal's selector.

    Codal does not use a stable 0..N sequence. Consolidated statements commonly
    use IDs such as 13, 14, and 15 while standalone statements use 1, 0, and 9.
    The page title determines which group belongs to the requested disclosure.
    """
    select_match = re.search(
        r'<select[^>]+(?:id|name)=["\'][^"\']*ddlTable["\'][^>]*>(.*?)</select>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not select_match:
        return []

    options = []
    for value, raw_label in re.findall(
        r'<option[^>]*value=["\']?(\d+)["\']?[^>]*>(.*?)(?=</option>|<option|$)',
        select_match.group(1),
        flags=re.IGNORECASE | re.DOTALL,
    ):
        label = html_module.unescape(re.sub(r"<[^>]+>", " ", raw_label))
        label = re.sub(r"\s+", " ", label).strip()
        options.append((int(value), label))

    if not options:
        return []

    title_match = re.search(
        r"<title[^>]*>(.*?)</title>", page_html, flags=re.IGNORECASE | re.DOTALL
    )
    page_title = html_module.unescape(title_match.group(1)) if title_match else ""
    wants_consolidated = "تلفیقی" in page_title
    has_consolidated = any("تلفیقی" in label for _, label in options)
    has_standalone = any("تلفیقی" not in label for _, label in options)

    if has_consolidated and has_standalone:
        options = [
            (sid, label)
            for sid, label in options
            if ("تلفیقی" in label) == wants_consolidated
        ]

    def is_primary_statement(label: str) -> bool:
        compact = re.sub(r"\s+", " ", label)
        return (
            ("صورت سود و زیان" in compact and "جامع" not in compact)
            or "صورت وضعیت مالی" in compact
            or "صورت جریان" in compact
        )

    primary_ids = [sid for sid, label in options if is_primary_statement(label)]
    return primary_ids


def _fetch_sheet_datasources(
    sheet_urls: list[tuple[int, str]], timeout: int
) -> tuple[list[dict], str | None]:
    """Fetch Codal sheet variants concurrently while preserving sheet order."""
    if not sheet_urls:
        return [], None

    def fetch_one(item):
        sid, url = item
        try:
            html = _fetch_html(url, timeout)
            return sid, _try_extract_datasource_from_html(html, url), html, None
        except ConnectionError as exc:
            return sid, None, None, exc

    workers = min(
        len(sheet_urls),
        max(1, int(getattr(settings, "CODAL_SHEET_FETCH_WORKERS", 3))),
    )
    results = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="codal-sheet") as pool:
        futures = {pool.submit(fetch_one, item): item[0] for item in sheet_urls}
        for future in as_completed(futures):
            sid, datasource, html, error = future.result()
            results[sid] = (datasource, html, error)

    found_datasources = []
    last_html = None
    for sid in sorted(results):
        datasource, html, error = results[sid]
        if html is not None:
            last_html = html
        if error is not None:
            logger.warning("Connection error for sheetId=%d: %s", sid, error)
        elif datasource:
            logger.info(
                "✅ sheetId=%d: got datasource with %d sheet(s)",
                sid,
                len(datasource.get("sheets", [])),
            )
            found_datasources.append(datasource)
        else:
            logger.info("❌ sheetId=%d: no datasource", sid)

    return found_datasources, last_html


def _merge_datasources(datasources: list[dict]) -> dict:
    """
    ادغام چند datasource (از sheetIdهای مختلف) به یک datasource واحد.
    
    هر datasource یک sheets آرایه دارد. ما همه sheets را جمع می‌کنیم.
    فیلدهای سطح بالا (title, period, ...) را از اولین datasource می‌گیریم.
    
    Args:
        datasources: لیست datasource‌های استخراج شده
    
    Returns:
        dict: datasource ادغام شده
    """
    if not datasources:
        raise ValueError("No datasources to merge")

    if len(datasources) == 1:
        return datasources[0]

    # استفاده از اولین datasource به عنوان پایه
    merged = dict(datasources[0])
    all_sheets = []
    seen_sheet_codes = set()

    for ds in datasources:
        for sheet in ds.get("sheets", []):
            sheet_code = sheet.get("code")
            # جلوگیری از تکرار (اگر دو datasource همان شیت را داشته باشند)
            sheet_key = (sheet_code, sheet.get("title_Fa") or "")
            if sheet_key not in seen_sheet_codes:
                seen_sheet_codes.add(sheet_key)
                all_sheets.append(sheet)
                logger.info(
                    "  Merged sheet code=%s: %s",
                    sheet_code, (sheet.get("title_Fa") or "")[:40],
                )

    merged["sheets"] = all_sheets
    logger.info(
        "Merged %d datasources → %d total sheets",
        len(datasources), len(all_sheets),
    )
    return merged


def extract_datasource(report_url: str) -> dict:
    """
    دریافت HTML صفحه گزارش کدال و استخراج var datasource = {...}

    استراتژی (بر اساس تحلیل codalpy و ساختار واقعی کدال):
    
      1. اگر URL از نوع Decision.aspx باشد:
         ⚠️ URL اصلی معمولاً صفحه «نظر حسابرس» است و datasource آن
         مربوط به نظر حسابرس است، نه داده مالی.
         → مستقیماً sheetIdهای 0 تا 5 را امتحان کن و همه datasourceها
         را MERGE کن.
      
      2. برای سایر URLها:
         → اول URL اصلی را امتحان کن
         → اگر datasource پیدا نشد، sheetIdها را امتحان کن

    Args:
        report_url: لینک مستقیم گزارش

    Returns:
        dict: parsed datasource JSON (ادغام شده si چند sheetId)

    Raises:
        ConnectionError: خطا در اتصال
        ValueError: datasource یافت نشد
    """
    full_url = report_url if report_url.startswith("http") else CODAL_BASE_URL + report_url
    timeout = getattr(settings, "CODAL_REQUEST_TIMEOUT", 30)

    is_decision_page = "Decision.aspx" in full_url

    # ═══════════════════════════════════════════════════════════════════════
    # Decision.aspx: مستقیماً sheetIdها را امتحان کن و MERGE کن
    # ═══════════════════════════════════════════════════════════════════════
    if is_decision_page:
        logger.info(
            "Decision.aspx detected. Discovering financial sheet IDs..."
        )
        # If the caller already selected a sheet, preserve that exact sheet.
        # Otherwise fetch the base page once and read the real IDs from its
        # ddlTable selector instead of guessing 0..5.
        sheet_urls = _build_sheet_urls(full_url, max_sheet_id=5)
        if len(sheet_urls) > 1:
            try:
                index_html = _fetch_html(full_url, timeout)
            except ConnectionError as exc:
                logger.warning("Could not load Codal sheet selector: %s", exc)
                index_html = ""
            discovered_ids = _discover_primary_sheet_ids(index_html)
            if discovered_ids:
                logger.info("Discovered primary Codal sheet IDs: %s", discovered_ids)
                sheet_urls = _build_urls_for_sheet_ids(full_url, discovered_ids)
            else:
                logger.warning(
                    "Codal sheet selector was unavailable; falling back to IDs 0..5"
                )

        found_datasources, last_html = _fetch_sheet_datasources(sheet_urls, timeout)

        if found_datasources:
            merged = _merge_datasources(found_datasources)
            logger.info(
                "✅ Total: merged %d datasources → %d sheets",
                len(found_datasources), len(merged.get("sheets", [])),
            )
            return merged

        # هیچ sheetIdای datasource نداشت
        page_title_m = re.search(r'<title>(.*?)</title>', (last_html or ""), re.IGNORECASE)
        page_title = page_title_m.group(1).strip() if page_title_m else ""
        html_len = len(last_html) if last_html else 0

        raise ValueError(
            f"متغیر datasource در صفحه Decision.aspx یافت نشد."
            f"\nتمام sheetIdهای 0 تا 5 امتحان شدند."
            f"\n\nعنوان صفحه: {page_title}"
            f"\nطول HTML: {html_len} کاراکتر"
            f"\nURL: {full_url[:150]}"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # سایر صفحات: اول URL اصلی، بعد sheetId
    # ═══════════════════════════════════════════════════════════════════════
    logger.info("Non-Decision page. Trying original URL first: %s", full_url[:120])
    try:
        html = _fetch_html(full_url, timeout)
    except ConnectionError:
        raise

    datasource = _try_extract_datasource_from_html(html, full_url)
    if datasource:
        return datasource

    logger.info("No datasource on original URL. Trying sheetIds...")
    sheet_urls = _build_sheet_urls(full_url, max_sheet_id=5)

    found_datasources, fallback_html = _fetch_sheet_datasources(sheet_urls, timeout)
    if fallback_html is not None:
        html = fallback_html

    if found_datasources:
        return _merge_datasources(found_datasources)

    # هیچ جا datasource پیدا نشد
    page_title_m = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE)
    page_title = page_title_m.group(1).strip() if page_title_m else ""

    raise ValueError(
        f"متغیر datasource در صفحه یافت نشد."
        f"\n\nعنوان صفحه: {page_title}"
        f"\nطول HTML: {len(html)} کاراکتر"
        f"\nURL: {full_url[:150]}"
    )


def categorize_sheet(sheet: dict) -> str:
    """تشخیص نوع شیت از روی کد یا عنوان"""
    code = sheet.get("code")
    title = _normalize_persian(sheet.get("title_Fa") or "")
    
    # اول بر اساس کد
    if code is not None and code in SHEET_CATEGORY_MAP:
        return SHEET_CATEGORY_MAP[code]
    
    # بعد بر اساس عنوان (با اولویت طولانی‌ترین match)
    if any(kw in title for kw in ("ترازنامه", "وضعیت مالی", "بدهی‌ها")):
        return "balance"
    if any(kw in title for kw in ("سود و زیان", "عملکرد مالی", "درآمد")):
        return "income"
    if "جریان" in title and "نقد" in title:
        return "cashflow"
    
    return "notes"


def _parse_cell_value(val) -> float | None:
    """
    تبدیل مقدار سلول به عدد.
    
    فرمت‌های پشتیبانی شده:
      - عدد: 12345, 12345.0
      - رشته عددی: "12345"
      - رشته با کاما: "1,234,567", "1,234,567.50"
      - عدد منفی: -12345, "(12345)"
      - صفر: 0, "0"
    
    رشته‌های خالی، NaN و مقادیر غیرعددی → None
    """
    if val is None:
        return None

    # اگر عدد یا بولین است
    if isinstance(val, (int, float)):
        if val != val or val == float('inf') or val == float('-inf'):
            return None
        return float(val)

    # اگر رشته است
    if isinstance(val, str):
        s = val.strip().translate(
            str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
        )
        if not s or s in ('-', '--', '...', '۰', 'nan', 'NaN', 'null'):
            return None

        # حذف کامای جداکننده هزارگان
        s = s.replace(',', '').replace('٬', '').replace('،', '')

        # عدد منفی در پرانتز: (12345) → -12345
        if s.startswith('(') and s.endswith(')'):
            s = '-' + s[1:-1]

        # حذف فاصله‌ها (برخی گزارش‌ها فاصله دارند)
        s = s.replace(' ', '')

        if not s:
            return None

        try:
            n = float(s)
            if n != n or n == float('inf') or n == float('-inf'):
                return None
            return n
        except (ValueError, TypeError):
            return None

    return None


def _get_row_key(cell: dict) -> str | None:
    """
    استخراج کلید ردیف از سلول.
    فرمت‌های ممکن:
      - address: "A1", "B2" → ردیف = عدد
      - rowCode / rowSequence: عدد
    """
    addr = cell.get("address", "")
    if addr:
        m = re.match(r'[A-Z]+(\d+)', addr)
        if m:
            return m.group(1)

    row_code = cell.get("rowCode")
    if row_code is not None:
        return str(row_code)

    row_seq = cell.get("rowSequence")
    if row_seq is not None:
        return str(row_seq)

    return None


def _excel_column_number(address: str) -> int | None:
    match = re.match(r"([A-Z]+)\d+", address or "", re.IGNORECASE)
    if not match:
        return None
    result = 0
    for character in match.group(1).upper():
        result = result * 26 + ord(character) - ord("A") + 1
    return result


def _cell_column_key(cell: dict) -> int | None:
    """Return Codal's semantic columnCode, falling back to Excel address."""
    column_code = cell.get("columnCode")
    try:
        if column_code is not None:
            return int(column_code)
    except (TypeError, ValueError):
        pass
    return _excel_column_number(cell.get("address", ""))


def _column_profiles(cells: list[dict]) -> dict[int, dict]:
    profiles: dict[int, dict] = {}
    for cell in cells:
        column = _cell_column_key(cell)
        if column is None:
            continue
        profile = profiles.setdefault(
            column,
            {"cells": [], "numeric": 0, "nonzero": 0, "text": 0, "texts": []},
        )
        profile["cells"].append(cell)
        raw_value = cell.get("value")
        numeric_value = _parse_cell_value(raw_value)
        if numeric_value is not None:
            profile["numeric"] += 1
            if numeric_value != 0:
                profile["nonzero"] += 1
        elif str(raw_value or "").strip():
            raw_text = str(raw_value).strip()
            if raw_text.lower() not in {
                "-infinity", "+infinity", "infinity", "nan", "null", "-", "--"
            }:
                profile["text"] += 1
                profile["texts"].append(raw_text)
    return profiles


def _detect_label_columns(profiles: dict[int, dict]) -> list[int]:
    """Detect one or more description columns in single- and dual-panel tables."""
    label_columns = []
    for column, profile in sorted(profiles.items()):
        if profile["text"] >= 2 and profile["text"] > profile["numeric"] * 2:
            label_columns.append(column)
    if not label_columns and profiles:
        label_columns.append(min(profiles))
    return label_columns


def _select_value_columns(
    profiles: dict[int, dict], panel_columns: list[int]
) -> tuple[int | None, int | None]:
    """Choose current and comparative value columns inside one visual panel."""
    candidates = []
    for column in panel_columns:
        profile = profiles[column]
        header_text = " ".join(profile["texts"][:3])
        if "درصد" in header_text or "%" in header_text:
            continue
        if profile["numeric"]:
            candidates.append(column)

    if not candidates:
        return None, None

    current_column = candidates[0]
    comparison_candidates = candidates[1:]
    if not comparison_candidates:
        return current_column, None

    # Some Codal templates include an all-zero placeholder comparison column.
    # Prefer the populated comparison; on ties retain the nearest column.
    comparison_column = max(
        comparison_candidates,
        key=lambda column: (
            profiles[column]["nonzero"],
            profiles[column]["numeric"],
            -column,
        ),
    )
    return current_column, comparison_column


def _extract_financial_cell_value(cell: dict | None, comparative: bool) -> float | None:
    if not cell:
        return None
    preferred_field = "yearEndToDate" if comparative else "periodEndToDate"
    value = _parse_cell_value(cell.get(preferred_field))
    if value is None:
        value = _parse_cell_value(cell.get("value"))
    return value


def _is_structural_header(concept: str, period_value, year_value) -> bool:
    normalized = _normalize_for_match(concept)
    known_headers = {
        "شرح",
        "داراییها",
        "بدهیها",
        "حقوق مالکانه",
        "بدهیها و حقوق مالکانه",
        "داراییها و بدهیها",
        "صورت وضعیت مالی",
        "صورت سود و زیان",
    }
    return normalized in known_headers or (
        period_value is None and year_value is None
    )


def parse_financial_report(datasource: dict) -> dict:
    """
    پارس datasource به ساختار ساختاریافته برای نمایش در قالب.
    
    از دو استراتژی برای گروه‌بندی سلول‌ها استفاده می‌کند:
      1. address-based: سلول‌هایی با address مثل "A1", "B2" (فرمت اکسل)
      2. columnCode-based: سلول‌هایی با columnCode/rowCode
    
    Returns:
        dict with keys: title, period, year_end, is_audited, is_consolidated, sheets
        Each sheet has: code, title, category, tables
        Each table has: title, rows
        Each row has: concept, period_value, year_value, row_type, indent
    """
    result = {
        "title": datasource.get("title_Fa") or "",
        "tracing_no": datasource.get("tracing_no", ""),
        "period": datasource.get("periodEndToDate", ""),
        "year_end": datasource.get("yearEndToDate", ""),
        "is_audited": datasource.get("isAudited", False),
        "is_consolidated": datasource.get("isConsolidated", False),
        "sheets": [],
    }
    
    for sheet in datasource.get("sheets", []):
        category = categorize_sheet(sheet)
        sheet_data = {
            "code": sheet.get("code"),
            "title": sheet.get("title_Fa") or "",
            "category": category,
            "tables": [],
        }
        
        for table in sheet.get("tables", []):
            table_data = {
                "title": table.get("title_Fa") or "",
                "rows": [],
            }
            
            cells = table.get("cells", [])
            if not cells:
                sheet_data["tables"].append(table_data)
                continue
            
            has_address = any(_excel_column_number(c.get("address", "")) for c in cells)
            has_column_code = any(c.get("columnCode") is not None for c in cells)

            if not has_address and not has_column_code:
                logger.warning(
                    "Table has %d cells but no address or columnCode. "
                    "Keys: %s",
                    len(cells),
                    list(cells[0].keys())[:10] if cells else "(none)",
                )
                sheet_data["tables"].append(table_data)
                continue
            
            # Physical address rows are essential for split insurance statements:
            # their right-hand panel has a second label column (usually E/cc=5).
            rows_map: dict[str, dict[int, dict]] = {}
            for cell in cells:
                row_key = _get_row_key(cell)
                column_key = _cell_column_key(cell)
                if row_key is None or column_key is None:
                    continue
                rows_map.setdefault(row_key, {})[column_key] = cell

            profiles = _column_profiles(cells)
            label_columns = _detect_label_columns(profiles)
            logical_rows = []

            def _sort_key(k):
                try:
                    return (0, int(k))
                except (ValueError, TypeError):
                    return (1, k)

            for panel_index, label_column in enumerate(label_columns):
                next_label = (
                    label_columns[panel_index + 1]
                    if panel_index + 1 < len(label_columns)
                    else None
                )
                panel_columns = [
                    column
                    for column in sorted(profiles)
                    if column > label_column
                    and (next_label is None or column < next_label)
                ]
                current_column, comparison_column = _select_value_columns(
                    profiles, panel_columns
                )

                for row_key in sorted(rows_map, key=_sort_key):
                    row_cells = rows_map[row_key]
                    label_cell = row_cells.get(label_column)
                    if not label_cell:
                        continue
                    concept_text = (
                        label_cell.get("financialConcept")
                        or label_cell.get("financial_concept")
                        or label_cell.get("value")
                        or ""
                    )
                    concept = _normalize_persian(str(concept_text)).strip()
                    if not concept:
                        continue

                    period_value = _extract_financial_cell_value(
                        row_cells.get(current_column), comparative=False
                    )
                    year_value = _extract_financial_cell_value(
                        row_cells.get(comparison_column), comparative=True
                    )
                    is_header = _is_structural_header(
                        concept, period_value, year_value
                    )
                    if is_header:
                        period_value = None
                        year_value = None

                    row_type = (
                        label_cell.get("rowTypeName", "")
                        or label_cell.get("row_type_name", "")
                        or ""
                    )
                    if is_header or row_type in ("Header", "Title", "GroupHeader"):
                        indent = 0
                    elif row_type == "SubGroupHeader":
                        indent = 1
                    else:
                        indent = 2

                    logical_rows.append({
                        "concept": concept,
                        "period_value": period_value,
                        "year_value": year_value,
                        "row_type": row_type,
                        "indent": indent,
                        "is_header": is_header,
                        "panel": panel_index,
                        "source_row": row_key,
                        "source_columns": {
                            "label": label_column,
                            "period": current_column,
                            "year": comparison_column,
                        },
                    })

            table_data["rows"] = logical_rows

            # لاگ آماری برای دیباگ
            rows_with_data = sum(
                1 for r in logical_rows
                if r["period_value"] is not None or r["year_value"] is not None
            )
            logger.info(
                "Table '%s': %d cells → %d logical rows across %d panel(s) "
                "(%d with numeric data), address=%s, columnCode=%s",
                (table.get("title_Fa") or "")[:40],
                len(cells),
                len(logical_rows),
                len(label_columns),
                rows_with_data,
                "✓" if has_address else "✗",
                "✓" if has_column_code else "✗",
            )
            
            sheet_data["tables"].append(table_data)
        
        result["sheets"].append(sheet_data)
    
    return result


def _normalize_for_match(text: str) -> str:
    """
    نرمالایز کردن متن برای مقایسه:
    1. تبدیل عربی → فارسی (ی، ک، ة)
    2. حذف نیم‌فاصله
    3. فاصله اطراف پرانتز
    4. فاصله‌های اضافی
    """
    t = text or ""
    t = _normalize_persian(t)       # عربی → فارسی
    t = t.replace("\u200c", "")      # نیم‌فاصله
    t = re.sub(r"\s*\(\s*", "(", t)  # فاصله قبل (
    t = re.sub(r"\s*\)\s*", ")", t)  # فاصله بعد )
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+(ها|های)(?=\s|$)", r"\1", t)
    return t


def _find_value_in_sheet(sheet: dict, concept_key: str, field: str = "period_value") -> float | None:
    """
    پیدا کردن مقدار یک مفهوم مالی در یک شیت.
    
    استراتژی تطبیق (سخت‌گیرانه برای جلوگیری از داده ساختگی):
      1. فقط جهت forward: alias باید SUBSTRING از concept باشد
         (نه برعکس — قبلاً concept in alias هم چک می‌شد که باعث
         match اشتباه "فروش" با "کارمزد فروش" می‌شد)
      2. حداقل ۵ کاراکتر برای alias
      3. حداقل ۵۰٪ از طول concept باید match شود
      4. اولویت با طولانی‌ترین match
    
    Returns:
        float اگر پیدا شد، None در غیر این صورت
    """
    if not sheet:
        return None
    aliases = CONCEPT_ALIASES.get(concept_key, [concept_key])

    # نرمالایز و فیلتر alias‌ها (حداقل ۵ کاراکتر)
    normalized_aliases = []
    for alias in aliases:
        na = _normalize_for_match(alias)
        if na and len(na) >= 5:
            normalized_aliases.append(na)

    if not normalized_aliases:
        return None

    best_val = None
    best_score = -1
    best_match_alias = ""
    best_match_concept = ""

    for table in sheet.get("tables", []):
        for row in table.get("rows", []):
            if row.get("is_header"):
                continue
            concept = row.get("concept", "")
            concept_norm = _normalize_for_match(concept)
            if not concept_norm:
                continue

            for alias_norm in normalized_aliases:
                if alias_norm == concept_norm:
                    score = 10_000 + len(alias_norm)
                elif alias_norm in concept_norm:
                    match_len = len(alias_norm)
                    min_match = max(5, len(concept_norm) * 0.5)
                    if match_len < min_match:
                        continue
                    # Never use a current/non-current subtotal as the grand total.
                    if concept_key in ("total_assets", "total_liabilities") and (
                        "جاری" in concept_norm
                    ):
                        continue
                    if concept_key == "total_equity" and "و بدهی" in concept_norm:
                        continue
                    score = int(100 * match_len / len(concept_norm)) + match_len
                else:
                    continue

                if score > best_score:
                    val = row.get(field)
                    if val is not None:
                        try:
                            best_val = float(val)
                            best_score = score
                            best_match_alias = alias_norm
                            best_match_concept = concept_norm
                        except (ValueError, TypeError):
                            pass

    if best_val is not None:
        logger.debug(
            "Concept '%s' → matched alias '%s' in row '%s' = %s",
            concept_key, best_match_alias, best_match_concept, best_val,
        )
    else:
        logger.debug(
            "Concept '%s' → NOT FOUND in sheet (tried %d aliases)",
            concept_key, len(normalized_aliases),
        )

    return best_val


def _safe_divide(numerator, denominator) -> float | None:
    """تقسیم امن"""
    if numerator is None or denominator is None or denominator == 0:
        return None
    try:
        return float(numerator) / float(denominator)
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def _profit_after_expense(revenue, expense) -> float | None:
    """Derive profit while respecting Codal's signed-expense convention."""
    if revenue is None or expense is None:
        return None
    return revenue + expense if expense < 0 else revenue - expense


def _average_balance(current, previous):
    if current is None:
        return None
    if previous is None:
        return current
    return (float(current) + float(previous)) / 2


def _safe_divide_positive_denominator(numerator, denominator) -> float | None:
    """Divide only when a balance denominator is positive and meaningful."""
    if denominator is None or float(denominator) <= 0:
        return None
    return _safe_divide(numerator, denominator)


def _average_positive_balance(current, previous):
    """Average balances without producing misleading returns across insolvency."""
    if current is None or float(current) <= 0:
        return None
    if previous is None:
        return float(current)
    if float(previous) <= 0:
        return None
    return (float(current) + float(previous)) / 2


def calculate_financial_ratios(parsed_report: dict) -> dict:
    """
    محاسبه ۹ شاخص مالی کلیدی.
    
    Returns:
        dict with ratio keys, each having: label, formula, period, year
    """
    sheets = parsed_report.get("sheets", [])
    
    income_sheet = next((s for s in sheets if s.get("category") == "income"), None)
    balance_sheet = next((s for s in sheets if s.get("category") == "balance"), None)
    cashflow_sheet = next((s for s in sheets if s.get("category") == "cashflow"), None)
    
    # ---- مقادیر دوره جاری ----
    revenue_p = _find_value_in_sheet(income_sheet, "revenue")
    cogs_p = _find_value_in_sheet(income_sheet, "cogs")
    gross_profit_p = _find_value_in_sheet(income_sheet, "gross_profit")
    operating_profit_p = _find_value_in_sheet(income_sheet, "operating_profit")
    net_income_p = _find_value_in_sheet(income_sheet, "net_income")
    
    total_assets_p = _find_value_in_sheet(balance_sheet, "total_assets")
    current_assets_p = _find_value_in_sheet(balance_sheet, "total_current_assets")
    current_liabilities_p = _find_value_in_sheet(balance_sheet, "total_current_liabilities")
    total_liabilities_p = _find_value_in_sheet(balance_sheet, "total_liabilities")
    equity_p = _find_value_in_sheet(balance_sheet, "total_equity")
    operating_cashflow_p = _find_value_in_sheet(cashflow_sheet, "operating_cashflow")
    
    if gross_profit_p is None:
        gross_profit_p = _profit_after_expense(revenue_p, cogs_p)
    
    # ---- مقادیر سال قبل ----
    revenue_y = _find_value_in_sheet(income_sheet, "revenue", "year_value")
    cogs_y = _find_value_in_sheet(income_sheet, "cogs", "year_value")
    gross_profit_y = _find_value_in_sheet(income_sheet, "gross_profit", "year_value")
    operating_profit_y = _find_value_in_sheet(income_sheet, "operating_profit", "year_value")
    net_income_y = _find_value_in_sheet(income_sheet, "net_income", "year_value")
    
    total_assets_y = _find_value_in_sheet(balance_sheet, "total_assets", "year_value")
    current_assets_y = _find_value_in_sheet(balance_sheet, "total_current_assets", "year_value")
    current_liabilities_y = _find_value_in_sheet(balance_sheet, "total_current_liabilities", "year_value")
    total_liabilities_y = _find_value_in_sheet(balance_sheet, "total_liabilities", "year_value")
    equity_y = _find_value_in_sheet(balance_sheet, "total_equity", "year_value")
    operating_cashflow_y = _find_value_in_sheet(cashflow_sheet, "operating_cashflow", "year_value")
    
    if gross_profit_y is None:
        gross_profit_y = _profit_after_expense(revenue_y, cogs_y)

    average_equity_p = _average_positive_balance(equity_p, equity_y)
    average_assets_p = _average_balance(total_assets_p, total_assets_y)

    ratios = {
        "gross_margin": {
            "label": "حاشیه سود ناخالص",
            "formula": "سود ناخالص ÷ درآمد عملیاتی",
            "period": _safe_divide(gross_profit_p, revenue_p),
            "year": _safe_divide(gross_profit_y, revenue_y),
            "type": "percent",
        },
        "operating_margin": {
            "label": "حاشیه سود عملیاتی",
            "formula": "سود عملیاتی ÷ درآمد عملیاتی",
            "period": _safe_divide(operating_profit_p, revenue_p),
            "year": _safe_divide(operating_profit_y, revenue_y),
            "type": "percent",
        },
        "net_margin": {
            "label": "حاشیه سود خالص",
            "formula": "سود خالص ÷ درآمد عملیاتی",
            "period": _safe_divide(net_income_p, revenue_p),
            "year": _safe_divide(net_income_y, revenue_y),
            "type": "percent",
        },
        "current_ratio": {
            "label": "نسبت جاری",
            "formula": "دارایی جاری ÷ بدهی جاری",
            "period": _safe_divide(current_assets_p, current_liabilities_p),
            "year": _safe_divide(current_assets_y, current_liabilities_y),
            "type": "ratio",
        },
        "debt_to_assets": {
            "label": "نسبت بدهی به دارایی",
            "formula": "کل بدهی ÷ کل دارایی",
            "period": _safe_divide(total_liabilities_p, total_assets_p),
            "year": _safe_divide(total_liabilities_y, total_assets_y),
            "type": "percent",
        },
        "debt_to_equity": {
            "label": "نسبت بدهی به حقوق صاحبان سهام",
            "formula": "کل بدهی ÷ حقوق صاحبان سهام",
            "period": _safe_divide_positive_denominator(total_liabilities_p, equity_p),
            "year": _safe_divide_positive_denominator(total_liabilities_y, equity_y),
            "type": "ratio",
        },
        "roe": {
            "label": "بازده حقوق صاحبان سهام (ROE)",
            "formula": "سود خالص ÷ میانگین حقوق صاحبان سهام",
            "period": _safe_divide(net_income_p, average_equity_p),
            "year": _safe_divide_positive_denominator(net_income_y, equity_y),
            "type": "percent",
            "annualized": False,
        },
        "roa": {
            "label": "بازده دارایی‌ها (ROA)",
            "formula": "سود خالص ÷ میانگین کل دارایی‌ها",
            "period": _safe_divide(net_income_p, average_assets_p),
            "year": _safe_divide(net_income_y, total_assets_y),
            "type": "percent",
            "annualized": False,
        },
        "cashflow_quality": {
            "label": "کیفیت سود (جریان نقد عملیاتی / سود خالص)",
            "formula": "جریان نقد عملیاتی ÷ سود خالص",
            "period": _safe_divide(operating_cashflow_p, net_income_p),
            "year": _safe_divide(operating_cashflow_y, net_income_y),
            "type": "ratio",
        },
    }

    # Insurance statements use a dual-panel balance sheet and sector-specific
    # income concepts. Expose ratios whose definitions are explicit and
    # dashboard-safe instead of forcing manufacturing ratios onto insurers.
    net_premium_p = _find_value_in_sheet(income_sheet, "net_premium")
    net_premium_y = _find_value_in_sheet(income_sheet, "net_premium", "year_value")
    net_claims_p = _find_value_in_sheet(income_sheet, "net_claims_paid")
    net_claims_y = _find_value_in_sheet(income_sheet, "net_claims_paid", "year_value")
    investment_income_p = _find_value_in_sheet(
        income_sheet, "insurance_investment_income"
    )
    investment_income_y = _find_value_in_sheet(
        income_sheet, "insurance_investment_income", "year_value"
    )
    is_insurance = net_premium_p is not None or net_premium_y is not None
    parsed_report["analysis_profile"] = "insurance" if is_insurance else "general"

    if is_insurance:
        ratios["gross_margin"].update({
            "period": None,
            "year": None,
            "applicable": False,
            "unavailable_label": "نامرتبط با صنعت بیمه",
            "unavailable_reason": (
                "در صورت سود و زیان بیمه، بهای تمام‌شده و سود ناخالص "
                "به شکل شرکت‌های تولیدی ارائه نمی‌شود."
            ),
        })
        ratios["current_ratio"].update({
            "period": None,
            "year": None,
            "applicable": False,
            "unavailable_label": "نامرتبط با صنعت بیمه",
            "unavailable_reason": (
                "صورت وضعیت مالی بیمه دارایی‌ها و بدهی‌ها را به جاری و "
                "غیرجاری تفکیک نمی‌کند."
            ),
        })
        ratios["net_claims_paid_ratio"] = {
            "label": "نسبت خسارت پرداختی خالص",
            "formula": "قدر مطلق خسارت و مزایای پرداختی خالص ÷ حق بیمه خالص",
            "period": _safe_divide(
                abs(net_claims_p) if net_claims_p is not None else None,
                net_premium_p,
            ),
            "year": _safe_divide(
                abs(net_claims_y) if net_claims_y is not None else None,
                net_premium_y,
            ),
            "type": "percent",
            "category": "insurance",
        }
        ratios["insurance_investment_income_ratio"] = {
            "label": "سهم درآمد سرمایه‌گذاری بیمه‌ای",
            "formula": "درآمد سرمایه‌گذاری منابع بیمه‌ای ÷ درآمدهای بیمه‌ای",
            "period": _safe_divide(investment_income_p, revenue_p),
            "year": _safe_divide(investment_income_y, revenue_y),
            "type": "percent",
            "category": "insurance",
        }

    if cashflow_sheet is None:
        ratios["cashflow_quality"].update({
            "unavailable_label": "داده ارائه نشده",
            "unavailable_reason": "صورت جریان وجوه نقد در این گزارش وجود ندارد.",
        })

    for key, ratio in ratios.items():
        ratio.setdefault("category", "general")
        ratio["key"] = key
        ratio["available"] = (
            ratio.get("period") is not None or ratio.get("year") is not None
        )

    return ratios


def get_financial_report(report_url: str) -> dict:
    """
    تابع اصلی: دریافت کامل گزارش مالی از کدال.
    
    1. فچ HTML صفحه گزارش
    2. استخراج datasource JSON
    3. پارس به ساختار ساختاریافته
    4. محاسبه شاخص‌های مالی
    
    Returns:
        dict with keys: report, ratios
    """
    cache_key = "codal-financial:" + hashlib.sha256(
        report_url.encode("utf-8")
    ).hexdigest()
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return cached_result

    with _financial_report_locks_guard:
        report_lock = _financial_report_locks.setdefault(cache_key, threading.Lock())

    # Prevent duplicate clicks/requests from launching the same Codal requests
    # at once. Re-check the shared cache after acquiring the lock.
    with report_lock:
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        datasource = extract_datasource(report_url)
        parsed = parse_financial_report(datasource)
        ratios = calculate_financial_ratios(parsed)

        result = {
            "report": parsed,
            "ratios": ratios,
            "dashboard": {
                "profile": parsed.get("analysis_profile", "general"),
                "metrics": list(ratios.values()),
            },
        }
        cache.set(
            cache_key,
            result,
            getattr(settings, "FINANCIAL_REPORT_CACHE_TIMEOUT", 86400),
        )
        return result
