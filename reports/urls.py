from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("api/suggestions/", views.suggestion_api, name="suggestion_api"),
]