from django.http import JsonResponse
from django.shortcuts import render

import requests

from .services import get_or_fetch_announcements, search_companies, resolve_search_query


def home(request):
    """ویوی صفحه اصلی - فرم جستجو"""
    announcements = []
    symbol_query = ""
    company_info = None
    error_message = ""

    if request.method == "GET" and "symbol" in request.GET:
        raw_query = request.GET.get("symbol", "").strip()

        if not raw_query:
            error_message = "لطفاً نام نماد یا شرکت را وارد کنید."
        elif len(raw_query) > 100:
            error_message = "عبارت جستجو بیش از حد طولانی است."
        else:
            # رفع مسیر: نام شرکت → نماد
            symbol_query = resolve_search_query(raw_query)

            # اطلاعات شرکت را برای نمایش بگیر
            from .models import Company
            try:
                c = Company.objects.get(symbol=symbol_query)
                company_info = {"symbol": c.symbol, "name": c.name, "sector": c.sector, "sector_icon": c.sector_icon}
            except Company.DoesNotExist:
                company_info = None

            try:
                announcements = get_or_fetch_announcements(symbol_query)

                if not announcements:
                    error_message = (
                        f"اطلاعیه‌ای برای «{raw_query}» یافت نشد. "
                        "لطفاً نام نماد یا شرکت را بررسی کنید."
                    )
            except requests.ConnectionError:
                error_message = "خطا در اتصال به سرور کدال. لطفاً اتصال اینترنت را بررسی کنید."
            except requests.Timeout:
                error_message = "پاسخی از سرور کدال دریافت نشد (تایم‌اوت)."
            except requests.RequestException as e:
                error_message = f"خطای شبکه در ارتباط با کدال: {str(e)}"
            except Exception as e:
                error_message = f"خطای پیش‌بینی‌نشده: {str(e)}"

    context = {
        "announcements": announcements,
        "symbol_query": symbol_query,
        "raw_query": request.GET.get("symbol", "").strip() if "symbol" in request.GET else "",
        "company_info": company_info,
        "error_message": error_message,
        "total_results": len(announcements),
    }

    return render(request, "reports/search.html", context)


def suggestion_api(request):
    """API اتوکامپلت جستجوی شرکت‌ها"""
    query = request.GET.get("q", "").strip()
    if not query:
        return JsonResponse([], safe=False)

    results = search_companies(query)
    return JsonResponse(results, safe=False)