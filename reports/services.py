import json
import logging
import re
import time
from datetime import datetime, timezone

import requests
from django.conf import settings
from django.db import models as db_models

from .models import Announcement, Company

logger = logging.getLogger(__name__)

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
    """Parse Codal /Date(ms)/ format into a datetime object."""
    if not date_str:
        return None
    match = re.search(r"\((\d+)", date_str)
    if match:
        timestamp_ms = int(match.group(1))
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
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

CODAL_BASE_URL = "https://codal.ir"

# نقشه شیت‌ها: SheetId → نوع شیت
SHEET_CATEGORY_MAP = {
    0: "balance",    # ترازنامه
    1: "income",     # سود و زیان
    2: "cashflow",   # جریان نقد
}

# نام‌های مختلف یک مفهوم مالی در گزارش‌های مختلف شرکت‌ها
CONCEPT_ALIASES = {
    "revenue": ["درآمد عملیاتی", "فروش خالص", "فروش", "درآمد فروش", "درآمد", "Net Revenue", "Revenue", "بهای فروش کالا و خدمات"],
    "cogs": ["بهای تمام شده", "بهای تمام\u200cشده", "بهای تمام شده کالای فروش رفته", "بهای تمام\u200cشده کالای فروش رفته", "Cost of Goods Sold", "Cost of Revenue"],
    "gross_profit": ["سود ناخالص", "سود (زیان) ناخالص", "Gross Profit", "Gross Loss"],
    "operating_profit": ["سود عملیاتی", "سود (زیان) عملیاتی", "Operating Profit", "Operating Income", "سود (زیان) ناخالص عملیاتی"],
    "net_income": ["سود خالص", "سود (زیان) خالص", "Net Income", "Net Profit", "سود (زیان) پس از مالیات"],
    "total_current_assets": ["جمع دارایی‌های جاری", "جمع دارایی جاری", "Current Assets", "Total Current Assets"],
    "total_noncurrent_assets": ["جمع دارایی‌های غیرجاری", "جمع دارایی غیرجاری", "Non-Current Assets"],
    "total_assets": ["جمع کل دارایی‌ها", "جمع دارایی‌ها", "Total Assets", "Total of Assets"],
    "total_current_liabilities": ["جمع بدهی‌های جاری", "جمع بدهی جاری", "Current Liabilities", "Total Current Liabilities"],
    "total_noncurrent_liabilities": ["جمع بدهی‌های غیرجاری", "جمع بدهی غیرجاری", "Non-Current Liabilities"],
    "total_liabilities": ["جمع کل بدهی‌ها", "جمع بدهی‌ها", "Total Liabilities"],
    "total_equity": ["جمع حقوق صاحبان سهام", "حقوق صاحبان سهام", "Total Equity", "Equity", "Shareholders' Equity"],
    "operating_cashflow": ["جریان نقد عملیاتی", "جریان نقد حاصل از فعالیت‌های عملیاتی", "Operating Cash Flow", "Cash from Operating Activities"],
}


