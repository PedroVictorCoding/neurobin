from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import Stack, StackItem
from .serializers import StackSerializer, StackItemSerializer


class StackViewSet(viewsets.ModelViewSet):
    serializer_class = StackSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Stack.objects.all()


class StackItemViewSet(viewsets.ModelViewSet):
    serializer_class = StackItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return StackItem.objects.select_related('stack').all()
