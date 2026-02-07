from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import StackViewSet, StackItemViewSet

router = DefaultRouter()
router.register(r'stack', StackViewSet, basename='stack')
router.register(r'stackitem', StackItemViewSet, basename='stackitem')

urlpatterns = [
    path('', include(router.urls)),
]