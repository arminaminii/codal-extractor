"""
Custom template tags for Codal Expert project.

Provides:
  - sector_svg_icon: Returns inline SVG markup for a given sector name
  - to_jalali: Converts a datetime to Jalali (Shamsi) date string
"""

import jdatetime
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


# ---------------------------------------------------------------------------
# SVG Icons for each sector (no emojis!)
# ---------------------------------------------------------------------------
SECTOR_ICONS: dict[str, str] = {
    "بانکی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-4"/>'
        '<path d="M9 9h.01M9 12h.01M9 15h.01M9 18h.01"/>'
        '</svg>'
    ),
    "صنعت بیمه": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>'
        '</svg>'
    ),
    "خودرویی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<rect x="1" y="3" width="15" height="13" rx="2"/>'
        '<path d="M16 8h4l3 3v5a2 2 0 0 1-2 2h-1"/>'
        '<circle cx="5.5" cy="18.5" r="2.5"/>'
        '<circle cx="18.5" cy="18.5" r="2.5"/>'
        '</svg>'
    ),
    "محصولات شیمیایی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M9 3h6v8l4 8H5l4-8V3z"/>'
        '<path d="M9 3h6"/>'
        '<line x1="10" y1="14" x2="14" y2="14"/>'
        '</svg>'
    ),
    "فلزات": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>'
        '</svg>'
    ),
    "فراورده\u200cهای نفتی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/>'
        '<path d="M12 6v6l4 2"/>'
        '</svg>'
    ),
    "فراورده‌های نفتی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/>'
        '<path d="M12 6v6l4 2"/>'
        '</svg>'
    ),
    "سیمانی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<rect x="2" y="7" width="20" height="10" rx="2"/>'
        '<path d="M16 7V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v3"/>'
        '</svg>'
    ),
    "دارویی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3"/>'
        '<path d="M10.5 8.25h3"/>'
        '<path d="M10.5 11.25h3"/>'
        '</svg>'
    ),
    "کانی\u200cهای غیر فلزی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>'
        '</svg>'
    ),
    "کانی‌های غیر فلزی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>'
        '</svg>'
    ),
    "صنعت ساختمان": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
        '<polyline points="9 22 9 12 15 12 15 22"/>'
        '</svg>'
    ),
    "صنعت مواد غذایی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M18 8h1a4 4 0 010 8h-1"/>'
        '<path d="M2 8h16v9a4 4 0 01-4 4H6a4 4 0 01-4-4V8z"/>'
        '<line x1="6" y1="1" x2="6" y2="4"/>'
        '<line x1="10" y1="1" x2="10" y2="4"/>'
        '<line x1="14" y1="1" x2="14" y2="4"/>'
        '</svg>'
    ),
    "صنعت کاشی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<rect x="3" y="3" width="7" height="7" rx="1"/>'
        '<rect x="14" y="3" width="7" height="7" rx="1"/>'
        '<rect x="3" y="14" width="7" height="7" rx="1"/>'
        '<rect x="14" y="14" width="7" height="7" rx="1"/>'
        '</svg>'
    ),
    "صنعت پیمانکاری": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/>'
        '</svg>'
    ),
    "صنعت حمل و نقل": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<rect x="1" y="3" width="15" height="13" rx="2"/>'
        '<path d="M16 8h2a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2h0"/>'
        '<circle cx="5.5" cy="18.5" r="2.5"/>'
        '<circle cx="18.5" cy="18.5" r="2.5"/>'
        '</svg>'
    ),
    "صنعت رایانه": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>'
        '<line x1="8" y1="21" x2="16" y2="21"/>'
        '<line x1="12" y1="17" x2="12" y2="21"/>'
        '</svg>'
    ),
    "صنعت تولید برق": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>'
        '</svg>'
    ),
    "صنعت دستگاه\u200cهای برقی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>'
        '</svg>'
    ),
    "صنعت دستگاه‌های برقی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>'
        '</svg>'
    ),
    "صنعت لاستیک": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="10"/>'
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M12 2a15 15 0 0 1 4 10 15 15 0 0 1-4 10"/>'
        '<path d="M12 2a15 15 0 0 0-4 10 15 15 0 0 0 4 10"/>'
        '</svg>'
    ),
    "ساخت محصولات فلزی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/>'
        '</svg>'
    ),
    "استخراج فلزات": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M2 22L12 2l10 20H2z"/>'
        '<line x1="12" y1="16" x2="12" y2="12"/>'
        '<line x1="12" y1="8" x2="12.01" y2="8"/>'
        '</svg>'
    ),
    "سرمایه\u200cگذاری": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<line x1="12" y1="1" x2="12" y2="23"/>'
        '<path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/>'
        '</svg>'
    ),
    "سرمایه‌گذاری": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<line x1="12" y1="1" x2="12" y2="23"/>'
        '<path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/>'
        '</svg>'
    ),
    "کشاورزی": (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<path d="M7 20h10"/>'
        '<path d="M10 20c5.5-2.5.8-6.4 3-10"/>'
        '<path d="M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8z"/>'
        '<path d="M14.1 6a7 7 0 00-1.1 4c1.9-.1 3.3-.6 4.3-1.4 1-1 1.6-2.3 1.7-4.6-2.7.1-4 1-4.9 2z"/>'
        '</svg>'
    ),
}

