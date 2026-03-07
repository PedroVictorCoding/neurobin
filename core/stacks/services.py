from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from typing import Dict, Iterable, List, Optional

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
    Add recurrence using frequency semantics:
    - daily:   interval = times per day
    - weekly:  interval = times per week
    - monthly: interval = times per month

    Examples:
    - 1 daily   -> +1 day
    - 4 weekly  -> +7/4 days (4x/week)
    - 2 monthly -> halfway to same date next month (2x/month)
    """
    if interval < 1:
        raise ValueError("recurrence_interval must be >= 1")

    if unit == 'daily':
        return dt + timedelta(days=(1 / interval))
    if unit == 'weekly':
        return dt + timedelta(days=(7 / interval))
    if unit == 'monthly':
        # Keep month-aware cadence by splitting the current month-span.
        next_month_same_clock = dt + relativedelta(months=1)
        span = next_month_same_clock - dt
        return dt + (span / interval)
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

    if unit in {'daily', 'weekly'}:
        step = add_recurrence(current, interval, unit) - current
        step_seconds = step.total_seconds()
        if step_seconds > 0:
            diff_seconds = (target - current).total_seconds()
            jump_count = int(max(0, diff_seconds // step_seconds))
            if jump_count > 0:
                current = current + (step * jump_count)

    safety_counter = 0
    while current < target and safety_counter < 20_000:
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


def _is_in_cycle_on_phase(dt: datetime, item: StackItem) -> bool:
    """Return True if `dt` falls within the 'on' phase of the item's drug holiday cycle."""
    on = getattr(item, 'cycle_on_days', None)
    off = getattr(item, 'cycle_off_days', None)
    if not on or not off:
        return True  # cycling not configured
    cycle_length = on + off
    ref: Optional[date] = getattr(item, 'cycle_reference_date', None)
    if ref is None:
        ref = timezone.localtime(item.added).date() if item.added else timezone.localtime(dt).date()
    local_date = timezone.localtime(dt).date()
    days_since_ref = (local_date - ref).days
    if days_since_ref < 0:
        return True  # before cycle started, treat as on
    phase = days_since_ref % cycle_length
    return phase < on


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

        doses_per = max(1, getattr(item, 'doses_per_recurrence', 1) or 1)

        emitted = 0
        safety = 0
        while emitted < per_item_cap and safety < per_item_cap * 4:
            safety += 1
            if current > until:
                break

            if not _is_in_cycle_on_phase(current, item):
                current = add_recurrence(current, item.recurrence_interval, item.recurrence_unit)
                continue

            # Compute the gap to the next recurrence so we can space sub-doses evenly.
            next_period = add_recurrence(current, item.recurrence_interval, item.recurrence_unit)
            period_seconds = (next_period - current).total_seconds()
            dose_gap = timedelta(seconds=period_seconds / doses_per)

            for dose_idx in range(doses_per):
                dose_time = current + (dose_gap * dose_idx)
                if dose_time > until:
                    break
                if dose_time < window_start:
                    continue
                occurrences.append(
                    StackOccurrence(
                        stack_id=item.stack_id,
                        stack_name=item.stack.name,
                        stack_item_id=item.id,
                        compound_id=item.compound_id,
                        compound_name=item.compound.name,
                        compound_slug=getattr(item.compound, 'slug', ''),
                        scheduled_for=dose_time,
                        dosage_amount=str(item.dosage_amount) if item.dosage_amount is not None else None,
                        dosage_unit=item.dosage_unit,
                        time_of_day=item.time_of_day,
                        is_taken=False,
                    )
                )
                emitted += 1

            current = next_period

    occurrences.sort(key=lambda o: o.scheduled_for)
    return occurrences


# ---------------------------------------------------------------------------
# Adherence helpers
# ---------------------------------------------------------------------------

def compute_adherence_stats(
    occurrences: List[StackOccurrence],
    *,
    user,
    now: Optional[datetime] = None,
) -> dict:
    """
    Returns a dict with today's adherence and consecutive-day streak.

    Keys:
        taken_today      int
        scheduled_today  int
        today_pct        int | None
        streak_days      int  (consecutive calendar days with ≥1 intake logged)
    """
    now = now or timezone.now()
    stack_occs = [o for o in occurrences if not getattr(o, 'is_unstacked', False)]
    taken_today = sum(1 for o in stack_occs if o.is_taken)
    scheduled_today = len(stack_occs)
    today_pct: Optional[int] = None
    if scheduled_today > 0:
        today_pct = int(round(taken_today / scheduled_today * 100))

    # Streak: how many consecutive calendar days going backwards from yesterday
    # where at least one stack-linked intake was logged.
    streak_days = 0
    check_date = timezone.localtime(now).date() - timedelta(days=1)
    try:
        for _ in range(60):
            has_log = IntakeLog.objects.filter(
                user=user,
                stack_item__isnull=False,
                taken_at__date=check_date,
            ).exists()
            if has_log:
                streak_days += 1
                check_date -= timedelta(days=1)
            else:
                break
    except OperationalError:
        pass

    return {
        'taken_today': taken_today,
        'scheduled_today': scheduled_today,
        'today_pct': today_pct,
        'streak_days': streak_days,
    }


# ---------------------------------------------------------------------------
# Effect-window timeline data
# ---------------------------------------------------------------------------

