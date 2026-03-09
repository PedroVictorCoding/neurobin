from collections import defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone


def _get_session_recent_list(request, key, limit=6):
    rows = request.session.get(key, [])
    if not isinstance(rows, list):
        return []
    return rows[:limit]


def _build_home_week_intake_context(request):
    from stacks.models import StackItem
    from stacks.services import (
        annotate_occurrences_taken,
        get_schedule_window,
        iter_upcoming_occurrences,
        merge_taken_logs_into_occurrences,
    )

    now = timezone.now()
    tz = timezone.get_current_timezone()
    window_start, window_end = get_schedule_window(now=now, period="week")
    local_week_start = timezone.localtime(window_start, tz).date()
    local_today = timezone.localtime(now, tz).date()

    occurrences = []
    if request.user.is_authenticated:
        items = (
            StackItem.objects.filter(stack__user=request.user, stack__is_active=True)
            .select_related("stack", "compound")
        )
        occurrences = iter_upcoming_occurrences(
            items,
            now=now,
            until=window_end,
            window_start=window_start,
        )
        occurrences = annotate_occurrences_taken(
            occurrences,
            user=request.user,
            window_start=window_start,
            window_end=window_end,
        )
        occurrences = merge_taken_logs_into_occurrences(
            occurrences,
            user=request.user,
            window_start=window_start,
            window_end=window_end,
        )

    by_day = defaultdict(list)
    for occurrence in occurrences:
        day_key = timezone.localtime(occurrence.scheduled_for, tz).date()
        by_day[day_key].append(occurrence)

    days = []
    has_items = False
    for offset in range(7):
        current_day = local_week_start + timedelta(days=offset)
        day_occurrences = by_day.get(current_day, [])
        count = len(day_occurrences)
        taken_count = sum(1 for occurrence in day_occurrences if occurrence.is_taken)
        has_items = has_items or bool(count)
        days.append(
            {
                "date": current_day,
                "count": count,
                "taken_count": taken_count,
                "percent_taken": int(round((taken_count / count) * 100)) if count else 0,
                "items": day_occurrences,
                "extra_count": 0,
                "is_today": current_day == local_today,
            }
        )

    return {
        "title": f"Week of {local_week_start.strftime('%b %d, %Y')}",
        "days": days,
        "has_items": has_items,
        "is_preview": not request.user.is_authenticated,
    }


def _parse_scheduled_for_value(raw_value):
    scheduled_for_raw = (raw_value or "").strip()
    if not scheduled_for_raw:
        return None

    try:
        scheduled_for_str = scheduled_for_raw.replace("Z", "+00:00")
        scheduled_for = datetime.fromisoformat(scheduled_for_str)
        if timezone.is_naive(scheduled_for):
            scheduled_for = timezone.make_aware(scheduled_for, timezone.get_current_timezone())
        return scheduled_for
    except ValueError:
        return None


