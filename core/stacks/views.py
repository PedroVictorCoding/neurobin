from html import escape

from django.contrib.auth.mixins import LoginRequiredMixin

from django.views.generic import TemplateView
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from collections import defaultdict
from datetime import date, datetime, timedelta
from django.db.models import Count
from dateutil.relativedelta import relativedelta
import hashlib
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
from .models import Stack
from django.views.decorators.http import require_POST

from .forms import StackForm
from .forms_add_compound import AddCompoundForm
from .models import StackItem
from .metrics import compute_enzymatic_overload
from .models import StackRiskAssessment
from .models import StackTrait
from logs.models import IntakeLog
import json
from .services import (
    annotate_occurrences_taken,
    build_timeline_data,
    compute_adherence_stats,
    detect_timing_conflicts,
    get_schedule_window,
    iter_upcoming_occurrences,
    merge_taken_logs_into_occurrences,
    take_stack_item,
    untake_stack_item_occurrence,
)
from .trait_engine import (
    DEFAULT_TRAITS,
    analyze_stack_character_sheet,
    grouping_preset_options,
    parse_focus_groups,
    recommend_stack_builds,
)
from .risk import get_or_compute_stack_risk


def _build_stack_embed_description(stack, items) -> str:
    if not items:
        return f"{stack.name} by {stack.user.username}. No compounds listed yet."

    parts = []
    for item in items[:6]:
        dose = ""
        if item.dosage_amount:
            dose = f" {item.dosage_amount}{item.dosage_unit}"
        cadence = f" / {item.recurrence_rate_label}"
        parts.append(f"{item.compound.name}{dose}{cadence}")
    compounds_part = " • ".join(parts)
    extra = "" if len(items) <= 6 else f" • +{len(items) - 6} more"
    return f"{stack.name} ({len(items)} compounds) by {stack.user.username}: {compounds_part}{extra}"


def _truncate_stack_share_text(value: str, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3].rstrip()}..."


