from django.contrib.auth.mixins import LoginRequiredMixin

from django.views.generic import TemplateView
from django.http import Http404
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
from .services import (
    annotate_occurrences_taken,
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
        level = min(count, 4)
        bar_height = min(100, count * 20)
        cells.append(
            {
                'date': d,
                'occurrences': day_occurrences,
                'count': count,
                'level': level,
                'bar_height': bar_height,
                'is_today': d == local_today,
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
        return context


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
