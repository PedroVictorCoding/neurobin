from datetime import datetime, timedelta

from django.db.models import Count
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Stack, StackItem
from .serializers import PublicStackSerializer, StackSerializer, StackItemSerializer
from .services import get_schedule_window, iter_upcoming_occurrences, take_stack_item


class StackViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows users to view and edit their stacks.
    """
    serializer_class = StackSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Stack.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class StackItemViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows users to view and edit items in their stacks.
    """
    serializer_class = StackItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = StackItem.objects.filter(stack__user=self.request.user)
        stack_param = self.request.query_params.get('stack')
        if stack_param:
            qs = qs.filter(stack_id=stack_param)
        return qs

    def perform_create(self, serializer):
        stack = serializer.validated_data['stack']
        if stack.user_id != self.request.user.id:
            raise PermissionDenied('You can only add items to your own stacks.')
        serializer.save()

    def perform_update(self, serializer):
        stack = serializer.validated_data.get('stack', serializer.instance.stack)
        if stack.user_id != self.request.user.id:
            raise PermissionDenied('You can only move items within your own stacks.')
        serializer.save()

    @action(detail=True, methods=['post'])
    def take(self, request, pk=None):
        item = self.get_object()
        taken_at_raw = request.data.get('taken_at')
        taken_at = None
        if taken_at_raw:
            try:
                taken_at_str = str(taken_at_raw).replace('Z', '+00:00')
                taken_at = datetime.fromisoformat(taken_at_str)
                if timezone.is_naive(taken_at):
                    taken_at = timezone.make_aware(taken_at, timezone.get_current_timezone())
            except ValueError:
                return Response({'detail': 'Invalid taken_at (expected ISO 8601 datetime).'}, status=status.HTTP_400_BAD_REQUEST)

        scheduled_for_raw = request.data.get('scheduled_for')
        scheduled_for = None
        if scheduled_for_raw:
            try:
                scheduled_for_str = str(scheduled_for_raw).replace('Z', '+00:00')
                scheduled_for = datetime.fromisoformat(scheduled_for_str)
                if timezone.is_naive(scheduled_for):
                    scheduled_for = timezone.make_aware(scheduled_for, timezone.get_current_timezone())
            except ValueError:
                return Response({'detail': 'Invalid scheduled_for (expected ISO 8601 datetime).'}, status=status.HTTP_400_BAD_REQUEST)

        intake_log = take_stack_item(item, user=request.user, taken_at=taken_at, scheduled_for=scheduled_for)
        return Response(
            {
                'intake_log_id': intake_log.id,
                'next_intake_time': item.intake_time,
            },
            status=status.HTTP_201_CREATED,
        )


class PublicStackViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only API for public stacks (owned by anyone). Includes a copy action.
    """
    serializer_class = PublicStackSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return (
            Stack.objects.filter(visibility='public')
            .annotate(usage_count=Count('copies', distinct=True))
            .select_related('user')
            .prefetch_related('items__compound')
            .order_by('-usage_count', '-created')
        )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def copy(self, request, pk=None):
        source_stack = self.get_object()
        if source_stack.user_id == request.user.id:
            return Response({'detail': "You can't copy your own stack."}, status=status.HTTP_400_BAD_REQUEST)

        new_stack = Stack.objects.create(
            user=request.user,
            name=source_stack.name,
            description=source_stack.description,
            visibility='private',
            is_active=False,
            copied_from=source_stack,
            copied_at=timezone.now(),
        )

        items_to_create = []
        for source_item in source_stack.items.all():
            items_to_create.append(
                StackItem(
                    stack=new_stack,
                    compound=source_item.compound,
                    dosage_amount=source_item.dosage_amount,
                    dosage_unit=source_item.dosage_unit,
                    time_of_day=source_item.time_of_day,
                    intake_time=source_item.intake_time,
                    recurrence_interval=source_item.recurrence_interval,
                    recurrence_unit=source_item.recurrence_unit,
                    order=source_item.order,
                    notes=source_item.notes,
                    completed=False,
                )
            )

        if items_to_create:
            StackItem.objects.bulk_create(items_to_create)

        return Response(StackSerializer(new_stack, context={'request': request}).data, status=status.HTTP_201_CREATED)


class StackScheduleAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            days = int(request.query_params.get('days', '7'))
        except ValueError:
            return Response({'detail': 'days must be an integer.'}, status=status.HTTP_400_BAD_REQUEST)
        days = max(1, min(days, 90))

        try:
            limit = int(request.query_params.get('limit', '200'))
        except ValueError:
            return Response({'detail': 'limit must be an integer.'}, status=status.HTTP_400_BAD_REQUEST)
        limit = max(1, min(limit, 1000))

        now = timezone.now()
        period = (request.query_params.get('period') or '').strip().lower()
        if period in {'day', 'week', 'month'}:
            window_start, until = get_schedule_window(now=now, period=period)
        else:
            until = now + timedelta(days=days)
            include_past = str(request.query_params.get('include_past', '0')).lower() in {'1', 'true', 'yes'}
            window_start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0) if include_past else now

        items = (
            StackItem.objects.filter(stack__user=request.user, stack__is_active=True)
            .select_related('stack', 'compound')
        )
        occurrences = iter_upcoming_occurrences(items, now=now, until=until, window_start=window_start)
        occurrences = occurrences[:limit]

        return Response(
            [
                {
                    'stack_id': o.stack_id,
                    'stack_name': o.stack_name,
                    'stack_item_id': o.stack_item_id,
                    'compound_id': o.compound_id,
                    'compound_name': o.compound_name,
                    'scheduled_for': o.scheduled_for,
                    'dosage_amount': o.dosage_amount,
                    'dosage_unit': o.dosage_unit,
                    'time_of_day': o.time_of_day,
                }
                for o in occurrences
            ]
        )
