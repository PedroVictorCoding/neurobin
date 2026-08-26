from datetime import datetime, timedelta
import json

from django.db.models import Count
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from logs.models import IntakeLog
from .models import Stack, StackItem
from .serializers import PublicStackSerializer, StackSerializer, StackItemSerializer
from .services import (
    get_schedule_window,
    iter_upcoming_occurrences,
    take_stack_item,
    untake_stack_item_occurrence,
)
from .trait_engine import analyze_stack_character_sheet, recommend_stack_builds
from .risk import get_or_compute_stack_risk
from .metabolic import assess_metabolic_interaction, build_pbpk_export


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

    @action(detail=True, methods=['get'])
    def metabolic_assessment(self, request, pk=None):
        stack = self.get_object()
        if stack.user_id != request.user.id:
            raise PermissionDenied('Clinical-context assessments are owner-only.')
        result = get_or_compute_stack_risk(stack, list(stack.items.select_related('compound')))
        try:
            profile = request.user.clinical_profile
        except ObjectDoesNotExist:
            profile = None
        return Response(assess_metabolic_interaction(
            stack.items.select_related('compound'),
            predicted_compounds=result.assessment.details.get('compounds', []),
            clinical_profile=profile,
        ))

    @action(detail=True, methods=['get'])
    def pbpk_export(self, request, pk=None):
        stack = self.get_object()
        if stack.user_id != request.user.id:
            raise PermissionDenied('PBPK exports are owner-only.')
        result = get_or_compute_stack_risk(stack, list(stack.items.select_related('compound')))
        assessment = result.assessment.details.get('metabolic_interaction_potential', {})
        try:
            profile = request.user.clinical_profile
        except ObjectDoesNotExist:
            profile = None
        return Response(build_pbpk_export(stack, assessment, clinical_profile=profile))


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

    @staticmethod
    def _parse_optional_iso_datetime(value, *, field_name):
        if not value:
            return None, None
        try:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt.replace(microsecond=0), None
        except ValueError:
            return None, Response(
                {'detail': f'Invalid {field_name} (expected ISO 8601 datetime).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=['post'])
    def take(self, request, pk=None):
        item = self.get_object()
        taken_at, taken_at_error = self._parse_optional_iso_datetime(
            request.data.get('taken_at'),
            field_name='taken_at',
        )
        if taken_at_error:
            return taken_at_error

        scheduled_for, scheduled_for_error = self._parse_optional_iso_datetime(
            request.data.get('scheduled_for'),
            field_name='scheduled_for',
        )
        if scheduled_for_error:
            return scheduled_for_error

        intake_log = take_stack_item(item, user=request.user, taken_at=taken_at, scheduled_for=scheduled_for)
        return Response(
            {
                'intake_log_id': intake_log.id,
                'next_intake_time': item.intake_time,
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def untake(self, request, pk=None):
        item = self.get_object()
        scheduled_for_raw = request.data.get('scheduled_for')
        if not scheduled_for_raw:
            return Response(
                {'detail': 'scheduled_for is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        scheduled_for, scheduled_for_error = self._parse_optional_iso_datetime(
            scheduled_for_raw,
            field_name='scheduled_for',
        )
        if scheduled_for_error:
            return scheduled_for_error

        deleted_count = untake_stack_item_occurrence(
            item,
            user=request.user,
            scheduled_for=scheduled_for,
        )
        return Response(
            {
                'deleted_count': deleted_count,
                'is_taken': False,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['get'])
    def intake_status(self, request, pk=None):
        item = self.get_object()
        scheduled_for_raw = (request.query_params.get('scheduled_for') or '').strip()
        if not scheduled_for_raw:
            return Response(
                {'detail': 'scheduled_for query parameter is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        scheduled_for, scheduled_for_error = self._parse_optional_iso_datetime(
            scheduled_for_raw,
            field_name='scheduled_for',
        )
        if scheduled_for_error:
            return scheduled_for_error

        is_taken = IntakeLog.objects.filter(
            user=request.user,
            stack_item=item,
            scheduled_for=scheduled_for,
        ).exists()
        return Response(
            {
                'stack_item_id': item.id,
                'scheduled_for': scheduled_for,
                'is_taken': is_taken,
            },
            status=status.HTTP_200_OK,
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


class StackRecommendationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        stack_id = request.query_params.get("stack_id")
        if not stack_id:
            return Response(
                {"detail": "Provide stack_id query parameter for stack analysis."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            stack_id = int(stack_id)
        except ValueError:
            return Response({"detail": "stack_id must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

        stack = Stack.objects.filter(id=stack_id, user=request.user).first()
        if not stack:
            return Response({"detail": "Stack not found."}, status=status.HTTP_404_NOT_FOUND)

        goals = request.query_params.get("goals")
        max_traits = request.query_params.get("max_traits")
        try:
            goals_data = {} if not goals else json.loads(goals)
            max_traits_data = {} if not max_traits else json.loads(max_traits)
        except Exception:
            return Response(
                {"detail": "goals and max_traits must be valid JSON objects."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        compound_ids = list(
            StackItem.objects.filter(stack_id=stack.id).values_list("compound_id", flat=True)
        )
        payload = analyze_stack_character_sheet(
            compound_ids=compound_ids,
            goals=goals_data,
            constraints={
                "max_traits": max_traits_data,
                "no_cyp3a4_conflicts": str(request.query_params.get("no_cyp3a4_conflicts", "0")).lower()
                in {"1", "true", "yes"},
                "required_route": request.query_params.get("required_route", ""),
            },
            min_evidence_confidence=(request.query_params.get("min_confidence") or "low"),
            desired_context={
                "species": request.query_params.get("species", ""),
                "assay_type": request.query_params.get("assay_type", ""),
                "route": request.query_params.get("route", ""),
            },
        )
        payload["stack_id"] = stack.id
        payload["stack_name"] = stack.name
        return Response(payload)

    def post(self, request):
        data = request.data or {}
        goals = data.get("goals") or {}
        constraints = data.get("constraints") or {}
        candidate_ids = data.get("candidate_compound_ids") or None
        output_mode = str(data.get("output_mode") or data.get("mode") or "ranked")
        include_distribution_raw = data.get("include_distribution")
        if include_distribution_raw is None:
            include_distribution = None
        elif isinstance(include_distribution_raw, bool):
            include_distribution = include_distribution_raw
        else:
            include_distribution = str(include_distribution_raw).strip().lower() in {"1", "true", "yes", "on"}
        base_compound_ids = []
        stack_id = data.get("stack_id")
        if stack_id is not None:
            try:
                stack_id = int(stack_id)
            except (TypeError, ValueError):
                return Response({"detail": "stack_id must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
            stack = Stack.objects.filter(id=stack_id, user=request.user).first()
            if not stack:
                return Response({"detail": "Stack not found."}, status=status.HTTP_404_NOT_FOUND)
            base_compound_ids = list(
                StackItem.objects.filter(stack_id=stack.id).values_list("compound_id", flat=True)
            )

        try:
            payload = recommend_stack_builds(
                goals=goals,
                constraints=constraints,
                candidate_compound_ids=candidate_ids,
                base_compound_ids=base_compound_ids or None,
                max_stack_size=int(data.get("max_stack_size", 4)),
                beam_width=int(data.get("beam_width", 12)),
                top_k=int(data.get("top_k", 5)),
                min_evidence_confidence=str(data.get("min_evidence_confidence", "medium")),
                desired_context=data.get("desired_context") or {},
                candidate_limit=int(data.get("candidate_limit", 220)),
                output_mode=output_mode,
                include_distribution=include_distribution,
            )
        except (TypeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(payload, status=status.HTTP_200_OK)
