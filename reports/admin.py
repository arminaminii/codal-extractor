from django.contrib import admin
from .models import Announcement, Company


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("tracking_id", "symbol", "title_short", "publish_date", "created_at")
    list_filter = ("symbol", "letter_code", "publish_date")
    search_fields = ("symbol", "title", "tracking_id")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-publish_date",)

    @admin.display(description="عنوان (خلاصه)")
    def title_short(self, obj):
        if len(obj.title) > 80:
            return obj.title[:80] + "..."
        return obj.title


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("symbol", "name", "sector", "sector_icon")
    search_fields = ("symbol", "name", "sector")