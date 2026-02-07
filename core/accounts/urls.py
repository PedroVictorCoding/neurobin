from django.urls import path
from .views import register, custom_logout, profile_dashboard, edit_profile
from django.contrib.auth import views as auth_views
from .forms import StyledAuthenticationForm

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html', authentication_form=StyledAuthenticationForm), name='login'),
    path('logout/', custom_logout, name='logout'),
    path('register/', register, name='register'),
    path('profile/', profile_dashboard, name='profile_dashboard'),
    path('profile/edit/', edit_profile, name='edit_profile'),
    path('profile/<str:username>/', profile_dashboard, name='user_profile'),
]
