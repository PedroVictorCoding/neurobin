from django.urls import path, include
from django.contrib import admin
from django.http import JsonResponse


def api_root(request):
    return JsonResponse({
        'endpoints': {
            'stacks': '/api/stacks/',
            'compounds': '/api/compounds/',
            'accounts': '/api/accounts/',
        }
    })

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', api_root),
    path('api/stacks/', include('stacks.api_urls')),
    path('api/compounds/', include('compounds.api_urls')),
    path('api/accounts/', include('accounts.api_urls')),
]
