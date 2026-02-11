from django.http import HttpResponse
from django.shortcuts import render


def _get_session_recent_list(request, key, limit=6):
    rows = request.session.get(key, [])
    if not isinstance(rows, list):
        return []
    return rows[:limit]


def home(request):
    from compounds.models import Compound, CompoundTargetInteraction, Target
    from research.models import ResearchSnippet
    from stacks.models import Stack

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
    }

    return render(request, "home.html", context)

def effect_curves_demo(request):
    return render(request, "demo/effect_curves_demo.html")

def credits(request):
    return render(request, "core/credits.html")


def about(request):
    return render(request, "core/about.html")


def robots_txt(request):
    # Explicitly disallow crawling/scraping for all user agents.
    body = "User-agent: *\nDisallow: /\n"
    response = HttpResponse(body, content_type="text/plain")
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response
