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
from .api_views import (
    CompoundTargetInteractionListView,
    CompoundToCompoundInteractionListView,
    compound_interactions,
    compound_pair_interactions,
    compound_search_api
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
    path('compound-target-interactions/', CompoundTargetInteractionListView.as_view(), name='compound-target-interactions'),
    path('compound-compound-interactions/', CompoundToCompoundInteractionListView.as_view(), name='compound-compound-interactions'),
    path('compound/<int:compound_id>/interactions/', compound_interactions, name='compound-interactions'),
    path('compound-pair-interactions/', compound_pair_interactions, name='compound-pair-interactions'),
    path('compound-search/', compound_search_api, name='compound-search-api'),
]
