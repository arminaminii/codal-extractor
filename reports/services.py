import logging
import re
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
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/112.0.0.0 Safari/537.36"
    ),
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


def fetch_announcements_from_codal(symbol: str) -> list[dict]:
    """
    Fetch announcements from Codal API for a given symbol.

    Simple single-request: Length=-1, PageNumber=1.
    Based on: github.com/yghaderi/codalpy

    Raises:
        requests.RequestException: On network error
    """
    params = {**DEFAULT_PARAMS, "Symbol": symbol}

    logger.info("Fetching Codal API for symbol: %s", symbol)

    response = requests.get(
        CODAL_SEARCH_URL,
        params=params,
        headers=HEADERS,
        timeout=getattr(settings, "CODAL_REQUEST_TIMEOUT", 30),
    )
    response.raise_for_status()

    data = response.json()

    if "Letters" not in data:
        logger.warning(
            "Codal API response missing 'Letters' for %s. Response: %s",
            symbol, str(data)[:300],
        )
        return []

    results = []
    for item in data["Letters"]:
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

    logger.info(
        "Received %d announcements for symbol %s from Codal API",
        len(results), symbol,
    )
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
        symbol: Stock symbol
        force_refresh: If True, always re-fetch from API and update DB.
    """
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

    query_clean = query.strip()
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