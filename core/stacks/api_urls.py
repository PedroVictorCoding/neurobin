from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import PublicStackViewSet, StackScheduleAPIView, StackViewSet, StackItemViewSet

router = DefaultRouter()
router.register(r'stack', StackViewSet, basename='stack')
router.register(r'stackitem', StackItemViewSet, basename='stackitem')
router.register(r'public-stack', PublicStackViewSet, basename='public-stack')

urlpatterns = [
    path('schedule/', StackScheduleAPIView.as_view(), name='stack-schedule'),
    path('', include(router.urls)),
]
