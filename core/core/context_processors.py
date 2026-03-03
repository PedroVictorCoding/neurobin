from __future__ import annotations

from django.utils import timezone

GOAL_SKINS = {
    'general':     {'key': 'general',     'label': 'General',     'description': 'Overall wellbeing & exploration', 'accent_primary': '#b86bff', 'accent_hover': '#d0a2ff', 'rgb': '184, 107, 255', 'icon': 'fa-flask'},
    'anabolic':    {'key': 'anabolic',    'label': 'Anabolic',    'description': 'Muscle growth & strength',        'accent_primary': '#ff3366', 'accent_hover': '#ff6688', 'rgb': '255, 51, 102',  'icon': 'fa-dumbbell'},
    'longevity':   {'key': 'longevity',   'label': 'Longevity',   'description': 'Anti-aging & healthspan',         'accent_primary': '#00ff88', 'accent_hover': '#33ffaa', 'rgb': '0, 255, 136',   'icon': 'fa-leaf'},
    'cognition':   {'key': 'cognition',   'label': 'Cognition',   'description': 'Brain & cognitive enhancement',   'accent_primary': '#00d4ff', 'accent_hover': '#33ddff', 'rgb': '0, 212, 255',   'icon': 'fa-brain'},
    'performance': {'key': 'performance', 'label': 'Performance', 'description': 'Athletic output & energy',        'accent_primary': '#ff8c00', 'accent_hover': '#ffaa33', 'rgb': '255, 140, 0',   'icon': 'fa-bolt'},
    'recovery':    {'key': 'recovery',    'label': 'Recovery',    'description': 'Rest, repair & regeneration',     'accent_primary': '#00d4aa', 'accent_hover': '#33ddbb', 'rgb': '0, 212, 170',   'icon': 'fa-heart-pulse'},
    'sleep':       {'key': 'sleep',       'label': 'Sleep',       'description': 'Sleep quality & circadian',       'accent_primary': '#7c6fef', 'accent_hover': '#9d92f2', 'rgb': '124, 111, 239', 'icon': 'fa-moon'},
    'fat-loss':    {'key': 'fat-loss',    'label': 'Fat Loss',    'description': 'Body composition & metabolism',   'accent_primary': '#f5a623', 'accent_hover': '#f7be5a', 'rgb': '245, 166, 35',  'icon': 'fa-fire'},
}


def experience_context(request):
    """Global trust/conversion context for non-API templates."""
    path = request.path or ""
    if path.startswith("/api/"):
        return {}

    context = {
        "trust_microcopy": {
            "disclaimer": "Research-only outputs with visible confidence levels and uncertainty.",
            "integrity": "Use source-linked evidence and versioned changes for auditability.",
        }
    }

    # Resolve goal skin for all visitors (authenticated → their saved choice; others → default purple)
    skin_key = 'general'
    if request.user.is_authenticated and hasattr(request.user, 'profile'):
        skin_key = request.user.profile.goal_skin or 'general'
    context['user_skin'] = GOAL_SKINS.get(skin_key, GOAL_SKINS['general'])
    context['goal_skins'] = list(GOAL_SKINS.values())

    if request.user.is_authenticated:
        from stacks.models import Stack

        active_stack_count = Stack.objects.filter(user=request.user, is_active=True).count()
        total_stack_count = Stack.objects.filter(user=request.user).count()
        recent_stacks = request.session.get("recent_stacks", [])
        resume_stack = recent_stacks[0] if recent_stacks else None

        context["return_prompt"] = {
            "headline": "Welcome back. Continue your evidence workflow.",
            "detail": (
                f"{active_stack_count} active stack(s), {total_stack_count} total."
                if total_stack_count
                else "Start your first stack to build a repeatable research routine."
            ),
            "resume_stack": resume_stack,
        }
    else:
        context["conversion_prompt"] = {
            "headline": "Explore first. Create an account only when you want to save progress.",
            "detail": "Save stacks, risk snapshots, and review history across sessions.",
        }

    context["trust_context_generated_at"] = timezone.now()
    return context