def extract_datasource(report_url: str) -> dict:
    """
    دریافت HTML صفحه گزارش کدال و استخراج var datasource = {...}
    
    Args:
        report_url: لینک مستقیم گزارش (مثل https://codal.ir/ReportList.aspx?...)
    
    Returns:
        dict: parsed datasource JSON
    
    Raises:
        ConnectionError: خطا در اتصال
        ValueError: datasource یافت نشد
    """
    full_url = report_url if report_url.startswith("http") else CODAL_BASE_URL + report_url
    
    timeout = getattr(settings, "CODAL_REQUEST_TIMEOUT", 30)
    
    resp = None

    for attempt in range(MAX_RETRIES):
        try:
            logger.info("Fetching report page: %s (attempt %d)", full_url, attempt + 1)
            resp = requests.get(full_url, headers=HEADERS, timeout=timeout)

            if resp.status_code == 429:
                wait = 10 * (2 ** attempt)
                logger.warning("429 on report fetch. Waiting %ds", wait)
                time.sleep(wait)
                continue

            resp.raise_for_status()
            break  # success
        except requests.ConnectionError as e:
            raise ConnectionError(f"خطا در اتصال به کدال: {e}")
        except requests.Timeout:
            raise ConnectionError("درخواست به سرور کدال طول کشید و قطع شد.")
        except requests.RequestException as e:
            raise ConnectionError(f"خطا در دریافت گزارش: {e}")
    else:
        # تمام تلاش‌ها 429 شدند
        raise ConnectionError(
            "درخواست‌های شما بیش از حد مجاز است (429). "
            "لطفاً چند دقیقه صبر کنید و دوباره تلاش کنید."
        )

    html = resp.text

    # استخراج var datasource = {...}
    # از شمارنده آکولاد متعادل استفاده می‌کنیم چون datasource JSON بزرگی است
    # و regex ساده با .*? در اولین }; اشتباه متوقف می‌شود.
    ds_start = html.find("var datasource")
    if ds_start == -1:
        raise ValueError(
            "متغیر datasource در صفحه یافت نشد. "
            "ممکن است این گزارش فرمت قدیمی داشته باشد یا فایل HTML نداشته باشد."
        )

    eq_pos = html.index('=', ds_start)
    json_start = html.index('{', eq_pos)

    # شمارنده آکولاد متعادل + رعایت string‌ها
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
        raise ValueError("نتوانست انتهای JSON datasource را پیدا کند (آکولادها بسته نشدند).")

    json_str = html[json_start:json_end + 1]

    try:
        datasource = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"خطا در پارس JSON datasource: {e}")
    
    logger.info("Datasource extracted successfully. Sheets: %d", len(datasource.get("sheets", [])))
    return datasource


def categorize_sheet(sheet: dict) -> str:
    """تشخیص نوع شیت از روی کد یا عنوان"""
    code = sheet.get("code")
    title = _normalize_persian(sheet.get("title_Fa", ""))
    
    # اول بر اساس کد
    if code in SHEET_CATEGORY_MAP:
        return SHEET_CATEGORY_MAP[code]
    
    # بعد بر اساس عنوان
    if "ترازنامه" in title or "وضعیت مالی" in title:
        return "balance"
    if "سود و زیان" in title or "عملکرد مالی" in title:
        return "income"
    if "جریان" in title and "نقد" in title:
        return "cashflow"
    
    return "notes"


