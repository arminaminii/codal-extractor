import logging

import requests
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .models import Announcement, Company
from .services import (
    _normalize_persian,
    FINANCIAL_STATEMENT_CODES,
    get_financial_report,
    categorize_letter_code,
    get_all_sectors,
    get_companies_by_sector,
    get_or_fetch_announcements,
    search_companies,
)

logger = logging.getLogger(__name__)


def home(request):
    """
    Company selection page.
    - GET param 'symbol': redirect to /reports/<symbol>/
    - GET param 'sector': pass to template for showing sector companies
    - Otherwise: render company selection page
    """
    # If symbol param present, redirect to reports page
    symbol = request.GET.get("symbol", "").strip()
    if symbol:
        return redirect("reports", symbol=symbol)

    sector = request.GET.get("sector", "").strip()
    sectors = get_all_sectors()

    context = {
        "sectors": sectors,
        "sector": sector,
    }

    return render(request, "reports/home.html", context)


def reports(request, symbol):
    """
    Reports page for a specific company symbol.
    - GET param 'category': filter by report category
    - GET param 'refresh': if "1", force re-fetch from Codal API
    - Fetches announcements and categorizes them
    """
    category_filter = request.GET.get("category", "").strip()
    force_refresh = request.GET.get("refresh", "").strip() == "1"

    # Normalize symbol early so template and DB queries all use same value
    symbol = _normalize_persian(symbol)
    logger.info(
        "Reports view: symbol=%s force_refresh=%s category=%s",
        symbol, force_refresh, category_filter,
    )

    # --- Fetch announcements ---
    fetch_error = None
    announcements = []
    try:
        announcements = get_or_fetch_announcements(symbol, force_refresh=force_refresh)
    except requests.ConnectionError:
        fetch_error = "خطا در اتصال به سرور کدال. لطفاً اتصال اینترنت خود را بررسی کنید."
        logger.error("Connection error fetching announcements for %s", symbol)
    except requests.Timeout:
        fetch_error = "درخواست به سرور کدال طول کشید و قطع شد. لطفاً دوباره تلاش کنید."
        logger.error("Timeout fetching announcements for %s", symbol)
    except requests.RequestException as e:
        fetch_error = f"خطا در دریافت اطلاعات از کدال: {e}"
        logger.error("Request error fetching announcements for %s: %s", symbol, e)

    logger.info("Reports view: got %d announcements for %s", len(announcements), symbol)

    # Get company info from DB (also normalize)
    try:
        company = Company.objects.get(symbol=symbol)
        company_info = {
            "symbol": company.symbol,
            "name": company.name,
            "sector": company.sector,
            "sector_icon": company.sector_icon,
        }
    except Company.DoesNotExist:
        company_info = None

    # Categorize each announcement
    all_categorized = []
    seen_categories = {}  # category_key -> {category, label, color}
    category_counts = {}

    for ann in announcements:
        cat = categorize_letter_code(ann.letter_code)
        lc = (ann.letter_code or "").strip()
        # فقط صورت‌های مالی واقعی (ن-۱۰، ن-۳۱ و ...) قابل تحلیل هستند
        can_analyze = lc in FINANCIAL_STATEMENT_CODES
        entry = {
            "tracking_id": ann.tracking_id,
            "symbol": ann.symbol,
            "title": ann.title,
            "publish_date": ann.publish_date,
            "direct_link": ann.direct_link,
            "letter_code": ann.letter_code,
            "category": cat["category"],
            "category_label": cat["label"],
            "category_color": cat["color"],
            "can_analyze": can_analyze,
        }
        all_categorized.append(entry)
        seen_categories[cat["category"]] = cat
        category_counts[cat["category"]] = category_counts.get(cat["category"], 0) + 1

    # Build categories list with counts (ordered by a fixed priority)
    category_order = [
        "financial", "disclosure", "assembly",
        "capital_increase", "dividend", "monthly",
        "management", "corporate", "other",
    ]
    categories = []
    for key in category_order:
        if key in seen_categories:
            cat_info = dict(seen_categories[key])
            cat_info["count"] = category_counts.get(key, 0)
            categories.append(cat_info)

    # Apply category filter if specified
    if category_filter:
        categorized_announcements = [
            a for a in all_categorized
            if a["category"] == category_filter
        ]
    else:
        categorized_announcements = all_categorized

    context = {
        "symbol": symbol,
        "company_info": company_info,
        "announcements": categorized_announcements,
        "categories": categories,
        "category_filter": category_filter,
        "total_results": len(categorized_announcements),
        "fetch_error": fetch_error,
    }

    return render(request, "reports/reports.html", context)


