from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ResearchSnippetViewSet,
    SnippetReviewViewSet,
    SnippetTagViewSet,
    SnippetTaggingViewSet,
    UserRoleViewSet,
    ResearchSettingsViewSet,
    SnippetCommentViewSet
)

router = DefaultRouter()
router.register(r'researchsnippet', ResearchSnippetViewSet, basename='researchsnippet')
router.register(r'snippetreview', SnippetReviewViewSet)
router.register(r'snippettag', SnippetTagViewSet)
router.register(r'snippettagging', SnippetTaggingViewSet)
router.register(r'userrole', UserRoleViewSet)
router.register(r'researchsettings', ResearchSettingsViewSet)
router.register(r'snippetcomment', SnippetCommentViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
