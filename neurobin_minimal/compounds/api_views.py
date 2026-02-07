from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import Compound
from .serializers import CompoundSerializer


class CompoundViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CompoundSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Compound.objects.all()