def parse_financial_report(datasource: dict) -> dict:
    """
    پارس datasource به ساختار ساختاریافته برای نمایش در قالب.
    
    Returns:
        dict with keys: title, period, year_end, is_audited, is_consolidated, sheets
        Each sheet has: code, title, category, tables
        Each table has: title, rows
        Each row has: concept, period_value, year_value, row_type, indent
    """
    result = {
        "title": datasource.get("title_Fa", ""),
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
            "title": sheet.get("title_Fa", ""),
            "category": category,
            "tables": [],
        }
        
        for table in sheet.get("tables", []):
            table_data = {
                "title": table.get("title_Fa", ""),
                "rows": [],
            }
            
            # گروه‌بندی سلول‌ها بر اساس آدرس ردیف
            rows_map = {}
            for cell in table.get("cells", []):
                addr = cell.get("address", "")
                row_match = re.match(r'([A-Z]+)(\d+)', addr)
                if not row_match:
                    continue
                row_num = row_match.group(2)
                col_letter = row_match.group(1)
                
                if row_num not in rows_map:
                    rows_map[row_num] = {
                        "concept": "",
                        "period_value": None,
                        "year_value": None,
                        "row_type": cell.get("row_type_name", ""),
                        "indent": 0,
                    }
                
                # ستون A = شرح، بقیه = مقادیر عددی
                if col_letter == "A":
                    concept_text = cell.get("financial_concept") or cell.get("value") or ""
                    rows_map[row_num]["concept"] = _normalize_persian(str(concept_text))
                else:
                    # مقدار دوره جاری
                    val = cell.get("periodEndToDate")
                    if val is not None:
                        try:
                            rows_map[row_num]["period_value"] = float(val)
                        except (ValueError, TypeError):
                            rows_map[row_num]["period_value"] = val
                    
                    # مقدار مقایسه‌ای (سال قبل)
                    val_year = cell.get("yearEndToDate")
                    if val_year is not None:
                        try:
                            rows_map[row_num]["year_value"] = float(val_year)
                        except (ValueError, TypeError):
                            rows_map[row_num]["year_value"] = val_year
            
            # محاسبه indent
            for row_num in rows_map:
                rt = rows_map[row_num]["row_type"]
                if rt in ("Header", "Title", "GroupHeader"):
                    rows_map[row_num]["indent"] = 0
                elif rt == "SubGroupHeader":
                    rows_map[row_num]["indent"] = 1
                else:
                    rows_map[row_num]["indent"] = 2
            
            # مرتب‌سازی بر اساس شماره ردیف
            for row_num in sorted(rows_map.keys(), key=lambda x: int(x)):
                table_data["rows"].append(rows_map[row_num])
            
            sheet_data["tables"].append(table_data)
        
        result["sheets"].append(sheet_data)
    
    return result


def _find_value_in_sheet(sheet: dict, concept_key: str, field: str = "period_value") -> float | None:
    """پیدا کردن مقدار یک مفهوم مالی در یک شیت"""
    if not sheet:
        return None
    aliases = CONCEPT_ALIASES.get(concept_key, [concept_key])
    
    for table in sheet.get("tables", []):
        for row in table.get("rows", []):
            concept = row.get("concept", "")
            for alias in aliases:
                if alias in concept or concept in alias:
                    val = row.get(field)
                    if val is not None:
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            pass
    return None


def _safe_divide(numerator, denominator) -> float | None:
    """تقسیم امن"""
    if numerator is None or denominator is None or denominator == 0:
        return None
    try:
        return float(numerator) / float(denominator)
    except (ValueError, TypeError, ZeroDivisionError):
        return None


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
    
    if gross_profit_p is None and revenue_p is not None and cogs_p is not None:
        gross_profit_p = revenue_p - cogs_p
    
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
    
    if gross_profit_y is None and revenue_y is not None and cogs_y is not None:
        gross_profit_y = revenue_y - cogs_y
    
    return {
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
            "period": _safe_divide(total_liabilities_p, equity_p),
            "year": _safe_divide(total_liabilities_y, equity_y),
            "type": "ratio",
        },
        "roe": {
            "label": "بازده حقوق صاحبان سهام (ROE)",
            "formula": "سود خالص ÷ حقوق صاحبان سهام",
            "period": _safe_divide(net_income_p, equity_p),
            "year": _safe_divide(net_income_y, equity_y),
            "type": "percent",
        },
        "roa": {
            "label": "بازده دارایی‌ها (ROA)",
            "formula": "سود خالص ÷ کل دارایی",
            "period": _safe_divide(net_income_p, total_assets_p),
            "year": _safe_divide(net_income_y, total_assets_y),
            "type": "percent",
        },
        "cashflow_quality": {
            "label": "کیفیت سود (جریان نقد عملیاتی / سود خالص)",
            "formula": "جریان نقد عملیاتی ÷ سود خالص",
            "period": _safe_divide(operating_cashflow_p, net_income_p),
            "year": _safe_divide(operating_cashflow_y, net_income_y),
            "type": "ratio",
        },
    }


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
    datasource = extract_datasource(report_url)
    parsed = parse_financial_report(datasource)
    ratios = calculate_financial_ratios(parsed)
    
    return {
        "report": parsed,
        "ratios": ratios,
    }