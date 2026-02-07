from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta, timezone as dt_timezone
from typing import Iterable, List, Optional

from dateutil.relativedelta import relativedelta
from django.db.utils import OperationalError
from django.utils import timezone

from logs.models import IntakeLog
from .models import StackItem


@dataclass(frozen=True)
class StackOccurrence:
    stack_id: int
    stack_name: str
    stack_item_id: int
    compound_id: int
    compound_name: str
    compound_slug: str
    scheduled_for: datetime
    dosage_amount: Optional[str]
    dosage_unit: str
    time_of_day: Optional[str]
    is_taken: bool = False


def add_recurrence(dt: datetime, interval: int, unit: str) -> datetime:
    """
    Add a calendar recurrence while preserving "wall-clock" time where possible.

    We prefer calendar deltas over fixed timedeltas to behave better across DST
    transitions (e.g. "every day at 9am local time").
    """
    if unit == 'daily':
        return dt + relativedelta(days=interval)
    if unit == 'weekly':
        return dt + relativedelta(weeks=interval)
    if unit == 'monthly':
        return dt + relativedelta(months=interval)
    raise ValueError(f"Unknown recurrence unit: {unit!r}")


def _default_local_time_for_time_of_day(time_of_day: Optional[str]) -> Optional[time]:
    if not time_of_day:
        return None
    # These defaults only apply when an item has no explicit intake_time yet.
    # They are intentionally conservative and can be overridden by editing the item.
    mapping = {
        'morning': time(hour=9, minute=0),
        'afternoon': time(hour=14, minute=0),
        'night': time(hour=20, minute=0),
        'pre-event': time(hour=12, minute=0),
    }
    return mapping.get(time_of_day)


def _infer_intake_time(item: StackItem, *, now: datetime) -> datetime:
    """
    Infer an initial intake_time for schedule display when the item has none.

    This enables "daily checking" of currently active stacks without requiring the
    user to set a first datetime for every item.
    """
    if item.intake_time:
        if timezone.is_naive(item.intake_time):
            return timezone.make_aware(item.intake_time, timezone.get_current_timezone())
        return item.intake_time

    tz = timezone.get_current_timezone()
    local_now = timezone.localtime(now, tz)
    local_t = _default_local_time_for_time_of_day(item.time_of_day) or local_now.timetz().replace(second=0, microsecond=0)
    local_dt = local_now.replace(hour=local_t.hour, minute=local_t.minute, second=0, microsecond=0)
    if timezone.is_naive(local_dt):
        local_dt = timezone.make_aware(local_dt, tz)
    return local_dt


