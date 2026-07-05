from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("reports/<str:symbol>/", views.reports, name="reports"),
    path("report/<int:tracking_id>/", views.financial_detail, name="financial_detail"),
    path("api/suggestions/", views.suggestion_api, name="suggestion_api"),
    path("api/sectors/", views.sector_list_api, name="sector_list_api"),
    path("api/companies/", views.company_list_api, name="company_list_api"),
]