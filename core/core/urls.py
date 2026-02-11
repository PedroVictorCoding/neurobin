"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from . import views
from .api_views import api_root

urlpatterns = [
    path('robots.txt', views.robots_txt, name='robots_txt'),
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('demo/effect-curves/', views.effect_curves_demo, name='effect_curves_demo'),
    path('credits/', views.credits, name='credits'),
    path('compounds/', include('compounds.urls')),
    path('accounts/', include('accounts.urls')),
    path('logs/', include('logs.urls')),
    path('intake/', include('logs.urls')),
    path('research/', include('research.urls')),
    path('change-requests/', include('change_requests.urls')),
    path('stacks/', include('stacks.urls')),
    
    # API Root
    path('api/', api_root, name='api_root'),
    
    # API URLs
    path('api/compounds/', include('compounds.api_urls')),
    path('api/accounts/', include('accounts.api_urls')),
    path('api/logs/', include('logs.api_urls')),
    path('api/research/', include('research.api_urls')),
    path('api/stacks/', include('stacks.api_urls')),
    
    # JWT Authentication
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]

# Serve static files during development
if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns
    urlpatterns += staticfiles_urlpatterns()
    
    # Serve media files during development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
