from __future__ import annotations

from django.utils import timezone


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
