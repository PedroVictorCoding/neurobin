from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import IntakeLogViewSet

router = DefaultRouter()
router.register(r'intakelog', IntakeLogViewSet, basename='intakelog')

urlpatterns = [
    path('', include(router.urls)),
]
