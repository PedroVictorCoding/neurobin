from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CompoundCategoriesViewSet,
    TargetViewSet,
    CompoundMechanismOfActionViewSet,
    CompoundViewSet,
    CompoundRatingViewSet,
    CompoundSafetyScreeningViewSet,
    EffectWindowViewSet
)

router = DefaultRouter()
router.register(r'compoundcategories', CompoundCategoriesViewSet)
router.register(r'target', TargetViewSet)
router.register(r'compoundmechanismofaction', CompoundMechanismOfActionViewSet)
router.register(r'compound', CompoundViewSet)
router.register(r'compoundrating', CompoundRatingViewSet)
router.register(r'compoundsafetyscreening', CompoundSafetyScreeningViewSet)
router.register(r'effectwindow', EffectWindowViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
