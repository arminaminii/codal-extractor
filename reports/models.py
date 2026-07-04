from django.db import models


class Announcement(models.Model):
    """
    مدل اطلاعیه‌های کدال
    هر رکورد نمایانگر یک اطلاعیه منتشر شده در سامانه کدال است.
    """

    tracking_id = models.PositiveBigIntegerField(
        primary_key=True,
        verbose_name="شناسه رهگیری کدال",
        help_text="شناسه یکتای هر اطلاعیه در سامانه کدال"
    )

    symbol = models.CharField(
        max_length=100,
        verbose_name="نماد",
        db_index=True,
        help_text="نام نماد بورسی (مثلاً فولاد)"
    )

    title = models.CharField(
        max_length=500,
        verbose_name="عنوان اطلاعیه",
        help_text="عنوان کامل اطلاعیه"
    )

    publish_date = models.DateTimeField(
        verbose_name="تاریخ انتشار",
        help_text="تاریخ و ساعت انتشار اطلاعیه",
        null=True,
        blank=True,
    )

    direct_link = models.URLField(
        max_length=1000,
        verbose_name="لینک مستقیم",
        help_text="لینک مستقیم به صفحه گزارش در سایت کدال"
    )

    letter_code = models.CharField(
        max_length=50,
        verbose_name="کد نامه",
        blank=True,
        default="",
        help_text="کد نوع نامه/گزارش"
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="تاریخ ثبت در دیتابیس"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="تاریخ بروزرسانی"
    )

    class Meta:
        ordering = ["-publish_date"]
        verbose_name = "اطلاعیه"
        verbose_name_plural = "اطلاعیه‌ها"
        indexes = [
            models.Index(fields=["symbol", "-publish_date"], name="idx_symbol_publish_date"),
        ]

    def __str__(self):
        return f"[{self.symbol}] {self.title[:60]}..."


class Company(models.Model):
    symbol = models.CharField(max_length=50, primary_key=True, verbose_name="نماد")
    name = models.CharField(max_length=200, verbose_name="نام شرکت")
    sector = models.CharField(max_length=100, verbose_name="صنعت")
    sector_icon = models.CharField(max_length=10, default="📊", verbose_name="آیکون صنعت")

    class Meta:
        verbose_name = "شرکت"
        verbose_name_plural = "شرکت‌ها"

    def __str__(self):
        return f"{self.symbol} - {self.name}"