# Default icon for unknown sectors
_DEFAULT_ICON = (
    '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round">'
    '<circle cx="12" cy="12" r="10"/>'
    '<line x1="12" y1="8" x2="12" y2="12"/>'
    '<line x1="12" y1="16" x2="12.01" y2="16"/>'
    '</svg>'
)


@register.simple_tag
def sector_svg_icon(sector_name: str, size: int = 20) -> str:
    """
    Return inline SVG markup for the given sector name.
    Usage: {% sector_svg_icon company.sector %}
    """
    if not sector_name:
        return mark_safe(_DEFAULT_ICON.replace('width="20" height="20"', f'width="{size}" height="{size}"'))

    # Direct lookup
    svg = SECTOR_ICONS.get(sector_name)
    if svg:
        return mark_safe(svg.replace('width="20" height="20"', f'width="{size}" height="{size}"'))

    # Fuzzy: try normalizing zero-width non-joiner
    normalized = sector_name.replace("\u200c", "").replace("‌", "")
    for key, val in SECTOR_ICONS.items():
        if key.replace("\u200c", "").replace("‌", "") == normalized:
            return mark_safe(val.replace('width="20" height="20"', f'width="{size}" height="{size}"'))

    return mark_safe(_DEFAULT_ICON.replace('width="20" height="20"', f'width="{size}" height="{size}"'))


@register.filter
def to_jalali(value):
    """
    Convert a datetime object to a Jalali (Shamsi) date string.
    Usage: {{ ann.publish_date|to_jalali }}
    """
    if value is None:
        return ""
    try:
        jdate = jdatetime.datetime.fromgregorian(datetime=value)
        return f"{jdate.year}/{jdate.month:02d}/{jdate.day:02d}"
    except (ValueError, OSError, OverflowError):
        return ""


@register.filter
def format_num(value):
    """فرمت عدد با جداکننده هزارگان فارسی"""
    if value is None:
        return "—"
    try:
        num = float(value)
        if num == 0:
            return "—"
        return f"{num:,.0f}".replace(",", "٬")
    except (ValueError, TypeError):
        return "—"


@register.filter
def format_ratio(value, ratio_type="percent"):
    """فرمت نسبت یا درصد"""
    if value is None:
        return "—"
    try:
        num = float(value)
        if ratio_type == "ratio":
            return f"{num:.2f}"
        else:
            return f"{num * 100:.1f}%"
    except (ValueError, TypeError):
        return "—"