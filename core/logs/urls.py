from django.urls import path
from . import views

urlpatterns = [
    path('add/', views.log_intake, name='log_intake'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),
    path('ip-analytics/', views.ip_analytics_dashboard, name='ip_analytics_dashboard'),
]
