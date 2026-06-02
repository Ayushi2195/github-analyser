from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("analyze/", views.analyze, name="analyze"),
    path("reports/<str:owner>/<str:repo_name>/", views.cached_report, name="cached_report"),
    path("featured/<str:owner>/<str:repo_name>/", views.featured_report, name="featured_report"),
    path("download/", views.download_pdf, name="download_pdf"),
]
