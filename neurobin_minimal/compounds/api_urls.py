from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import CompoundViewSet

router = DefaultRouter()
router.register(r'compound', CompoundViewSet, basename='compound')

urlpatterns = [
    path('', include(router.urls)),
]