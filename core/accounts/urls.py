from django.urls import path
from .views import (
    custom_logout,
    edit_profile,
    profile_dashboard,
    register,
    verify_email,
    verify_email_sent,
)
from django.contrib.auth import views as auth_views
from .forms import StyledAuthenticationForm

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html', authentication_form=StyledAuthenticationForm), name='login'),
    path('logout/', custom_logout, name='logout'),
    path('register/', register, name='register'),
    path('register/verify-email/sent/', verify_email_sent, name='verify_email_sent'),
    path('verify-email/<uuid:token>/', verify_email, name='verify_email'),
    path('profile/', profile_dashboard, name='profile_dashboard'),
    path('profile/edit/', edit_profile, name='edit_profile'),
    path('profile/<str:username>/', profile_dashboard, name='user_profile'),
]