def suggestion_api(request):
    """
    Autocomplete API for company search.
    GET params:
      - q: search query
      - sector: optional sector filter
    """
    query = request.GET.get("q", "").strip()
    sector = request.GET.get("sector", "").strip()

    if not query:
        return JsonResponse([], safe=False)

    results = search_companies(query, limit=12, sector=sector)
    return JsonResponse(results, safe=False)


def sector_list_api(request):
    """
    API endpoint: return list of sectors with company counts.
    """
    sectors = get_all_sectors()
    return JsonResponse(sectors, safe=False)


def company_list_api(request):
    """
    API endpoint: return all companies in a given sector.
    GET param: sector (required)
    """
    sector = request.GET.get("sector", "").strip()

    if not sector:
        return JsonResponse({"error": "sector parameter is required"}, status=400)

    companies = get_companies_by_sector(sector)
    return JsonResponse(companies, safe=False)


def financial_detail(request, tracking_id: int):
    """
    صفحه جزئیات مالی: استخراج و نمایش داده‌های ساختاریافته از صفحه گزارش کدال.
    وقتی کاربر روی دکمه «تحلیل مالی» کلیک می‌کند این view صدا زده می‌شود.
    """
    announcement = get_object_or_404(Announcement, tracking_id=tracking_id)

    try:
        result = get_financial_report(announcement.direct_link)
    except ConnectionError as e:
        logger.error("Connection error for report %s: %s", tracking_id, e)
        return render(request, "reports/error.html", {
            "error_title": announcement.title,
            "error_msg": str(e),
            "symbol": announcement.symbol,
        })
    except (ValueError, TypeError) as e:
        logger.error("Parse error for report %s: %s", tracking_id, e)
        return render(request, "reports/error.html", {
            "error_title": announcement.title,
            "error_msg": str(e),
            "symbol": announcement.symbol,
        })
    except Exception as e:
        logger.exception("Unexpected error for report %s", tracking_id)
        return render(request, "reports/error.html", {
            "error_title": announcement.title,
            "error_msg": f"خطای ناشناخته: {e}",
            "symbol": announcement.symbol,
        })

    parsed = result["report"]
    ratios = result["ratios"]

    income_sheets = [s for s in parsed["sheets"] if s.get("category") == "income"]
    balance_sheets = [s for s in parsed["sheets"] if s.get("category") == "balance"]
    cashflow_sheets = [s for s in parsed["sheets"] if s.get("category") == "cashflow"]
    note_sheets = [s for s in parsed["sheets"] if s.get("category") == "notes"]

    has_ratios = any(
        r.get("period") is not None or r.get("year") is not None
        for r in ratios.values()
    )
    has_data = bool(income_sheets or balance_sheets or cashflow_sheets or note_sheets)

    return render(request, "reports/financial_detail.html", {
        "announcement": announcement,
        "report": parsed,
        "ratios": ratios,
        "has_ratios": has_ratios,
        "has_data": has_data,
        "income_sheets": income_sheets,
        "balance_sheets": balance_sheets,
        "cashflow_sheets": cashflow_sheets,
        "note_sheets": note_sheets,
    })