def home(request):
    from compounds.models import Compound, CompoundTargetInteraction, Target
    from django.db.models import Count, Prefetch
    from research.models import ResearchSnippet
    from stacks.models import Stack, StackItem
    from stacks.services import take_stack_item, untake_stack_item_occurrence

    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

    if request.method == "POST" and request.user.is_authenticated:
        scheduled_for = _parse_scheduled_for_value(request.POST.get("scheduled_for"))
        item_id = request.POST.get("stack_item_id")
        item = (
            StackItem.objects.filter(id=item_id, stack__user=request.user)
            .select_related("stack", "compound")
            .first()
        )
        is_taken = None
        if item and scheduled_for:
            if "take_stack_item" in request.POST:
                take_stack_item(
                    item,
                    user=request.user,
                    taken_at=timezone.now(),
                    scheduled_for=scheduled_for,
                )
                is_taken = True
            elif "untake_stack_item" in request.POST:
                untake_stack_item_occurrence(
                    item,
                    user=request.user,
                    scheduled_for=scheduled_for,
                )
                is_taken = False

        if is_ajax:
            if is_taken is None:
                return JsonResponse({"ok": False, "error": "invalid-request"}, status=400)
            return JsonResponse({"ok": True, "is_taken": is_taken})

        return redirect("home")

    compound_count = Compound.objects.count()
    mechanism_count = CompoundTargetInteraction.objects.count()
    target_count = Target.objects.count()
    public_stack_count = Stack.objects.filter(visibility="public").count()
    public_snippet_count = ResearchSnippet.objects.filter(visibility="public").count()
    verified_snippet_count = ResearchSnippet.objects.filter(status="verified").count()

    recent_compound_entries = _get_session_recent_list(request, "recent_compounds", limit=6)
    recent_compound_slugs = [row.get("slug") for row in recent_compound_entries if row.get("slug")]
    compound_map = {
        row.slug: row
        for row in Compound.objects.filter(slug__in=recent_compound_slugs).only("slug", "name")
    }
    recent_compounds = []
    for row in recent_compound_entries:
        slug = row.get("slug")
        compound = compound_map.get(slug)
        if not slug or not compound:
            continue
        recent_compounds.append({"slug": slug, "name": compound.name})

    recent_snippet_entries = _get_session_recent_list(request, "recent_snippets", limit=6)
    recent_snippet_ids = [row.get("id") for row in recent_snippet_entries if row.get("id")]
    snippet_map = {
        row.id: row
        for row in ResearchSnippet.objects.filter(id__in=recent_snippet_ids).select_related("compound").only(
            "id",
            "title",
            "compound__slug",
            "compound__name",
        )
    }
    recent_snippets = []
    for row in recent_snippet_entries:
        snippet_id = row.get("id")
        snippet = snippet_map.get(snippet_id)
        if not snippet:
            continue
        recent_snippets.append(
            {
                "id": snippet.id,
                "title": snippet.title,
                "compound_slug": snippet.compound.slug,
                "compound_name": snippet.compound.name,
            }
        )

    recent_stacks = []
    if request.user.is_authenticated:
        recent_stack_entries = _get_session_recent_list(request, "recent_stacks", limit=6)
        recent_stack_ids = [row.get("id") for row in recent_stack_entries if row.get("id")]
        stack_map = {
            row.id: row
            for row in Stack.objects.filter(user=request.user, id__in=recent_stack_ids).only(
                "id",
                "name",
                "is_active",
            )
        }
        for row in recent_stack_entries:
            stack_id = row.get("id")
            stack = stack_map.get(stack_id)
            if not stack:
                continue
            recent_stacks.append(
                {
                    "id": stack.id,
                    "name": stack.name,
                    "is_active": stack.is_active,
                }
            )

    trending_stacks = list(
        Stack.objects
        .filter(visibility="public")
        .annotate(usage_count=Count("copies"))
        .select_related("user", "risk_assessment")
        .prefetch_related(Prefetch("items", queryset=StackItem.objects.select_related("compound").order_by("order")))
        .order_by("-usage_count", "-created")[:6]
    )

    featured_snippets = list(
        ResearchSnippet.objects
        .filter(status="verified")
        .select_related("compound", "created_by")
        .order_by("-view_count", "-created")[:6]
    )

    context = {
        "compound_count": compound_count,
        "mechanism_count": mechanism_count,
        "target_count": target_count,
        "public_stack_count": public_stack_count,
        "public_snippet_count": public_snippet_count,
        "verified_snippet_count": verified_snippet_count,
        "recent_compounds": recent_compounds,
        "recent_snippets": recent_snippets,
        "recent_stacks": recent_stacks,
        "week_intake": _build_home_week_intake_context(request),
        "trending_stacks": trending_stacks,
        "featured_snippets": featured_snippets,
    }

    return render(request, "home.html", context)

def effect_curves_demo(request):
    return render(request, "demo/effect_curves_demo.html")

def credits(request):
    return render(request, "core/credits.html")


def about(request):
    return render(request, "core/about.html")


def _normalized_ua_tokens(values):
    seen = set()
    out = []
    for raw in values:
        token = str(raw).strip()
        if not token:
            continue
        token_lower = token.lower()
        if token_lower in seen:
            continue
        seen.add(token_lower)
        out.append(token)
    return out


def _robots_disallowed_user_agents():
    blocked = _normalized_ua_tokens(getattr(settings, "BOT_BLOCKLIST_UA_SUBSTRINGS", ()))
    allowlisted = {
        token.lower()
        for token in _normalized_ua_tokens(getattr(settings, "BOT_ALLOWLIST_UA_SUBSTRINGS", ()))
    }
    return [token for token in blocked if token.lower() not in allowlisted]


def robots_txt(request):
    lines = []
    for user_agent in _robots_disallowed_user_agents():
        lines.append(f"User-agent: {user_agent}")
        lines.append("Disallow: /")
        lines.append("")

    lines.append("User-agent: *")
    if getattr(settings, "ROBOTS_ALLOW_ALL_AGENTS", True):
        lines.append("Allow: /")
    else:
        lines.append("Disallow: /")

    body = "\n".join(lines).rstrip() + "\n"
    return HttpResponse(body, content_type="text/plain")
