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

# --- Default params (PublisherType=1 is REQUIRED, CompanyState=0) ---
DEFAULT_PARAMS = {
    "Category": -1,
    "PublisherType": 1,        # ناشران — REQUIRED
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
    Parse Codal /Date(ms)/ format into a datetime object.
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
    Send GET request to Codal API and retrieve list of announcements.

    Args:
        symbol: Stock symbol (e.g. "فولاد")
        length: Number of results (-1 = all)
        page: Page number

    Returns:
        List of dicts with announcement data

    Raises:
        requests.RequestException: On network error
    """
    params = {
        **DEFAULT_PARAMS,
        "Symbol": symbol,
        "Length": length,
        "PageNumber": page,
    }

    logger.info(
        "Sending GET request to Codal API for symbol: %s | params: %s",
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
        logger.warning("Codal API response missing 'Letters' field. Response: %s", str(data)[:300])
        return []

    letters = data.get("Letters", [])
    results = []

    for item in letters:
        tracing_no = item.get("TracingNo")
        if not tracing_no:
            continue

        publish_date = _parse_codal_date(item.get("PublishDateTime", ""))
        letter_code = item.get("LetterCode", "")

        # Build direct link (relative Url → prefix with https://www.codal.ir)
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

    logger.info("Received %d announcements for symbol %s from Codal API", len(results), symbol)
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


def get_or_fetch_announcements(symbol: str) -> list[Announcement]:
    """
    Main function: check DB first, then fetch from Codal API if needed.
    """
    existing = Announcement.objects.filter(symbol=symbol).order_by("-publish_date")

    if existing.exists():
        logger.info(
            "Found %d existing records in DB for symbol %s",
            existing.count(),
            symbol,
        )
        return list(existing)

    logger.info("No records in DB. Fetching from Codal for symbol: %s", symbol)

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

    Returns:
        dict with keys: category, label, color
    """
    lc = (letter_code or "").strip()

    # Assembly — مجامع عمومی (check FIRST before generic ن-)
    if any(kw in lc for kw in ("مجمع", "ن-۵۶", "ن-۵۷", "ن-۵۸", "ن-۵۹", "ن-۶۰")):
        return {"category": "assembly", "label": "مجامع عمومی", "color": "#a78bfa"}

    # Management report — گزارش تفسیری / هیئت مدیره (ن-۲)
    if lc in ("ن-۲", "N-2") or any(kw in lc for kw in ("هیئت مدیره", "گزارش فعالیت")):
        return {"category": "management", "label": "گزارش هیئت مدیره", "color": "#fb923c"}

    # Monthly report — گزارش ماهانه
    if any(kw in lc for kw in ("ماهانه", "گ.م", "فعالیت ماهانه")):
        return {"category": "monthly", "label": "گزارش ماهانه", "color": "#60a5fa"}

    # Capital increase — افزایش سرمایه
    if any(kw in lc for kw in ("افزایش سرمایه", "حق تقدم", "ن-۲۶")):
        return {"category": "capital_increase", "label": "افزایش سرمایه", "color": "#34d399"}

    # Dividend — سود نقدی (before disclosure, exclude "سود و زیان")
    if ("سود" in lc or "تقسیم" in lc) and "سود و زیان" not in lc:
        return {"category": "dividend", "label": "سود نقدی", "color": "#f472b6"}

    # Disclosure — افشای اطلاعات بااهمیت
    if any(kw in lc for kw in ("الف", "ب", "شم", "افشا", "ش.", "اطلاعات با اهمیت")):
        return {"category": "disclosure", "label": "افشای اطلاعات بااهمیت", "color": "#f59e0b"}

    # Financial statements — صورت‌های مالی (general ن- prefix)
    if lc in ("N-1", "ن-۱") or lc.startswith("ن-"):
        return {"category": "financial", "label": "صورت‌های مالی", "color": "#22d3ee"}

    # Other — سایر
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