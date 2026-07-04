from django.shortcuts import render

import requests

from .services import get_or_fetch_announcements


def home(request):
    """ویوی صفحه اصلی - فرم جستجو"""
    announcements = []
    symbol_query = ""
    error_message = ""
    is_fresh_fetch = False

    if request.method == "GET" and "symbol" in request.GET:
        symbol_query = request.GET.get("symbol", "").strip()

        if not symbol_query:
            error_message = "لطفاً نام نماد را وارد کنید."
        elif len(symbol_query) > 100:
            error_message = "نام نماد بیش از حد طولانی است."
        else:
            try:
                announcements = get_or_fetch_announcements(symbol_query)

                if not announcements:
                    error_message = (
                        f"اطلاعیه‌ای برای نماد «{symbol_query}» یافت نشد. "
                        "لطفاً نام نماد را بررسی کنید."
                    )
            except requests.ConnectionError:
                error_message = (
                    "خطا در اتصال به سرور کدال. "
                    "لطفاً اتصال اینترنت خود را بررسی کرده و دوباره تلاش کنید."
                )
            except requests.Timeout:
                error_message = "پاسخی از سرور کدال دریافت نشد (تایم‌اوت). لطفاً دوباره تلاش کنید."
            except requests.RequestException as e:
                error_message = f"خطای شبکه در ارتباط با کدال: {str(e)}"
            except Exception as e:
                error_message = f"خطای پیش‌بینی‌نشده: {str(e)}"

    context = {
        "announcements": announcements,
        "symbol_query": symbol_query,
        "error_message": error_message,
        "total_results": len(announcements),
    }

    return render(request, "reports/search.html", context)