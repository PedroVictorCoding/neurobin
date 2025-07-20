from django.urls import path
from . import views

urlpatterns = [
    path('add/', views.log_intake, name='log_intake'),
    path('timeline/', views.intake_timeline, name='intake_timeline'),
    path('analytics/', views.analytics_dashboard, name='analytics_dashboard'),
]