def build_timeline_data(
    occurrences: List[StackOccurrence],
    *,
    now: Optional[datetime] = None,
) -> List[dict]:
    """
    For each occurrence that has EffectWindow data, return a chart row dict.

    Each row:
        compound_name   str
        compound_id     int
        intake_min      int   minutes from midnight of the current day
        onset_end_min   int
        peak_start_min  int
        peak_end_min    int
        duration_end_min int
        has_window      bool
    """
    from compounds.models import EffectWindow

    now = now or timezone.now()
    tz = timezone.get_current_timezone()

    # Collect unique compound IDs from scheduled (non-unstacked) occurrences.
    compound_ids = {
        o.compound_id for o in occurrences
        if not getattr(o, 'is_unstacked', False)
    }
    if not compound_ids:
        return []

    ew_map: Dict[int, EffectWindow] = {}
    for ew in EffectWindow.objects.filter(compound_id__in=compound_ids).order_by('id'):
        if ew.compound_id not in ew_map:
            ew_map[ew.compound_id] = ew

    rows = []
    seen_key: set = set()  # deduplicate by (compound_id, intake_min)
    for o in occurrences:
        if getattr(o, 'is_unstacked', False):
            continue
        local_time = timezone.localtime(o.scheduled_for, tz)
        intake_min = local_time.hour * 60 + local_time.minute
        key = (o.compound_id, intake_min)
        if key in seen_key:
            continue
        seen_key.add(key)
        ew = ew_map.get(o.compound_id)
        if ew:
            rows.append({
                'compound_name': o.compound_name,
                'compound_id': o.compound_id,
                'intake_min': intake_min,
                'onset_end_min': intake_min + ew.onset_minutes,
                'peak_start_min': intake_min + ew.peak_min_minutes,
                'peak_end_min': intake_min + ew.peak_max_minutes,
                'duration_end_min': intake_min + ew.duration_minutes,
                'has_window': True,
            })
        else:
            rows.append({
                'compound_name': o.compound_name,
                'compound_id': o.compound_id,
                'intake_min': intake_min,
                'has_window': False,
            })

    rows.sort(key=lambda r: r['intake_min'])
    return rows


# ---------------------------------------------------------------------------
# Conflict detection (effect-window overlap × CYP interaction)
# ---------------------------------------------------------------------------

def detect_timing_conflicts(
    occurrences: List[StackOccurrence],
    *,
    now: Optional[datetime] = None,
) -> List[dict]:
    """
    Return a list of conflict dicts when two compounds' effect windows overlap
    AND they have a known CYP inhibitor↔substrate relationship.

    Each dict:
        compound_a_name     str
        compound_b_name     str
        overlap_minutes     int
        cyp_target          str
        mechanism_a         str   (e.g. 'inhibitor')
        mechanism_b         str   (e.g. 'substrate')
    """
    from compounds.models import CompoundTargetInteraction, EffectWindow

    stack_occs = [o for o in occurrences if not getattr(o, 'is_unstacked', False)]
    if len(stack_occs) < 2:
        return []

    compound_ids = {o.compound_id for o in stack_occs}
    ew_map: Dict[int, EffectWindow] = {}
    for ew in EffectWindow.objects.filter(compound_id__in=compound_ids).order_by('id'):
        if ew.compound_id not in ew_map:
            ew_map[ew.compound_id] = ew

    # Build CYP interaction map: compound_id -> {cyp_target_name: mechanism}
    cyp_rows = (
        CompoundTargetInteraction.objects
        .filter(compound_id__in=compound_ids, target__name__icontains='CYP')
        .select_related('target')
        .values('compound_id', 'target__name', 'mechanism')
    )
    cyp_map: Dict[int, Dict[str, str]] = {}
    for row in cyp_rows:
        cid = row['compound_id']
        cyp_map.setdefault(cid, {})
        # If multiple rows for same CYP, prefer inhibitor/inducer over substrate.
        existing = cyp_map[cid].get(row['target__name'])
        if existing is None or row['mechanism'] in ('inhibitor', 'inducer'):
            cyp_map[cid][row['target__name']] = row['mechanism']

    conflicts: List[dict] = []
    seen_pairs: set = set()

    for i, occ_a in enumerate(stack_occs):
        ew_a = ew_map.get(occ_a.compound_id)
        if not ew_a:
            continue
        a_start = occ_a.scheduled_for
        a_end = a_start + timedelta(minutes=ew_a.duration_minutes)

        for occ_b in stack_occs[i + 1:]:
            if occ_a.compound_id == occ_b.compound_id:
                continue
            pair_key = tuple(sorted([occ_a.compound_id, occ_b.compound_id]))
            if pair_key in seen_pairs:
                continue
            ew_b = ew_map.get(occ_b.compound_id)
            if not ew_b:
                continue
            b_start = occ_b.scheduled_for
            b_end = b_start + timedelta(minutes=ew_b.duration_minutes)

            overlap_start = max(a_start, b_start)
            overlap_end = min(a_end, b_end)
            if overlap_end <= overlap_start:
                continue
            overlap_minutes = int((overlap_end - overlap_start).total_seconds() / 60)

            # Check for shared CYP target with opposing roles.
            cyp_a = cyp_map.get(occ_a.compound_id, {})
            cyp_b = cyp_map.get(occ_b.compound_id, {})
            for cyp_name, mech_a in cyp_a.items():
                mech_b = cyp_b.get(cyp_name)
                if mech_b is None:
                    continue
                roles = {mech_a, mech_b}
                # Only flag inhibitor/inducer ↔ substrate pairs.
                if roles & {'inhibitor', 'inducer'} and 'substrate' in roles:
                    seen_pairs.add(pair_key)
                    conflicts.append({
                        'compound_a_name': occ_a.compound_name,
                        'compound_b_name': occ_b.compound_name,
                        'overlap_minutes': overlap_minutes,
                        'cyp_target': cyp_name,
                        'mechanism_a': mech_a,
                        'mechanism_b': mech_b,
                    })
                    break

    return conflicts


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