def _build_stack_share_image_svg(stack: Stack, items) -> str:
    width = 1200
    height = 630
    preview_items = list(items[:7])

    title = escape(_truncate_stack_share_text(stack.name, 42))
    subtitle = escape(f"By {stack.user.username} | {len(items)} compounds")
    visibility = escape(stack.get_visibility_display())

    row_markup = []
    row_start_y = 220
    row_height = 54

    if preview_items:
        for index, item in enumerate(preview_items):
            y = row_start_y + (index * row_height)
            compound_name = escape(_truncate_stack_share_text(item.compound.name, 34))

            detail_parts = []
            if item.dosage_amount:
                detail_parts.append(f"{item.dosage_amount} {item.dosage_unit}")
            detail_parts.append(item.recurrence_rate_label)
            if item.time_of_day:
                detail_parts.append(item.get_time_of_day_display())
            detail_text = escape(" | ".join(detail_parts))

            row_markup.append(
                f"""
    <rect x="84" y="{y - 28}" width="1032" height="42" rx="12" fill="rgba(255,255,255,0.04)" />
    <circle cx="112" cy="{y - 7}" r="6" fill="#22d3ee" />
    <text x="132" y="{y}" fill="#f8fafc" font-size="24" font-weight="700">{compound_name}</text>
    <text x="760" y="{y}" fill="#cbd5e1" font-size="18" text-anchor="end">{detail_text}</text>
"""
            )
    else:
        row_markup.append(
            """
    <rect x="84" y="192" width="1032" height="68" rx="18" fill="rgba(255,255,255,0.04)" />
    <text x="110" y="235" fill="#cbd5e1" font-size="24">No compounds in this stack yet.</text>
"""
        )

    extra_markup = ""
    if len(items) > len(preview_items):
        extra_count = len(items) - len(preview_items)
        extra_markup = (
            f'<text x="84" y="600" fill="#93c5fd" font-size="20">+{extra_count} more compound'
            f'{"s" if extra_count != 1 else ""}</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">{title}</title>
  <desc id="desc">{subtitle}</desc>
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0b1020" />
      <stop offset="100%" stop-color="#101a30" />
    </linearGradient>
    <linearGradient id="panel" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#16243f" />
      <stop offset="100%" stop-color="#0f172a" />
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#bg)" />
  <rect x="42" y="42" width="1116" height="546" rx="28" fill="url(#panel)" stroke="rgba(255,255,255,0.08)" />
  <text x="84" y="118" fill="#7dd3fc" font-size="18" font-weight="700" letter-spacing="1.5">NEUROBIN STACK</text>
  <text x="84" y="164" fill="#f8fafc" font-size="42" font-weight="800">{title}</text>
  <text x="84" y="194" fill="#cbd5e1" font-size="22">{subtitle}</text>
  <rect x="944" y="92" width="172" height="36" rx="18" fill="rgba(34,211,238,0.12)" stroke="rgba(34,211,238,0.35)" />
  <text x="1030" y="116" fill="#dbeafe" font-size="18" font-weight="700" text-anchor="middle">{visibility}</text>
  {''.join(row_markup)}
  {extra_markup}
  <text x="84" y="564" fill="#94a3b8" font-size="18">Share link copied with preview image from Neurobin</text>
</svg>"""


def _get_shareable_stack_or_404(request, stack_id: int) -> Stack:
    stack = (
        Stack.objects.filter(id=stack_id)
        .select_related('user')
        .prefetch_related('items__compound')
        .first()
    )
    if not stack:
        stack = get_object_or_404(Stack, id=stack_id)
    if stack.visibility == 'private':
        if not request.user.is_authenticated or request.user.id != stack.user_id:
            raise Http404("Stack not found.")
    return stack


def stack_share_image(request, stack_id: int):
    stack = _get_shareable_stack_or_404(request, stack_id)
    items = list(stack.items.all().select_related('compound').order_by('order', 'added'))
    svg = _build_stack_share_image_svg(stack, items)
    response = HttpResponse(svg, content_type='image/svg+xml')
    response['Cache-Control'] = 'private, max-age=300'
    return response


def _safe_get_risk_assessment(stack: Stack):
    try:
        return stack.risk_assessment
    except StackRiskAssessment.DoesNotExist:
        return None


def _append_query_params(url: str, params: dict) -> str:
    parsed = urlparse(url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing.update({k: v for k, v in params.items() if v is not None})
    new_query = urlencode(existing)
    return urlunparse(parsed._replace(query=new_query))


def _push_recent_stack(request, stack: Stack):
    recent = request.session.get('recent_stacks', [])
    if not isinstance(recent, list):
        recent = []
    recent = [row for row in recent if row.get('id') != stack.id]
    recent.insert(0, {'id': stack.id, 'name': stack.name})
    request.session['recent_stacks'] = recent[:8]


@login_required
@require_POST
def stack_risk_refresh(request, stack_id: int):
    stack = (
        Stack.objects.filter(id=stack_id, user=request.user)
        .prefetch_related('items__compound')
        .first()
    )
    if not stack:
        return redirect('my_stacks')

    next_url = request.POST.get('next') or reverse('stack_detail', kwargs={'stack_id': stack.id})
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse('stack_detail', kwargs={'stack_id': stack.id})

    from compounds.models import CompoundADMETPrediction, CompoundMolPropPrediction
    from compounds.admet_ai import is_admet_ai_available, get_admet_ai_version, predict_admet
    from compounds.molprop import is_molprop_available, get_molprop_version, predict_molprop

    admet_available = is_admet_ai_available()
    molprop_available = is_molprop_available()
    if not admet_available and not molprop_available:
        return redirect(_append_query_params(next_url, {'risk': 'unavailable'}))

    items = list(stack.items.all().select_related('compound'))
    compounds = {i.compound_id: i.compound for i in items}

    admet_preds = CompoundADMETPrediction.objects.filter(compound_id__in=list(compounds.keys()))
    admet_map = {p.compound_id: p for p in admet_preds}
    molprop_preds = CompoundMolPropPrediction.objects.filter(compound_id__in=list(compounds.keys()))
    molprop_map = {p.compound_id: p for p in molprop_preds}

    admet_computed = 0
    molprop_computed = 0
    skipped = 0
    for compound_id, compound in compounds.items():
        smiles = (compound.smiles or '').strip()
        if not smiles:
            skipped += 1
            continue
        smiles_hash = hashlib.sha256(smiles.encode('utf-8')).hexdigest()
        if admet_available:
            existing_admet = admet_map.get(compound_id)
            admet_fresh = bool(
                existing_admet
                and existing_admet.smiles_sha256 == smiles_hash
                and isinstance(existing_admet.predictions, dict)
                and existing_admet.predictions
                and not (existing_admet.error or '').strip()
            )
            if not admet_fresh:
                try:
                    predictions = predict_admet(smiles)
                    CompoundADMETPrediction.objects.update_or_create(
                        compound_id=compound_id,
                        defaults={
                            'smiles': smiles,
                            'smiles_sha256': smiles_hash,
                            'model_version': get_admet_ai_version(),
                            'predictions': predictions,
                            'error': '',
                        },
                    )
                except Exception as exc:
                    CompoundADMETPrediction.objects.update_or_create(
                        compound_id=compound_id,
                        defaults={
                            'smiles': smiles,
                            'smiles_sha256': smiles_hash,
                            'model_version': get_admet_ai_version(),
                            'predictions': {},
                            'error': str(exc),
                        },
                    )
                admet_computed += 1

        if molprop_available:
            existing_molprop = molprop_map.get(compound_id)
            molprop_fresh = bool(
                existing_molprop
                and existing_molprop.smiles_sha256 == smiles_hash
                and isinstance(existing_molprop.predictions, dict)
                and existing_molprop.predictions
                and not (existing_molprop.error or '').strip()
            )
            if not molprop_fresh:
                try:
                    predictions, uncertainty = predict_molprop(smiles)
                    CompoundMolPropPrediction.objects.update_or_create(
                        compound_id=compound_id,
                        defaults={
                            'smiles': smiles,
                            'smiles_sha256': smiles_hash,
                            'model_version': get_molprop_version(),
                            'predictions': predictions,
                            'uncertainty': uncertainty,
                            'error': '',
                        },
                    )
                except Exception as exc:
                    CompoundMolPropPrediction.objects.update_or_create(
                        compound_id=compound_id,
                        defaults={
                            'smiles': smiles,
                            'smiles_sha256': smiles_hash,
                            'model_version': get_molprop_version(),
                            'predictions': {},
                            'uncertainty': {},
                            'error': str(exc),
                        },
                    )
                molprop_computed += 1

    get_or_compute_stack_risk(stack, items=items)
    return redirect(
        _append_query_params(
            next_url,
            {
                'risk': 'ok',
                'computed_admet': str(admet_computed),
                'computed_molprop': str(molprop_computed),
                'skipped': str(skipped),
            },
        )
    )


def _build_calendar_context(
    *,
    occurrences,
    period: str,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
):
    tz = timezone.get_current_timezone()
    by_day = defaultdict(list)
    for o in occurrences:
        by_day[timezone.localtime(o.scheduled_for, tz).date()].append(o)

    local_window_start = timezone.localtime(window_start, tz).date()
    local_window_end = timezone.localtime(window_end, tz).date()
    local_today = timezone.localtime(now, tz).date()

    if period == 'month':
        month_start = local_window_start.replace(day=1)
        month_end = local_window_end
        grid_start = month_start - timedelta(days=month_start.weekday())
        last_in_month = month_end - timedelta(days=1)
        grid_end = last_in_month + timedelta(days=(6 - last_in_month.weekday()) + 1)  # exclusive
        columns = 7
        title = month_start.strftime('%B %Y')
        current_month = month_start.month
    elif period == 'week':
        grid_start = local_window_start
        grid_end = local_window_end
        columns = 7
        title = f"Week of {grid_start.strftime('%b %d, %Y')}"
        current_month = None
    elif period == 'day':
        grid_start = local_window_start
        grid_end = grid_start + timedelta(days=1)
        columns = 1
        title = grid_start.strftime('%b %d, %Y')
        current_month = None
    else:
        grid_start = local_window_start
        grid_end = local_window_end
        columns = 7
        title = "Schedule"
        current_month = None

    cells = []
    d: date = grid_start
    while d < grid_end:
        day_occurrences = by_day.get(d, [])
        count = len(day_occurrences)
        is_past_or_today = d <= local_today

        # Adherence heatmap for past/today; count-based for future.
        taken_count = sum(
            1 for o in day_occurrences
            if getattr(o, 'is_taken', False) and not getattr(o, 'is_unstacked', False)
        )
        scheduled_count = sum(
            1 for o in day_occurrences
            if not getattr(o, 'is_unstacked', False)
        )

        if scheduled_count == 0:
            level = 0
        elif not is_past_or_today:
            # Future: shade by scheduled count
            level = min(scheduled_count, 4)
        elif taken_count == scheduled_count:
            level = 1  # green: perfect adherence
        elif taken_count > 0:
            level = 2  # yellow: partial
        else:
            level = 3  # orange: missed entirely

        bar_height = min(100, scheduled_count * 20) if scheduled_count else 0
        adherence_pct = int(round(taken_count / scheduled_count * 100)) if scheduled_count > 0 else None

        cells.append(
            {
                'date': d,
                'occurrences': day_occurrences,
                'count': count,
                'scheduled_count': scheduled_count,
                'taken_count': taken_count,
                'adherence_pct': adherence_pct,
                'level': level,
                'bar_height': bar_height,
                'is_today': d == local_today,
                'is_past': is_past_or_today and d != local_today,
                'is_outside_month': (current_month is not None) and (d.month != current_month),
            }
        )
        d = d + timedelta(days=1)

    if columns == 7:
        weeks = [cells[i : i + 7] for i in range(0, len(cells), 7)]
    else:
        weeks = [cells]

    return {
        'title': title,
        'columns': columns,
        'weeks': weeks,
    }


class MyStacksView(LoginRequiredMixin, TemplateView):
    template_name = 'stacks/my_stacks.html'


    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        # Main form for creating stacks
        context['form'] = StackForm()
        return self.render_to_response(context)

    def post(self, request, *args, **kwargs):
        if 'add_stack' in request.POST:
            form = StackForm(request.POST)
            if form.is_valid():
                stack = form.save(commit=False)
                stack.user = request.user
                stack.save()
                return redirect('my_stacks')
            context = self.get_context_data(**kwargs)
            context['form'] = form
            return self.render_to_response(context)
        elif 'delete_stack' in request.POST:
            stack_id = request.POST.get('stack_id')
            stack = Stack.objects.filter(id=stack_id, user=request.user).first()
            if stack:
                stack.delete()
            return redirect('my_stacks')
        elif 'toggle_stack_active' in request.POST:
            stack_id = request.POST.get('stack_id')
            stack = Stack.objects.filter(id=stack_id, user=request.user).first()
            if stack:
                stack.is_active = not stack.is_active
                stack.save(update_fields=['is_active'])
            return redirect('my_stacks')
        elif 'set_stack_visibility' in request.POST:
            stack_id = request.POST.get('stack_id')
            visibility = request.POST.get('visibility')
            stack = Stack.objects.filter(id=stack_id, user=request.user).first()
            if stack and visibility in dict(Stack.VISIBILITY_CHOICES):
                stack.visibility = visibility
                stack.save(update_fields=['visibility'])
            return redirect('my_stacks')
        else:
            return redirect('my_stacks')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['stacks'] = (
            Stack.objects.filter(user=self.request.user)
            .annotate(item_count=Count('items'))
            .select_related('risk_assessment')
            .order_by('-created')
        )
        for s in context['stacks']:
            s.risk = _safe_get_risk_assessment(s)
        return context


class StackDetailView(LoginRequiredMixin, TemplateView):
    template_name = 'stacks/stack_detail.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.stack = Stack.objects.filter(id=kwargs.get('stack_id'), user=request.user).first()
        if not self.stack:
            return redirect('my_stacks')
        _push_recent_stack(request, self.stack)
        return super().dispatch(request, *args, **kwargs)

    def _get_recommendation_traits(self):
        db_traits = list(
            StackTrait.objects.filter(is_active=True)
            .order_by('display_order', 'label')
            .values('slug', 'label', 'trait_type', 'is_hypothesis', 'default_weight')
        )
        if db_traits:
            return db_traits
        return [
            {
                'slug': row['slug'],
                'label': row['label'],
                'trait_type': row['trait_type'],
                'is_hypothesis': row['is_hypothesis'],
                'default_weight': row.get('default_weight', 1.0),
            }
            for row in DEFAULT_TRAITS
        ]

    def _default_recommendation_form(self, traits):
        max_traits = {row['slug']: '' for row in traits if row['trait_type'] == 'risk'}
        default_selected = []
        return {
            'max_traits': max_traits,
            'selected_focus_groups': default_selected,
            'max_stack_size': '3',
            'top_k': '5',
            'beam_width': '12',
            'min_confidence': 'medium',
            'output_mode': 'ranked',
            'include_distribution': False,
            'no_cyp3a4_conflicts': False,
            'required_route': '',
            'min_group_score': '0.5',
            'species': '',
            'assay_type': '',
            'route': '',
        }

    def _bind_recommendation_trait_rows(self, traits, form_state):
        rows = []
        for trait in traits:
            slug = trait['slug']
            row = dict(trait)
            row['max_value'] = (form_state.get('max_traits') or {}).get(slug, '')
            rows.append(row)
        return rows

    def _build_grouping_sections(self, traits, form_state):
        trait_rows = [dict(row) for row in traits]
        selected = set(form_state.get('selected_focus_groups') or [])
        grouped = defaultdict(list)

        for option in grouping_preset_options():
            trait_slug = option.get('trait_slug') or 'other'
            grouped[trait_slug].append(
                {
                    **option,
                    'field_name': f"focus_group_{option['slug']}",
                    'selected': option['slug'] in selected,
                }
            )

        sections = []
        for row in trait_rows:
            options = grouped.pop(row['slug'], [])
            if not options:
                continue
            sections.append(
                {
                    'trait_slug': row['slug'],
                    'trait_label': row['label'],
                    'trait_type': row.get('trait_type', ''),
                    'options': options,
                }
            )
        for trait_slug, options in grouped.items():
            sections.append(
                {
                    'trait_slug': trait_slug,
                    'trait_label': trait_slug.replace('_', ' ').title(),
                    'trait_type': 'benefit',
                    'options': options,
                }
            )
        return sections

    def _build_recommendation_payload(self, request, traits):
        errors = []
        form_state = self._default_recommendation_form(traits)

        preset_map = {row['slug']: row for row in grouping_preset_options()}
        selected_focus_groups = []
        for preset_slug in preset_map:
            field_name = f'focus_group_{preset_slug}'
            if request.POST.get(field_name):
                selected_focus_groups.append(preset_slug)
        form_state['selected_focus_groups'] = selected_focus_groups

        if not selected_focus_groups:
            errors.append("Select at least one category toggle.")

        trait_defaults = {}
        for row in traits:
            try:
                trait_defaults[row['slug']] = float(row.get('default_weight') or 1.0)
            except (TypeError, ValueError):
                trait_defaults[row['slug']] = 1.0

        trait_selection_count = defaultdict(int)
        for group_slug in selected_focus_groups:
            trait_slug = (preset_map.get(group_slug) or {}).get('trait_slug')
            if trait_slug:
                trait_selection_count[trait_slug] += 1

        goals = {}
        for trait_slug, selection_count in trait_selection_count.items():
            base_weight = trait_defaults.get(trait_slug, 1.0)
            goals[trait_slug] = round(base_weight * (1.0 + (0.15 * max(0, selection_count - 1))), 3)

        max_traits = {}
        for row in traits:
            if row['trait_type'] != 'risk':
                continue
            slug = row['slug']
            raw = (request.POST.get(f'max_{slug}') or '').strip()
            form_state['max_traits'][slug] = raw
            if not raw:
                continue
            try:
                max_traits[slug] = float(raw)
            except ValueError:
                errors.append(f"Invalid max value for risk trait '{slug}': {raw}")

        form_state['min_confidence'] = (request.POST.get('min_confidence') or 'medium').strip().lower()
        if form_state['min_confidence'] not in {'low', 'medium', 'high'}:
            form_state['min_confidence'] = 'medium'

        form_state['output_mode'] = (request.POST.get('output_mode') or 'ranked').strip().lower()
        if form_state['output_mode'] not in {'ranked', 'hybrid', 'cloud'}:
            form_state['output_mode'] = 'ranked'
        form_state['include_distribution'] = bool(request.POST.get('include_distribution'))
        if form_state['output_mode'] in {'hybrid', 'cloud'}:
            form_state['include_distribution'] = True

        form_state['no_cyp3a4_conflicts'] = bool(request.POST.get('no_cyp3a4_conflicts'))
        form_state['required_route'] = (request.POST.get('required_route') or '').strip()
        parsed_focus_groups = parse_focus_groups(selected_focus_groups)
        form_state['min_group_score'] = (request.POST.get('min_group_score') or '0.5').strip()
        try:
            min_group_score = float(form_state['min_group_score'])
        except ValueError:
            errors.append(f"Invalid min group score: {form_state['min_group_score']}")
            min_group_score = 0.5
        min_group_score = max(0.0, min(10.0, min_group_score))
        form_state['min_group_score'] = str(min_group_score)
        form_state['species'] = (request.POST.get('species') or '').strip()
        form_state['assay_type'] = (request.POST.get('assay_type') or '').strip()
        form_state['route'] = (request.POST.get('route') or '').strip()

        for int_field, min_val, max_val, default in (
            ('max_stack_size', 1, 6, 3),
            ('top_k', 1, 12, 5),
            ('beam_width', 2, 48, 12),
        ):
            raw = (request.POST.get(int_field) or str(default)).strip()
            form_state[int_field] = raw
            try:
                parsed = int(raw)
            except ValueError:
                errors.append(f"Invalid integer for {int_field}: {raw}")
                parsed = default
            if parsed < min_val or parsed > max_val:
                parsed = max(min_val, min(max_val, parsed))
            form_state[int_field] = str(parsed)

        payload = {
            'goals': goals,
            'constraints': {
                'max_traits': max_traits,
                'no_cyp3a4_conflicts': form_state['no_cyp3a4_conflicts'],
                'required_route': form_state['required_route'],
                'focus_groups': parsed_focus_groups,
                'min_group_score': min_group_score,
            },
            'max_stack_size': int(form_state['max_stack_size']),
            'top_k': int(form_state['top_k']),
            'beam_width': int(form_state['beam_width']),
            'min_evidence_confidence': form_state['min_confidence'],
            'output_mode': form_state['output_mode'],
            'include_distribution': form_state['include_distribution'],
            'desired_context': {
                'species': form_state['species'],
                'assay_type': form_state['assay_type'],
                'route': form_state['route'],
            },
        }
        return form_state, payload, errors

    def post(self, request, *args, **kwargs):
        if 'add_compound_to_stack' in request.POST:
            form = AddCompoundForm(request.POST)
            if form.is_valid():
                item = form.save(commit=False)
                item.stack = self.stack
                item.save()
                return redirect('stack_detail', stack_id=self.stack.id)
            context = self.get_context_data(**kwargs)
            context['add_form'] = form
            return self.render_to_response(context)

        if 'update_stack_item' in request.POST:
            item_id = request.POST.get('item_id')
            item = StackItem.objects.filter(id=item_id, stack=self.stack).select_related('compound').first()
            if not item:
                return redirect('stack_detail', stack_id=self.stack.id)

            form = AddCompoundForm(request.POST, instance=item)
            if form.is_valid():
                updated = form.save(commit=False)
                updated.stack = self.stack
                updated.save()
                return redirect('stack_detail', stack_id=self.stack.id)

            context = self.get_context_data(**kwargs)
            context['edit_item_id'] = item.id
            context['edit_form'] = form
            return self.render_to_response(context)

        if 'update_stack_name' in request.POST:
            form = StackForm(request.POST, instance=self.stack)
            if form.is_valid():
                self.stack = form.save()
                return redirect('stack_detail', stack_id=self.stack.id)

            context = self.get_context_data(**kwargs)
            context['stack_form'] = form
            return self.render_to_response(context)

        if 'delete_stack_item' in request.POST:
            item_id = request.POST.get('item_id')
            item = StackItem.objects.filter(id=item_id, stack=self.stack).first()
            if item:
                item.delete()
            return redirect('stack_detail', stack_id=self.stack.id)

        if 'toggle_stack_active' in request.POST:
            self.stack.is_active = not self.stack.is_active
            self.stack.save(update_fields=['is_active'])
            return redirect('stack_detail', stack_id=self.stack.id)

        if 'set_stack_visibility' in request.POST:
            visibility = request.POST.get('visibility')
            if visibility in dict(Stack.VISIBILITY_CHOICES):
                self.stack.visibility = visibility
                self.stack.save(update_fields=['visibility'])
            return redirect('stack_detail', stack_id=self.stack.id)

        if 'delete_stack' in request.POST:
            self.stack.delete()
            return redirect('my_stacks')

        if 'recommend_stack_additions' in request.POST:
            context = self.get_context_data(**kwargs)
            traits = context['recommendation_traits']
            form_state, payload, errors = self._build_recommendation_payload(request, traits)
            stack_compound_ids = [item.compound_id for item in context['items']]
            recommendation_result = None
            if not errors:
                recommendation_result = recommend_stack_builds(
                    goals=payload['goals'],
                    constraints=payload['constraints'],
                    base_compound_ids=stack_compound_ids,
                    max_stack_size=payload['max_stack_size'],
                    beam_width=payload['beam_width'],
                    top_k=payload['top_k'],
                    min_evidence_confidence=payload['min_evidence_confidence'],
                    output_mode=payload['output_mode'],
                    include_distribution=payload['include_distribution'],
                    desired_context=payload['desired_context'],
                )
            context['stack_recommendation_form'] = form_state
            context['recommendation_trait_rows'] = self._bind_recommendation_trait_rows(traits, form_state)
            context['grouping_sections'] = self._build_grouping_sections(traits, form_state)
            context['stack_recommendation_result'] = recommendation_result
            context['stack_recommendation_meta'] = (recommendation_result or {}).get('meta')
            context['stack_recommendation_errors'] = errors
            return self.render_to_response(context)

        return redirect('stack_detail', stack_id=self.stack.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['stack'] = self.stack
        context['items'] = (
            StackItem.objects.filter(stack=self.stack)
            .select_related('compound')
            .order_by('order', 'added')
        )
        edit_raw = (self.request.GET.get('edit') or '').strip()
        edit_item_id = None
        try:
            if edit_raw:
                edit_item_id = int(edit_raw)
        except ValueError:
            edit_item_id = None

        risk_result = get_or_compute_stack_risk(self.stack, items=list(context['items']))
        context['stack_risk'] = risk_result.assessment
        context['stack_risk_status'] = (self.request.GET.get('risk') or '').strip()
        context['stack_risk_refresh_url'] = reverse('stack_risk_refresh', kwargs={'stack_id': self.stack.id})

        # Auto-refresh uncached compound predictions for this stack to improve coverage.
        try:
            from compounds.admet_ai import is_admet_ai_available
            from compounds.molprop import is_molprop_available

            admet_available = is_admet_ai_available()
            molprop_available = is_molprop_available()
        except Exception:
            admet_available = False
            molprop_available = False

        needs_prediction = False
        if admet_available or molprop_available:
            from compounds.models import CompoundADMETPrediction, CompoundMolPropPrediction

            compounds = {i.compound_id: i.compound for i in context['items']}
            admet_qs = CompoundADMETPrediction.objects.filter(compound_id__in=list(compounds.keys()))
            admet_map = {p.compound_id: p for p in admet_qs}
            molprop_qs = CompoundMolPropPrediction.objects.filter(compound_id__in=list(compounds.keys()))
            molprop_map = {p.compound_id: p for p in molprop_qs}
            for compound_id, compound in compounds.items():
                smiles = (compound.smiles or '').strip()
                if not smiles:
                    continue
                smiles_hash = hashlib.sha256(smiles.encode('utf-8')).hexdigest()

                if admet_available:
                    pred = admet_map.get(compound_id)
                    if (
                        not pred
                        or pred.smiles_sha256 != smiles_hash
                        or not isinstance(pred.predictions, dict)
                        or not pred.predictions
                        or (pred.error or '').strip()
                    ):
                        needs_prediction = True
                        break

                if molprop_available:
                    mol = molprop_map.get(compound_id)
                    if (
                        not mol
                        or mol.smiles_sha256 != smiles_hash
                        or not isinstance(mol.predictions, dict)
                        or not mol.predictions
                        or (mol.error or '').strip()
                    ):
                        needs_prediction = True
                        break

        autoload_already_attempted = (self.request.GET.get('risk_autoload') or '').strip() == '1'
        context['stack_risk_autoload'] = bool(
            needs_prediction and not edit_item_id and not autoload_already_attempted
        )
        context['stack_risk_autoload_next'] = _append_query_params(
            self.request.get_full_path(),
            {'risk_autoload': '1'},
        )

        stack_compound_ids = [item.compound_id for item in context['items']]
        if stack_compound_ids:
            context['stack_trait_sheet'] = analyze_stack_character_sheet(
                compound_ids=stack_compound_ids,
                goals={},
                constraints={},
                min_evidence_confidence="low",
            )
        else:
            context['stack_trait_sheet'] = None
        context['enzymatic_overload'] = compute_enzymatic_overload(stack_compound_ids)

        context['recommendation_traits'] = self._get_recommendation_traits()
        context['stack_recommendation_form'] = self._default_recommendation_form(context['recommendation_traits'])
        context['recommendation_trait_rows'] = self._bind_recommendation_trait_rows(
            context['recommendation_traits'],
            context['stack_recommendation_form'],
        )
        context['grouping_sections'] = self._build_grouping_sections(
            context['recommendation_traits'],
            context['stack_recommendation_form'],
        )
        context['stack_recommendation_result'] = None
        context['stack_recommendation_meta'] = None
        context['stack_recommendation_errors'] = []
        context['grouping_presets'] = grouping_preset_options()

        context['stack_form'] = StackForm(instance=self.stack)
        context['add_form'] = AddCompoundForm()
        context['edit_item_id'] = edit_item_id
        context['edit_form'] = None
        if edit_item_id:
            item = StackItem.objects.filter(id=edit_item_id, stack=self.stack).select_related('compound').first()
            if item:
                context['edit_form'] = AddCompoundForm(instance=item)

        events = [
            {
                'ts': self.stack.created,
                'title': 'Stack created',
                'detail': self.stack.name,
            }
        ]
        for item in context['items'][:20]:
            events.append(
                {
                    'ts': item.added,
                    'title': 'Compound added',
                    'detail': item.compound.name,
                }
            )
        if context.get('stack_risk') and context['stack_risk'].computed_at:
            events.append(
                {
                    'ts': context['stack_risk'].computed_at,
                    'title': 'Risk snapshot refreshed',
                    'detail': context['stack_risk'].risk_level,
                }
            )
        events.sort(key=lambda row: row['ts'], reverse=True)
        context['stack_activity_events'] = events[:10]

        # Smart timing suggestions: flag CYP inhibitor↔substrate pairs in this stack.
        context['timing_suggestions'] = _compute_timing_suggestions(list(context['items']))

        return context


def _compute_timing_suggestions(items) -> list:
    """
    Return a list of dicts warning about CYP inhibitor↔substrate pairs in a stack.

    Each dict: {compound_a, compound_b, cyp_target, mechanism_a, mechanism_b, suggestion_minutes}
    """
    from compounds.models import CompoundTargetInteraction, EffectWindow

    compound_ids = [item.compound_id for item in items]
    if len(compound_ids) < 2:
        return []

    cyp_rows = (
        CompoundTargetInteraction.objects
        .filter(compound_id__in=compound_ids, target__name__icontains='CYP')
        .select_related('target', 'compound')
        .values('compound_id', 'compound__name', 'target__name', 'mechanism')
    )
    cyp_map: dict = {}
    for row in cyp_rows:
        cid = row['compound_id']
        cyp_map.setdefault(cid, {})
        existing_mech = cyp_map[cid].get(row['target__name'])
        if existing_mech is None or row['mechanism'] in ('inhibitor', 'inducer'):
            cyp_map[cid][row['target__name']] = (row['mechanism'], row['compound__name'])

    # EffectWindow durations for spacing suggestions
    ew_qs = EffectWindow.objects.filter(compound_id__in=compound_ids).values('compound_id', 'duration_minutes')
    ew_duration: dict = {}
    for row in ew_qs:
        if row['compound_id'] not in ew_duration:
            ew_duration[row['compound_id']] = row['duration_minutes']

    suggestions = []
    seen = set()
    for i, item_a in enumerate(items):
        cyp_a = cyp_map.get(item_a.compound_id, {})
        for item_b in items[i + 1:]:
            if item_a.compound_id == item_b.compound_id:
                continue
            cyp_b = cyp_map.get(item_b.compound_id, {})
            for cyp_name, (mech_a, name_a) in cyp_a.items():
                if cyp_name not in cyp_b:
                    continue
                mech_b, name_b = cyp_b[cyp_name]
                roles = {mech_a, mech_b}
                if roles & {'inhibitor', 'inducer'} and 'substrate' in roles:
                    pair = tuple(sorted([item_a.compound_id, item_b.compound_id]))
                    if pair in seen:
                        continue
                    seen.add(pair)
                    # Suggest spacing equal to the inhibitor's effect duration.
                    inhibitor_id = item_a.compound_id if mech_a in ('inhibitor', 'inducer') else item_b.compound_id
                    suggestion_minutes = ew_duration.get(inhibitor_id, 120)
                    suggestions.append({
                        'compound_a': name_a,
                        'compound_b': name_b,
                        'cyp_target': cyp_name,
                        'mechanism_a': mech_a,
                        'mechanism_b': mech_b,
                        'suggestion_hours': round(suggestion_minutes / 60, 1),
                    })
    return suggestions


@login_required
def stack_schedule_ical(request):
    """Live iCal subscription feed — one VEVENT+RRULE per stack item dose slot.

    Calendar apps re-fetch this URL on their refresh schedule; each fetch
    reflects the current scheduling rules without pre-expanding dates.
    Cycling (drug holidays) cannot be expressed as a plain RRULE, so it is
    noted in the event description and the calendar app will show every
    recurrence — users should expect off-days to still appear.
    """
    from datetime import timezone as _dt_tz

    items = (
        StackItem.objects.filter(stack__user=request.user, stack__is_active=True)
        .select_related('stack', 'compound')
    )

    def ical_escape(text: str) -> str:
        return (
            str(text or '')
            .replace('\\', '\\\\')
            .replace('\n', '\\n')
            .replace(',', '\\,')
            .replace(';', '\\;')
        )

    def fmt_dt(dt) -> str:
        utc = dt.astimezone(_dt_tz.utc)
        return utc.strftime('%Y%m%dT%H%M%SZ')

    def rrule_for_item(item) -> str:
        freq_map = {'daily': 'DAILY', 'weekly': 'WEEKLY', 'monthly': 'MONTHLY'}
        freq = freq_map.get(item.recurrence_unit, 'DAILY')
        interval = item.recurrence_interval or 1
        return f'FREQ={freq};INTERVAL={interval}'

    # Build the feed URL for REFRESH-INTERVAL / SOURCE
    feed_url = request.build_absolute_uri(request.path)

    cal_lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//Neurobin//Stack Schedule//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'X-WR-CALNAME:Neurobin Stack Schedule',
        # Ask clients to refresh every 3 hours
        'REFRESH-INTERVAL;VALUE=DURATION:PT3H',
        f'SOURCE;VALUE=URI:{feed_url}',
        f'URL:{feed_url}',
    ]

    now_utc = timezone.now().astimezone(_dt_tz.utc)

    for item in items:
        # Determine the anchor DTSTART.  Use the stored intake_time if set;
        # otherwise fall back to today at a time derived from time_of_day.
        if item.intake_time:
            anchor = item.intake_time.astimezone(_dt_tz.utc)
        else:
            fallback_hour = {'morning': 8, 'afternoon': 13, 'evening': 18, 'night': 21}.get(
                item.time_of_day or '', 9
            )
            anchor = now_utc.replace(hour=fallback_hour, minute=0, second=0, microsecond=0)

        doses = max(item.doses_per_recurrence or 1, 1)

        # Compute the spacing between doses within a single recurrence period
        freq_map = {'daily': 1440, 'weekly': 10080, 'monthly': 43200}
        period_minutes = freq_map.get(item.recurrence_unit, 1440) // max(item.recurrence_interval or 1, 1)
        dose_spacing = period_minutes // doses

        summary_base = ical_escape(item.compound.name)
        if item.dosage_amount:
            summary_base += f' {ical_escape(item.dosage_amount)} {ical_escape(item.dosage_unit)}'

        desc_parts = [f'Stack: {ical_escape(item.stack.name)}']
        if item.cycle_on_days and item.cycle_off_days:
            desc_parts.append(
                f'Cycling: {item.cycle_on_days} days on / {item.cycle_off_days} days off'
                ' (calendar shows all days; ignore off-days manually)'
            )
        description = ical_escape('\\n'.join(desc_parts))

        rrule = rrule_for_item(item)

        for dose_idx in range(doses):
            dose_start = anchor + timedelta(minutes=dose_spacing * dose_idx)
            dose_end = dose_start + timedelta(minutes=30)
            uid = f'item-{item.pk}-dose-{dose_idx}@neurobin'

            cal_lines += [
                'BEGIN:VEVENT',
                f'UID:{uid}',
                f'DTSTART:{fmt_dt(dose_start)}',
                f'DTEND:{fmt_dt(dose_end)}',
                f'RRULE:{rrule}',
                f'SUMMARY:{summary_base}',
                f'DESCRIPTION:{description}',
                f'LAST-MODIFIED:{fmt_dt(now_utc)}',
                'END:VEVENT',
            ]

    cal_lines.append('END:VCALENDAR')
    content = '\r\n'.join(cal_lines) + '\r\n'
    response = HttpResponse(content, content_type='text/calendar; charset=utf-8')
    # inline (not attachment) so calendar apps can subscribe directly
    response['Content-Disposition'] = 'inline; filename="stack-schedule.ics"'
    return response


class StackScheduleView(LoginRequiredMixin, TemplateView):
    template_name = 'stacks/schedule.html'

    def post(self, request, *args, **kwargs):
        period = 'day'
        scheduled_for_raw = (request.POST.get('scheduled_for') or '').strip()
        scheduled_for = None
        if scheduled_for_raw:
            try:
                scheduled_for_str = scheduled_for_raw.replace('Z', '+00:00')
                scheduled_for = datetime.fromisoformat(scheduled_for_str)
                if timezone.is_naive(scheduled_for):
                    scheduled_for = timezone.make_aware(scheduled_for, timezone.get_current_timezone())
            except ValueError:
                scheduled_for = None

        if 'take_stack_item' in request.POST:
            item_id = request.POST.get('stack_item_id')
            item = StackItem.objects.filter(id=item_id, stack__user=request.user).select_related('stack', 'compound').first()
            if item:
                take_stack_item(
                    item,
                    user=request.user,
                    taken_at=timezone.now(),
                    scheduled_for=scheduled_for,
                )
        elif 'untake_stack_item' in request.POST:
            item_id = request.POST.get('stack_item_id')
            item = StackItem.objects.filter(id=item_id, stack__user=request.user).select_related('stack', 'compound').first()
            if item and scheduled_for:
                untake_stack_item_occurrence(item, user=request.user, scheduled_for=scheduled_for)
        return redirect('stack_schedule')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        period = 'day'
        window_start, until = get_schedule_window(now=now, period=period)
        items = (
            StackItem.objects.filter(stack__user=self.request.user, stack__is_active=True)
            .select_related('stack', 'compound')
        )
        context['now'] = now
        context['period'] = period
        occurrences = iter_upcoming_occurrences(items, now=now, until=until, window_start=window_start)
        occurrences = annotate_occurrences_taken(
            occurrences,
            user=self.request.user,
            window_start=window_start,
            window_end=until,
        )
        occurrences = merge_taken_logs_into_occurrences(
            occurrences,
            user=self.request.user,
            window_start=window_start,
            window_end=until,
        )

        schedule_entries = list(occurrences)
        unstacked_logs = (
            IntakeLog.objects.filter(
                user=self.request.user,
                stack_item__isnull=True,
                taken_at__gte=window_start,
                taken_at__lt=until,
            )
            .select_related('compound')
            .only(
                'compound_id',
                'compound__name',
                'compound__slug',
                'taken_at',
                'amount',
                'unit',
                'time_of_day',
            )
            .order_by('taken_at')
        )

        for log in unstacked_logs:
            schedule_entries.append({
                'stack_id': None,
                'stack_name': 'Logged (no stack)',
                'stack_item_id': None,
                'compound_id': log.compound_id,
                'compound_name': getattr(log.compound, 'name', ''),
                'compound_slug': getattr(log.compound, 'slug', ''),
                'scheduled_for': log.taken_at,
                'dosage_amount': log.amount or None,
                'dosage_unit': log.unit or '',
                'time_of_day': log.time_of_day,
                'is_taken': True,
                'is_unstacked': True,
            })

        def _entry_time(entry):
            if isinstance(entry, dict):
                return entry.get('scheduled_for')
            return getattr(entry, 'scheduled_for', None)

        schedule_entries.sort(key=_entry_time)

        context['occurrences'] = occurrences[:200]
        context['schedule_entries'] = schedule_entries[:200]
        context['calendar'] = _build_calendar_context(
            occurrences=occurrences,
            period=period,
            window_start=window_start,
            window_end=until,
            now=now,
        )

        # Adherence stats bar
        adherence = compute_adherence_stats(occurrences, user=self.request.user, now=now)
        context.update(adherence)

        # Effect-window timeline data (Chart.js horizontal floating bars)
        context['timeline_data_json'] = json.dumps(build_timeline_data(occurrences, now=now))

        # CYP conflict warnings
        context['conflict_warnings'] = detect_timing_conflicts(occurrences, now=now)

        return context


class StackCalendarView(LoginRequiredMixin, TemplateView):
    template_name = 'stacks/calendar.html'

    def post(self, request, *args, **kwargs):
        period = (request.POST.get('period') or '').strip().lower()
        scheduled_for_raw = (request.POST.get('scheduled_for') or '').strip()
        scheduled_for = None
        if scheduled_for_raw:
            try:
                scheduled_for_str = scheduled_for_raw.replace('Z', '+00:00')
                scheduled_for = datetime.fromisoformat(scheduled_for_str)
                if timezone.is_naive(scheduled_for):
                    scheduled_for = timezone.make_aware(scheduled_for, timezone.get_current_timezone())
            except ValueError:
                scheduled_for = None

        if 'take_stack_item' in request.POST:
            item_id = request.POST.get('stack_item_id')
            item = (
                StackItem.objects.filter(id=item_id, stack__user=request.user)
                .select_related('stack', 'compound')
                .first()
            )
            if item:
                take_stack_item(
                    item,
                    user=request.user,
                    taken_at=timezone.now(),
                    scheduled_for=scheduled_for,
                )
        elif 'untake_stack_item' in request.POST:
            item_id = request.POST.get('stack_item_id')
            item = (
                StackItem.objects.filter(id=item_id, stack__user=request.user)
                .select_related('stack', 'compound')
                .first()
            )
            if item and scheduled_for:
                untake_stack_item_occurrence(item, user=request.user, scheduled_for=scheduled_for)

        if period in {'day', 'week', 'month'}:
            return redirect(f"{reverse('stack_calendar')}?period={period}")
        return redirect('stack_calendar')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        period = (self.request.GET.get('period') or 'month').strip().lower()
        try:
            window_start, until = get_schedule_window(now=now, period=period)
        except ValueError:
            period = 'month'
            window_start, until = get_schedule_window(now=now, period=period)

        items = (
            StackItem.objects.filter(stack__user=self.request.user, stack__is_active=True)
            .select_related('stack', 'compound')
        )
        occurrences = iter_upcoming_occurrences(items, now=now, until=until, window_start=window_start)
        occurrences = annotate_occurrences_taken(
            occurrences,
            user=self.request.user,
            window_start=window_start,
            window_end=until,
        )
        occurrences = merge_taken_logs_into_occurrences(
            occurrences,
            user=self.request.user,
            window_start=window_start,
            window_end=until,
        )

        context['now'] = now
        context['period'] = period
        context['calendar'] = _build_calendar_context(
            occurrences=occurrences,
            period=period,
            window_start=window_start,
            window_end=until,
            now=now,
        )
        return context


class StackShareView(TemplateView):
    template_name = 'stacks/share.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stack = _get_shareable_stack_or_404(self.request, kwargs.get('stack_id'))
        items = list(stack.items.all().select_related('compound').order_by('order', 'added'))
        risk_result = get_or_compute_stack_risk(stack, items=items)
        context['stack'] = stack
        context['items'] = items
        context['stack_risk'] = risk_result.assessment
        context['share_url'] = self.request.build_absolute_uri()
        context['embed_url'] = self.request.build_absolute_uri(reverse('stack_share_embed', kwargs={'stack_id': stack.id}))
        context['stack_detail_url'] = self.request.build_absolute_uri(reverse('stack_detail', kwargs={'stack_id': stack.id}))
        context['embed_description'] = _build_stack_embed_description(stack, items)
        return context


class StackShareEmbedView(TemplateView):
    template_name = 'stacks/share_embed.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stack = _get_shareable_stack_or_404(self.request, kwargs.get('stack_id'))
        context['stack'] = stack
        context['items'] = list(stack.items.all().select_related('compound').order_by('order', 'added'))[:30]
        return context


class ExploreStacksView(LoginRequiredMixin, TemplateView):
    template_name = 'stacks/explore.html'

    def post(self, request, *args, **kwargs):
        if 'copy_stack' in request.POST:
            stack_id = request.POST.get('stack_id')
            source = (
                Stack.objects.filter(id=stack_id, visibility='public')
                .exclude(user=request.user)
                .prefetch_related('items__compound')
                .first()
            )
            if source:
                new_stack = Stack.objects.create(
                    user=request.user,
                    name=source.name,
                    description=source.description,
                    visibility='private',
                    is_active=False,
                    copied_from=source,
                    copied_at=timezone.now(),
                )
                items_to_create = []
                for src_item in source.items.all():
                    items_to_create.append(
                        StackItem(
                            stack=new_stack,
                            compound=src_item.compound,
                            dosage_amount=src_item.dosage_amount,
                            dosage_unit=src_item.dosage_unit,
                            time_of_day=src_item.time_of_day,
                            intake_time=src_item.intake_time,
                            recurrence_interval=src_item.recurrence_interval,
                            recurrence_unit=src_item.recurrence_unit,
                            order=src_item.order,
                            notes=src_item.notes,
                            completed=False,
                        )
                    )
                if items_to_create:
                    StackItem.objects.bulk_create(items_to_create)
        return redirect('explore_stacks')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        q = (self.request.GET.get('q') or '').strip()
        stacks = (
            Stack.objects.filter(visibility='public')
            .annotate(usage_count=Count('copies', distinct=True))
            .select_related('user')
            .select_related('risk_assessment')
            .prefetch_related('items__compound')
            .order_by('-usage_count', '-created')
        )
        if q:
            stacks = stacks.filter(name__icontains=q)
        context['q'] = q
        context['public_stacks'] = list(stacks)
        for s in context['public_stacks']:
            s.risk = _safe_get_risk_assessment(s)
        return context


class StackBuilderView(LoginRequiredMixin, TemplateView):
    """Interactive visual stack builder with functional taxonomy."""

    template_name = 'stacks/stack_builder.html'

    # Target-name substrings that indicate a compound belongs in the builder.
    # This is the server-side pre-filter; JS does the fine-grained taxonomy.
    _TARGET_KEYWORDS = [
        'androgen', 'estrogen', 'progesterone', 'aromatase',
        'dopamine', 'serotonin', '5-ht', 'gaba', 'glutamate', 'ampa', 'nmda',
        'acetylcholin', 'muscarinic', 'nicotinic',
        'norepinephrine', 'adrenergic', 'noradrenalin',
        'opioid', 'cannabinoid', 'sigma',
        'histamine', 'adenosine', 'melatonin',
        'insulin', 'glucagon', 'thyroid', 'mtor', 'ampk',
        'bdnf', 'ngf', 'trkb', 'vegf',
        'calcium channel', 'ace inhibitor', 'angiotensin',
        'cox', 'cyclooxygenase', 'interleukin', 'tnf',
        'growth hormone', 'igf', 'ghrelin',
        'prolactin', 'gonadotropin',
    ]
    _CATEGORY_KEYWORDS = [
        'anabolic', 'androgen', 'steroid', 'sarm', 'peptide',
        'nootropic', 'neuroenhancer', 'cognitive',
        'antipsychotic', 'anxiolytic', 'antidepressant',
        'opioid', 'cannabinoid', 'psychedelic',
        'stimulant', 'sedative', 'hypnotic',
        'anti-inflammatory', 'analgesic',
        'cardiovascular', 'antihypertensive',
        'antidiabetic', 'thyroid', 'metabolic',
        'hormone', 'estrogen', 'contraceptive',
        'anti-cancer', 'antineoplastic', 'antitumor',
        'antibiotic', 'antiviral', 'antifungal',
        'immunomodulat', 'immunosuppressant',
        'longevity', 'anti-aging', 'neuroprotect',
        'sex hormone', 'endocrine', 'anticancer',
        'antiepileptic', 'anticonvulsant',
        'mood stabilizer', 'psychostimulant',
        'beta blocker', 'calcium channel',
        'ace inhibitor', 'statin', 'lipid',
        'weight management', 'obesity',
        'antihistamine', 'anti-parkinson', 'antiparkinsonian',
    ]
    # Explicit compound-name substrings for compounds that may have no
    # categories or MoA records in the DB (e.g. most anabolics/peptides).
    _NAME_KEYWORDS = [
        # Androgens / AAS
        'testosterone', 'nandrolone', 'trenbolone', 'boldenone', 'stanozolol',
        'oxandrolone', 'methandrostenolone', 'oxymetholone', 'drostanolone',
        'methenolone', 'fluoxymesterone', 'trestolone', 'mesterolone',
        'clostebol', 'epitestosterone', 'methyltestosterone', 'halotestin',
        'superdrol', 'methasterone', 'dimethyltrienolone',
        # SARMs / selective modulators
        'ostarine', 'ligandrol', 'lgd4033', 'lgd-4033', 'rad-140',
        'andarine', 'yk11', 'gw501516', 'cardarine', 'sr9009', 'ibutamoren',
        'mk677', 'mk-677', 'enobosarm', 'ac-262',
        # GH axis / secretagogues
        'ipamorelin', 'sermorelin', 'hexarelin', 'ghrp', 'cjc-1295',
        'tesamorelin', 'igf-1', 'aod-9604',
        # Repair / tissue peptides
        'bpc-157', 'tb-500', 'thymosin', 'ghk-cu',
        # Estrogen modulators
        'anastrozole', 'letrozole', 'exemestane', 'tamoxifen', 'clomiphene',
        'raloxifene', 'fulvestrant', 'toremifene', 'enclomiphene',
        # Ancillaries
        'cabergoline', 'bromocriptine',
        # Nootropics / racetams / peptide cognitives
        'piracetam', 'aniracetam', 'oxiracetam', 'pramiracetam', 'noopept',
        'phenylpiracetam', 'modafinil', 'armodafinil', 'huperzine',
        'vinpocetine', 'citicoline', 'alpha-gpc', 'semax', 'selank',
        'cerebrolysin', 'epitalon', 'epithalon', 'dsip', 'thymalin',
        # Sleep / circadian
        'melatonin', 'ramelteon', 'agomelatine', 'phenibut',
        # Psychedelics
        'psilocybin', 'psilocin', 'psilocybine', '5-meo-dmt', 'mescaline',
        'ibogaine', 'dmt', 'lsd',
        # Dissociatives / empathogens
        'mdma', 'ketamine', 'esketamine', 'memantine',
        # Stimulants
        'clenbuterol', 'ephedrine', 'yohimbine', 'caffeine', 'theobromine',
        # Longevity
        'nicotinamide riboside', 'nicotinamide mononucleotide', 'berberine',
        'resveratrol', 'pterostilbene', 'quercetin', 'curcumin',
        'rapamycin', 'sirolimus', 'everolimus',
        # Metabolic / GLP-1
        'semaglutide', 'liraglutide', 'tirzepatide',
        # Cardiovascular / ED
        'sildenafil', 'tadalafil', 'vardenafil',
        # Adaptogens
        'ashwagandha', 'rhodiola', 'ginseng',
    ]

    def get_context_data(self, **kwargs):
        from django.db.models import Q
        from compounds.models import Compound

        ctx = super().get_context_data(**kwargs)

        # ── Compound IDs from user's own stacks (always include) ──────────────
        user_compound_ids = set(
            StackItem.objects.filter(stack__user=self.request.user)
            .values_list('compound_id', flat=True)
        )

        # ── Compound IDs matched by target keywords ────────────────────────────
        target_q = Q()
        for kw in self._TARGET_KEYWORDS:
            target_q |= Q(mechanism_of_action__target_name__name__icontains=kw)

        # ── Compound IDs matched by category keywords ─────────────────────────
        cat_q = Q()
        for kw in self._CATEGORY_KEYWORDS:
            cat_q |= Q(categories__name__icontains=kw)

        # ── Compound IDs matched by explicit name keywords ────────────────────
        name_q = Q()
        for kw in self._NAME_KEYWORDS:
            name_q |= Q(name__icontains=kw)

        matched_ids = set(
            Compound.objects.filter(target_q | cat_q | name_q)
            .distinct()
            .values_list('pk', flat=True)
        )

        all_ids = user_compound_ids | matched_ids

        compounds_qs = (
            Compound.objects.filter(pk__in=all_ids)
            .prefetch_related(
                'categories',
                'mechanism_of_action__target_name',
                'taxonomy_tags',
            )
            .select_related('steroid_ratings', 'safety_screening')
            .order_by('name')
        )

        compounds_data = []

        for c in compounds_qs:
            cats = [cat.name for cat in c.categories.all()]

            rating = getattr(c, 'steroid_ratings', None)
            safety = getattr(c, 'safety_screening', None)

            anabolic = float(rating.anabolic_rating) if (rating and rating.anabolic_rating is not None) else 0
            androgenic = float(rating.androgenic_rating) if (rating and rating.androgenic_rating is not None) else 0

            estrogenic = 0
            progestogenic = 0
            mechanisms_list = []
            for moa in c.mechanism_of_action.all():
                target = moa.target_name
                t_name = target.name.lower() if target else ''
                action = (moa.target_interaction or '').lower()
                if target:
                    mechanisms_list.append(
                        f"{target.name}|{action}" if action else target.name
                    )
                if 'estrogen' in t_name:
                    estrogenic = max(estrogenic, 50) if 'agonist' in action else min(estrogenic, -30)
                if 'progesterone' in t_name or 'progestin' in t_name:
                    if 'agonist' in action:
                        progestogenic = max(progestogenic, 50)

            # Keep this as a centered delta scale where 1 == neutral (0),
            # >1 increases stress, and values below 1 can represent protection.
            hepato      = (float(safety.liver_toxicity)      - 1.0) * 25.0 if (safety and safety.liver_toxicity is not None)      else 0.0
            suppression = (float(safety.hpta_suppression)    - 1.0) * 25.0 if (safety and safety.hpta_suppression is not None)    else 0.0
            cardio      = (float(safety.cardiovascular_risk) - 1.0) * 25.0 if (safety and safety.cardiovascular_risk is not None) else 0.0
            neuro       = (float(safety.neurotoxicity)       - 1.0) * 25.0 if (safety and safety.neurotoxicity is not None)       else 0.0
            kidney      = (float(safety.kidney_toxicity)     - 1.0) * 25.0 if (safety and safety.kidney_toxicity is not None)     else 0.0
            lung        = (float(safety.lung_toxicity)       - 1.0) * 25.0 if (safety and safety.lung_toxicity is not None)       else 0.0
            pancreas    = (float(safety.pancreas_toxicity)   - 1.0) * 25.0 if (safety and safety.pancreas_toxicity is not None)   else 0.0
            bladder     = (float(safety.bladder_toxicity)    - 1.0) * 25.0 if (safety and safety.bladder_toxicity is not None)    else 0.0

            # General safety score (0–100) — composite across all organ/system risk fields.
            # hh classification is deferred to the frontend so it can scale by actual dose.
            safety_score = max(hepato, cardio, neuro, suppression, kidney, lung, pancreas, bladder)

            # DB-precomputed taxonomy sub IDs (from populate_builder_tags)
            db_subs = [t.sub_id for t in c.taxonomy_tags.all()]

            std_dose = float(c.standard_dose) if c.standard_dose else None
            # ester_ratio: fraction of active (free-base) hormone per mg of ester
            # compound.  1.0 for oral / ester-free compounds.
            ester_ratio = float(rating.ester_ratio) if (rating and rating.ester_ratio is not None) else 1.0

            # Test equivalent (mg-eq free testosterone per mg of compound):
            #   anabolic_rating / 100  → potency relative to testosterone at the receptor
            #   × ester_ratio          → fraction that is actually active hormone after
            #                            the ester chain is cleaved in vivo
            # Example: 200 mg Testosterone Enanthate
            #   = 200 × (100/100) × 0.720 = 144 mg-eq free testosterone
            # Example: 200 mg Trenbolone Acetate
            #   = 200 × (500/100) × 0.865 = 865 mg-eq free testosterone
            test_equiv = round((anabolic / 100.0) * ester_ratio, 4) if anabolic > 0 else 0.0

            compounds_data.append({
                'id': c.pk,
                'slug': c.slug,
                'name': c.name,
                'aka': c.aliases or '',
                'views': c.views,
                'dbCats': cats,
                'dbSubs': db_subs,          # pre-computed taxonomy from DB
                'moa': mechanisms_list[:12],
                'defaultDose': std_dose or 100,
                'standardDose': std_dose,   # stored as free-base equivalent mg for AAS
                'esterRatio': ester_ratio,
                'unit': c.standard_dose_unit or 'mg',
                'testEquiv': test_equiv,
                'props': {
                    'anabolic': round(anabolic, 1),
                    'androgenic': round(androgenic, 1),
                    'estrogenic': estrogenic,
                    'progestogenic': progestogenic,
                    'hepato': hepato,
                    'kidney': kidney,
                    'suppression': suppression,
                    'cardio': cardio,
                    'neuro': neuro,
                    'lung': lung,
                    'pancreas': pancreas,
                    'bladder': bladder,
                    'safetyScore': safety_score,
                },
                'notes': (c.description[:200] if c.description else ''),
            })

        ctx['compounds_data'] = compounds_data
        return ctx
