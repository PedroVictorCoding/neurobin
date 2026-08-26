from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import UserViewSet, UserProfileViewSet
from .clinical_api import ClinicalDocumentViewSet, ClinicalProfileViewSet

router = DefaultRouter()
router.register(r'user', UserViewSet)
router.register(r'userprofile', UserProfileViewSet)
router.register(r'clinical-profile', ClinicalProfileViewSet, basename='clinical-profile')
router.register(r'clinical-document', ClinicalDocumentViewSet, basename='clinical-document')

urlpatterns = [
    path('', include(router.urls)),
]