def _advance_to_at_least(current: datetime, target: datetime, *, interval: int, unit: str) -> datetime:
    if current >= target:
        return current
    if interval < 1:
        raise ValueError("recurrence_interval must be >= 1")

    tz = timezone.get_current_timezone()
    current_local = timezone.localtime(current, tz)
    target_local = timezone.localtime(target, tz)

    if unit == 'daily':
        diff_days = (target_local.date() - current_local.date()).days
        jump = max(0, (diff_days // interval) * interval)
        if jump:
            current = current + relativedelta(days=jump)
        while current < target:
            current = add_recurrence(current, interval, unit)
        return current

    if unit == 'weekly':
        diff_days = (target_local.date() - current_local.date()).days
        diff_weeks = max(0, diff_days // 7)
        jump = max(0, (diff_weeks // interval) * interval)
        if jump:
            current = current + relativedelta(weeks=jump)
        while current < target:
            current = add_recurrence(current, interval, unit)
        return current

    if unit == 'monthly':
        months_diff = (target_local.year - current_local.year) * 12 + (target_local.month - current_local.month)
        jump = max(0, (months_diff // interval) * interval)
        if jump:
            current = current + relativedelta(months=jump)
        while current < target:
            current = add_recurrence(current, interval, unit)
        return current

    # Fallback: safe linear advance
    safety_counter = 0
    while current < target and safety_counter < 10_000:
        current = add_recurrence(current, interval, unit)
        safety_counter += 1
    return current


def get_schedule_window(*, now: datetime, period: str) -> tuple[datetime, datetime]:
    """
    Compute a local-calendar window for schedule views.

    Supported periods: 'day', 'week', 'month'.
    """
    local_now = timezone.localtime(now)
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == 'day':
        end = start + timedelta(days=1)
        return start, end

    if period == 'week':
        start = start - timedelta(days=start.weekday())
        end = start + timedelta(days=7)
        return start, end

    if period == 'month':
        start = start.replace(day=1)
        end = start + relativedelta(months=1)
        return start, end

    raise ValueError(f"Unknown schedule period: {period!r}")


def iter_upcoming_occurrences(
    items: Iterable[StackItem],
    *,
    now: Optional[datetime] = None,
    until: Optional[datetime] = None,
    window_start: Optional[datetime] = None,
    per_item_cap: int = 32,
) -> List[StackOccurrence]:
    now = now or timezone.now()
    until = until or (now + timedelta(days=7))
    window_start = window_start or now
    occurrences: List[StackOccurrence] = []

    for item in items:
        current = _infer_intake_time(item, now=now)
        current = _advance_to_at_least(
            current,
            window_start,
            interval=item.recurrence_interval,
            unit=item.recurrence_unit,
        )

        for _ in range(per_item_cap):
            if current > until:
                break

            occurrences.append(
                StackOccurrence(
                    stack_id=item.stack_id,
                    stack_name=item.stack.name,
                    stack_item_id=item.id,
                    compound_id=item.compound_id,
                    compound_name=item.compound.name,
                    compound_slug=getattr(item.compound, 'slug', ''),
                    scheduled_for=current,
                    dosage_amount=str(item.dosage_amount) if item.dosage_amount is not None else None,
                    dosage_unit=item.dosage_unit,
                    time_of_day=item.time_of_day,
                    is_taken=False,
                )
            )
            current = add_recurrence(current, item.recurrence_interval, item.recurrence_unit)

    occurrences.sort(key=lambda o: o.scheduled_for)
    return occurrences


def _coerce_aware_no_micro(dt: datetime) -> datetime:
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt.replace(microsecond=0)


def _normalize_key_dt(dt: datetime) -> datetime:
    return _coerce_aware_no_micro(dt).astimezone(dt_timezone.utc)


def annotate_occurrences_taken(
    occurrences: List[StackOccurrence],
    *,
    user,
    window_start: datetime,
    window_end: datetime,
) -> List[StackOccurrence]:
    if not occurrences:
        return occurrences

    stack_item_ids = {o.stack_item_id for o in occurrences}
    if not stack_item_ids:
        return occurrences

    window_start_n = _normalize_key_dt(window_start)
    window_end_n = _normalize_key_dt(window_end)

    qs = (
        IntakeLog.objects.filter(
            user=user,
            stack_item_id__in=stack_item_ids,
            scheduled_for__isnull=False,
        )
        .only('stack_item_id', 'scheduled_for')
    )

    # Inclusive start, exclusive end.
    qs = qs.filter(scheduled_for__gte=window_start_n, scheduled_for__lt=window_end_n)

    try:
        taken_rows = list(qs.values_list('stack_item_id', 'scheduled_for'))
    except OperationalError:
        # DB schema missing columns (e.g. migrations not applied yet). Fail open.
        return occurrences

    taken_keys = {(stack_item_id, _normalize_key_dt(scheduled_for)) for stack_item_id, scheduled_for in taken_rows}

    out: List[StackOccurrence] = []
    for o in occurrences:
        key = (o.stack_item_id, _normalize_key_dt(o.scheduled_for))
        out.append(replace(o, is_taken=(key in taken_keys)))
    return out


def merge_taken_logs_into_occurrences(
    occurrences: List[StackOccurrence],
    *,
    user,
    window_start: datetime,
    window_end: datetime,
) -> List[StackOccurrence]:
    """
    Ensure taken occurrences remain visible within the window even after the
    StackItem's next `intake_time` advances.
    """
    window_start_n = _normalize_key_dt(window_start)
    window_end_n = _normalize_key_dt(window_end)

    existing_by_key = {
        (o.stack_item_id, _normalize_key_dt(o.scheduled_for)): o
        for o in occurrences
    }

    qs = (
        IntakeLog.objects.filter(
            user=user,
            stack_item__isnull=False,
            scheduled_for__isnull=False,
            scheduled_for__gte=window_start_n,
            scheduled_for__lt=window_end_n,
        )
        .select_related('compound', 'stack_item__stack')
        .only(
            'stack_item_id',
            'scheduled_for',
            'compound_id',
            'compound__name',
            'compound__slug',
            'stack_item__stack_id',
            'stack_item__stack__name',
            'amount',
            'unit',
            'time_of_day',
        )
    )

    try:
        logs = list(qs)
    except OperationalError:
        return occurrences

    merged = dict(existing_by_key)
    for log in logs:
        if not log.stack_item_id or not log.scheduled_for:
            continue
        key = (log.stack_item_id, _normalize_key_dt(log.scheduled_for))
        existing = merged.get(key)
        if existing:
            merged[key] = replace(existing, is_taken=True)
            continue

        stack = getattr(log.stack_item, 'stack', None)
        merged[key] = StackOccurrence(
            stack_id=getattr(stack, 'id', log.stack_item.stack_id),
            stack_name=getattr(stack, 'name', ''),
            stack_item_id=log.stack_item_id,
            compound_id=log.compound_id,
            compound_name=getattr(log.compound, 'name', ''),
            compound_slug=getattr(log.compound, 'slug', ''),
            scheduled_for=_coerce_aware_no_micro(log.scheduled_for),
            dosage_amount=log.amount or None,
            dosage_unit=log.unit or '',
            time_of_day=log.time_of_day,
            is_taken=True,
        )

    out = list(merged.values())
    out.sort(key=lambda o: o.scheduled_for)
    return out


def untake_stack_item_occurrence(
    item: StackItem,
    *,
    user,
    scheduled_for: datetime,
) -> int:
    """
    Remove the intake log marking this specific occurrence as taken.

    Best-effort rollback: if the stack item was advanced exactly one recurrence
    from this scheduled occurrence (and no later logs exist), rewind intake_time
    back to `scheduled_for` so the occurrence stays visible/due.
    """
    if item.stack.user_id != user.id:
        raise PermissionError("Cannot untake a stack item you don't own.")

    scheduled_for = _coerce_aware_no_micro(scheduled_for)

    try:
        deleted_count, _ = IntakeLog.objects.filter(
            user=user,
            stack_item=item,
            scheduled_for=scheduled_for,
        ).delete()
    except OperationalError:
        return 0

    # Attempt to rewind the schedule if this was the latest taken occurrence.
    expected_next = add_recurrence(scheduled_for, item.recurrence_interval, item.recurrence_unit)

    item_intake_time = item.intake_time
    if item_intake_time:
        item_intake_time = _coerce_aware_no_micro(item_intake_time)

    if not item_intake_time:
        item.intake_time = scheduled_for
        item.save(update_fields=['intake_time'])
        return deleted_count

    if item_intake_time != _coerce_aware_no_micro(expected_next):
        return deleted_count

    try:
        has_later = IntakeLog.objects.filter(
            user=user,
            stack_item=item,
            scheduled_for__gt=scheduled_for,
            scheduled_for__isnull=False,
        ).exists()
    except OperationalError:
        has_later = True

    if not has_later:
        item.intake_time = scheduled_for
        item.save(update_fields=['intake_time'])

    return deleted_count


def take_stack_item(
    item: StackItem,
    *,
    user,
    taken_at: Optional[datetime] = None,
    scheduled_for: Optional[datetime] = None,
    notes: str = "",
) -> IntakeLog:
    if item.stack.user_id != user.id:
        raise PermissionError("Cannot take a stack item you don't own.")

    taken_at = taken_at or timezone.now()
    if timezone.is_naive(taken_at):
        taken_at = timezone.make_aware(taken_at, timezone.get_current_timezone())

    if scheduled_for:
        if timezone.is_naive(scheduled_for):
            scheduled_for = timezone.make_aware(scheduled_for, timezone.get_current_timezone())
    elif item.intake_time:
        # If the item has a scheduled time, prefer advancing from that to reduce drift.
        item_intake_time = item.intake_time
        if timezone.is_naive(item_intake_time):
            item_intake_time = timezone.make_aware(item_intake_time, timezone.get_current_timezone())
        candidate_next = add_recurrence(item_intake_time, item.recurrence_interval, item.recurrence_unit)
        scheduled_for = item_intake_time if candidate_next > taken_at else taken_at
    else:
        scheduled_for = taken_at
    scheduled_for = _coerce_aware_no_micro(scheduled_for)

    intake_log = IntakeLog.objects.create(
        user=user,
        compound=item.compound,
        stack_item=item,
        scheduled_for=scheduled_for,
        amount=str(item.dosage_amount) if item.dosage_amount is not None else "",
        unit=item.dosage_unit,
        time_of_day=item.time_of_day,
        taken_at=taken_at,
        notes=notes or f"Taken from stack: {item.stack.name}",
    )

    item.intake_time = add_recurrence(scheduled_for, item.recurrence_interval, item.recurrence_unit)
    item.completed = False
    item.save(update_fields=['intake_time', 'completed'])

    return intake_log
