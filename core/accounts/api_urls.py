from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet, UserProfileViewSet

router = DefaultRouter()
router.register(r'user', UserViewSet)
router.register(r'userprofile', UserProfileViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
