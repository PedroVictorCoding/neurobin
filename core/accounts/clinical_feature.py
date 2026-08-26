from django.conf import settings
from rest_framework.exceptions import NotFound
from rest_framework.permissions import BasePermission


def metabolic_feature_allowed(user):
    if not settings.METABOLIC_ASSESSMENT_ENABLED or not user or not user.is_authenticated:
        return False
    return bool(user.is_staff and (
        not settings.METABOLIC_ASSESSMENT_STAFF_ALLOWLIST
        or user.username in settings.METABOLIC_ASSESSMENT_STAFF_ALLOWLIST
    ))


class MetabolicFeaturePermission(BasePermission):
    def has_permission(self, request, view):
        if not metabolic_feature_allowed(request.user):
            raise NotFound()
        return True
