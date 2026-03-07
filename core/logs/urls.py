from django.urls import path
from . import views

urlpatterns = [
    path('add/', views.log_intake, name='log_intake'),
    path('bloodwork/', views.bloodwork_dashboard, name='bloodwork_dashboard'),
    path('bloodwork/<int:pk>/edit/', views.bloodwork_edit, name='bloodwork_edit'),
    path('bloodwork/<int:pk>/delete/', views.bloodwork_delete, name='bloodwork_delete'),
    path('bloodwork/<int:pk>/print/', views.bloodwork_print, name='bloodwork_print'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),
    path('ip-analytics/', views.ip_analytics_dashboard, name='ip_analytics_dashboard'),
]
