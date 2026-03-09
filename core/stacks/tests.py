from datetime import datetime, timedelta
from io import StringIO
from urllib.parse import quote

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from dateutil.relativedelta import relativedelta

from compounds.models import (
    Compound,
    CompoundADMETPrediction,
    CompoundCategories,
    CompoundSafetyScreening,
    CompoundTargetInteraction,
    CompoundTargetInteractionEvidence,
    Target,
)
from logs.models import IntakeLog
from stacks.forms_add_compound import AddCompoundForm
from stacks.models import Stack, StackDangerousPairRule, StackItem
from stacks.risk import STACK_RISK_SCORE_VERSION, get_or_compute_stack_risk
from stacks.trait_engine import grouping_preset_options


class StackSharingAndScheduleTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.owner = User.objects.create_user(username='owner', password='pw')
        self.other = User.objects.create_user(username='other', password='pw')
        self.compound = Compound.objects.create(name='Caffeine')

    def test_public_stack_can_be_copied(self):
        source_stack = Stack.objects.create(user=self.owner, name='Morning', visibility='public')
        StackItem.objects.create(
            stack=source_stack,
            compound=self.compound,
            dosage_amount='100.00',
            dosage_unit='mg',
            time_of_day='night',
            intake_time=timezone.now() + timedelta(hours=1),
            recurrence_interval=1,
            recurrence_unit='daily',
            order=0,
        )

        self.client.force_authenticate(user=self.other)
        resp = self.client.post(f'/api/stacks/public-stack/{source_stack.id}/copy/')
        self.assertEqual(resp.status_code, 201)

        new_stack = Stack.objects.get(user=self.other, copied_from=source_stack)
        self.assertEqual(new_stack.visibility, 'private')
        self.assertEqual(new_stack.items.count(), 1)
        self.assertEqual(new_stack.items.first().compound_id, self.compound.id)
        self.assertEqual(new_stack.items.first().time_of_day, 'night')

    def test_private_stack_is_not_copyable_via_public_endpoint(self):
        private_stack = Stack.objects.create(user=self.owner, name='Private', visibility='private')

        self.client.force_authenticate(user=self.other)
        resp = self.client.post(f'/api/stacks/public-stack/{private_stack.id}/copy/')
        self.assertEqual(resp.status_code, 404)

    def test_schedule_lists_occurrences_for_active_stacks(self):
        now = timezone.now()
        s1 = Stack.objects.create(user=self.other, name='S1', is_active=True, visibility='private')
        s2 = Stack.objects.create(user=self.other, name='S2', is_active=True, visibility='private')

        StackItem.objects.create(
            stack=s1,
            compound=self.compound,
            dosage_amount='50.00',
            dosage_unit='mg',
            intake_time=now + timedelta(hours=1),
            recurrence_interval=1,
            recurrence_unit='daily',
            order=0,
        )
        StackItem.objects.create(
            stack=s2,
            compound=self.compound,
            dosage_amount='25.00',
            dosage_unit='mg',
            intake_time=now + timedelta(hours=2),
            recurrence_interval=1,
            recurrence_unit='daily',
            order=0,
        )

        self.client.force_authenticate(user=self.other)
        resp = self.client.get('/api/stacks/schedule/?days=1&limit=10')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)
        self.assertLess(resp.json()[0]['scheduled_for'], resp.json()[1]['scheduled_for'])

    def test_take_stack_item_creates_intake_log_and_advances(self):
        now = timezone.now()
        stack = Stack.objects.create(user=self.other, name='S', is_active=True, visibility='private')
        item = StackItem.objects.create(
            stack=stack,
            compound=self.compound,
            dosage_amount='75.00',
            dosage_unit='mg',
            time_of_day='morning',
            intake_time=now + timedelta(minutes=1),
            recurrence_interval=1,
            recurrence_unit='daily',
            order=0,
        )

        self.client.force_authenticate(user=self.other)
        resp = self.client.post(f'/api/stacks/stackitem/{item.id}/take/', data={})
        self.assertEqual(resp.status_code, 201)

        item.refresh_from_db()
        self.assertTrue(IntakeLog.objects.filter(user=self.other, compound=self.compound).exists())
        self.assertEqual(IntakeLog.objects.get(user=self.other, compound=self.compound).time_of_day, 'morning')
        self.assertGreater(item.intake_time, now)

    def test_take_status_and_untake_actions_work_for_specific_occurrence(self):
        scheduled_for = timezone.now().replace(microsecond=0)
        stack = Stack.objects.create(user=self.other, name='S', is_active=True, visibility='private')
        item = StackItem.objects.create(
            stack=stack,
            compound=self.compound,
            dosage_amount='75.00',
            dosage_unit='mg',
            intake_time=scheduled_for,
            recurrence_interval=1,
            recurrence_unit='daily',
            order=0,
        )

        self.client.force_authenticate(user=self.other)
        take_resp = self.client.post(
            f'/api/stacks/stackitem/{item.id}/take/',
            data={'scheduled_for': scheduled_for.isoformat(), 'taken_at': scheduled_for.isoformat()},
            format='json',
        )
        self.assertEqual(take_resp.status_code, 201)

        status_resp = self.client.get(
            f'/api/stacks/stackitem/{item.id}/intake_status/?scheduled_for={quote(scheduled_for.isoformat())}'
        )
        self.assertEqual(status_resp.status_code, 200)
        self.assertTrue(status_resp.json()['is_taken'])

        untake_resp = self.client.post(
            f'/api/stacks/stackitem/{item.id}/untake/',
            data={'scheduled_for': scheduled_for.isoformat()},
            format='json',
        )
        self.assertEqual(untake_resp.status_code, 200)
        self.assertEqual(untake_resp.json()['deleted_count'], 1)

        status_resp_after = self.client.get(
            f'/api/stacks/stackitem/{item.id}/intake_status/?scheduled_for={quote(scheduled_for.isoformat())}'
        )
        self.assertEqual(status_resp_after.status_code, 200)
        self.assertFalse(status_resp_after.json()['is_taken'])

    def test_untake_and_intake_status_require_scheduled_for(self):
        stack = Stack.objects.create(user=self.other, name='S', is_active=True, visibility='private')
        item = StackItem.objects.create(
            stack=stack,
            compound=self.compound,
            recurrence_interval=1,
            recurrence_unit='daily',
        )
        self.client.force_authenticate(user=self.other)

        untake_resp = self.client.post(f'/api/stacks/stackitem/{item.id}/untake/', data={}, format='json')
        self.assertEqual(untake_resp.status_code, 400)

        status_resp = self.client.get(f'/api/stacks/stackitem/{item.id}/intake_status/')
        self.assertEqual(status_resp.status_code, 400)

    def test_schedule_can_include_due_items_since_midnight(self):
        now = timezone.now()
        local_now = timezone.localtime(now)
        midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        due_time = midnight + timedelta(hours=max(0, local_now.hour - 1))

        stack = Stack.objects.create(user=self.other, name='S', is_active=True, visibility='private')
        StackItem.objects.create(
            stack=stack,
            compound=self.compound,
            dosage_amount='50.00',
            dosage_unit='mg',
            intake_time=due_time,
            recurrence_interval=1,
            recurrence_unit='daily',
            order=0,
        )

        self.client.force_authenticate(user=self.other)

        resp_upcoming_only = self.client.get('/api/stacks/schedule/?days=1&limit=10')
        self.assertEqual(resp_upcoming_only.status_code, 200)
        self.assertGreaterEqual(len(resp_upcoming_only.json()), 1)

        first_upcoming = resp_upcoming_only.json()[0]['scheduled_for'].replace('Z', '+00:00')
        first_upcoming_dt = datetime.fromisoformat(first_upcoming)
        if timezone.is_naive(first_upcoming_dt):
            first_upcoming_dt = timezone.make_aware(first_upcoming_dt, timezone.get_current_timezone())
        self.assertGreater(first_upcoming_dt, timezone.now())

        resp_with_past = self.client.get('/api/stacks/schedule/?days=1&limit=10&include_past=1')
        self.assertEqual(resp_with_past.status_code, 200)
        self.assertGreaterEqual(len(resp_with_past.json()), 1)

        first = resp_with_past.json()[0]['scheduled_for'].replace('Z', '+00:00')
        first_dt = datetime.fromisoformat(first)
        if timezone.is_naive(first_dt):
            first_dt = timezone.make_aware(first_dt, timezone.get_current_timezone())
        self.assertLessEqual(first_dt, timezone.now())

    def test_take_can_advance_from_scheduled_for_to_prevent_drift(self):
        now = timezone.now()
        local_now = timezone.localtime(now)
        midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        scheduled_for = midnight + timedelta(hours=max(0, local_now.hour - 1))

        stack = Stack.objects.create(user=self.other, name='S', is_active=True, visibility='private')
        item = StackItem.objects.create(
            stack=stack,
            compound=self.compound,
            dosage_amount='75.00',
            dosage_unit='mg',
            time_of_day='morning',
            intake_time=scheduled_for,
            recurrence_interval=1,
            recurrence_unit='daily',
            order=0,
        )

        self.client.force_authenticate(user=self.other)
        resp = self.client.post(
            f'/api/stacks/stackitem/{item.id}/take/',
            data={'scheduled_for': scheduled_for.isoformat(), 'taken_at': now.isoformat()},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)

        item.refresh_from_db()
        expected = scheduled_for + relativedelta(days=1)
        self.assertEqual(item.intake_time, expected)

    def test_take_weekly_frequency_advances_as_times_per_week(self):
        now = timezone.now().replace(microsecond=0)
        stack = Stack.objects.create(user=self.other, name='S', is_active=True, visibility='private')
        item = StackItem.objects.create(
            stack=stack,
            compound=self.compound,
            dosage_amount='75.00',
            dosage_unit='mg',
            intake_time=now,
            recurrence_interval=4,  # 4x/week
            recurrence_unit='weekly',
            order=0,
        )

        self.client.force_authenticate(user=self.other)
        resp = self.client.post(
            f'/api/stacks/stackitem/{item.id}/take/',
            data={'scheduled_for': now.isoformat(), 'taken_at': now.isoformat()},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)

        item.refresh_from_db()
        expected = now + timedelta(days=7 / 4)
        self.assertEqual(item.intake_time, expected)

    def test_recurrence_rate_label_is_rendered_as_frequency(self):
        stack = Stack.objects.create(user=self.other, name='S', is_active=False, visibility='private')
        item = StackItem.objects.create(
            stack=stack,
            compound=self.compound,
            recurrence_interval=4,
            recurrence_unit='weekly',
        )
        self.assertEqual(item.recurrence_rate_label, '4x/week')

    def test_calendar_graph_view_page_renders(self):
        Stack.objects.create(user=self.other, name='S', is_active=True, visibility='private')
        self.client.force_login(self.other)
        resp = self.client.get('/stacks/calendar/?period=month')
        self.assertEqual(resp.status_code, 200)

    def test_calendar_graph_view_can_take_item(self):
        now = timezone.now()
        stack = Stack.objects.create(user=self.other, name='S', is_active=True, visibility='private')
        item = StackItem.objects.create(
            stack=stack,
            compound=self.compound,
            dosage_amount='50.00',
            dosage_unit='mg',
            intake_time=now,
            recurrence_interval=1,
            recurrence_unit='daily',
            order=0,
        )

        self.client.force_login(self.other)
        resp = self.client.post(
            '/stacks/calendar/',
            data={
                'period': 'month',
                'stack_item_id': str(item.id),
                'scheduled_for': now.isoformat(),
                'take_stack_item': '1',
            },
        )
        self.assertEqual(resp.status_code, 302)
        log = IntakeLog.objects.get(user=self.other, compound=self.compound)
        self.assertEqual(log.stack_item_id, item.id)
        self.assertIsNotNone(log.scheduled_for)

        item.refresh_from_db()
        resp2 = self.client.get('/stacks/calendar/?period=month')
        self.assertEqual(resp2.status_code, 200)
        calendar = resp2.context['calendar']
        found = False
        for week in calendar['weeks']:
            for cell in week:
                for o in cell['occurrences']:
                    if o.stack_item_id == item.id and o.is_taken:
                        found = True
                        break
                if found:
                    break
            if found:
                break
        self.assertTrue(found)

        resp3 = self.client.post(
            '/stacks/calendar/',
            data={
                'period': 'month',
                'stack_item_id': str(item.id),
                'scheduled_for': now.replace(microsecond=0).isoformat(),
                'untake_stack_item': '1',
            },
        )
        self.assertEqual(resp3.status_code, 302)
        self.assertFalse(IntakeLog.objects.filter(user=self.other, stack_item_id=item.id, scheduled_for__isnull=False).exists())


    def test_share_page_has_redirect_to_stack_detail_and_embed_description(self):
        stack = Stack.objects.create(user=self.owner, name='Share Me', visibility='public')
        StackItem.objects.create(
            stack=stack,
            compound=self.compound,
            dosage_amount='100.00',
            dosage_unit='mg',
            recurrence_interval=1,
            recurrence_unit='daily',
            order=0,
        )

        resp = self.client.get(f'/stacks/share/{stack.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'url=http://testserver/stacks/{stack.id}/')
        self.assertContains(resp, 'Caffeine 100.00mg / 1x/day')

    def test_owner_can_delete_stackitem_via_api(self):
        stack = Stack.objects.create(user=self.other, name='S', is_active=False, visibility='private')
        item = StackItem.objects.create(stack=stack, compound=self.compound, recurrence_interval=1, recurrence_unit='daily')

        self.client.force_authenticate(user=self.other)
        resp = self.client.delete(f'/api/stacks/stackitem/{item.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(StackItem.objects.filter(id=item.id).exists())

    def test_owner_can_delete_stack_via_api(self):
        stack = Stack.objects.create(user=self.other, name='S', is_active=False, visibility='private')
        self.client.force_authenticate(user=self.other)
        resp = self.client.delete(f'/api/stacks/stack/{stack.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Stack.objects.filter(id=stack.id).exists())

    def test_explore_shows_all_public_and_ranks_by_usage(self):
        own_public = Stack.objects.create(user=self.other, name='Own Public', visibility='public')
        high_usage = Stack.objects.create(user=self.owner, name='High Usage', visibility='public')
        medium_usage = Stack.objects.create(user=self.owner, name='Medium Usage', visibility='public')
        low_usage = Stack.objects.create(user=self.owner, name='Low Usage', visibility='public')

        Stack.objects.create(user=self.other, name='copy1', visibility='private', copied_from=high_usage)
        Stack.objects.create(user=self.other, name='copy2', visibility='private', copied_from=high_usage)
        Stack.objects.create(user=self.other, name='copy3', visibility='private', copied_from=medium_usage)

        self.client.force_login(self.other)
        resp = self.client.get('/stacks/explore/')
        self.assertEqual(resp.status_code, 200)

        public_names = [s.name for s in resp.context['public_stacks']]
        self.assertIn('Own Public', public_names)
        self.assertEqual(
            public_names[:4],
            ['High Usage', 'Medium Usage', 'Low Usage', 'Own Public'],
        )

    def test_share_page_renders_for_public_stack(self):
        stack = Stack.objects.create(user=self.owner, name='Shared Public', visibility='public')
        StackItem.objects.create(stack=stack, compound=self.compound, recurrence_interval=1, recurrence_unit='daily')
        resp = self.client.get(f'/stacks/share/{stack.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Shared Public')
        self.assertContains(resp, self.compound.name)
        embed_resp = self.client.get(f'/stacks/share/{stack.id}/embed/')
        self.assertEqual(embed_resp.status_code, 200)
        self.assertContains(embed_resp, 'Shared Public')

    def test_share_image_renders_for_public_stack(self):
        stack = Stack.objects.create(user=self.owner, name='Clipboard Ready', visibility='public')
        StackItem.objects.create(
            stack=stack,
            compound=self.compound,
            dosage_amount='100.00',
            dosage_unit='mg',
            recurrence_interval=1,
            recurrence_unit='daily',
        )

        resp = self.client.get(f'/stacks/share/{stack.id}/image.svg')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/svg+xml')
        self.assertIn('Clipboard Ready', resp.content.decode('utf-8'))
        self.assertIn('Caffeine', resp.content.decode('utf-8'))

    def test_share_page_not_available_for_private_stack(self):
        stack = Stack.objects.create(user=self.owner, name='Secret', visibility='private')
        resp = self.client.get(f'/stacks/share/{stack.id}/')
        self.assertEqual(resp.status_code, 404)
        embed_resp = self.client.get(f'/stacks/share/{stack.id}/embed/')
        self.assertEqual(embed_resp.status_code, 404)
        image_resp = self.client.get(f'/stacks/share/{stack.id}/image.svg')
        self.assertEqual(image_resp.status_code, 404)

    def test_share_page_available_for_private_stack_owner(self):
        stack = Stack.objects.create(user=self.owner, name='Secret Owner', visibility='private')
        self.client.force_login(self.owner)
        resp = self.client.get(f'/stacks/share/{stack.id}/')
        self.assertEqual(resp.status_code, 200)
        embed_resp = self.client.get(f'/stacks/share/{stack.id}/embed/')
        self.assertEqual(embed_resp.status_code, 200)
        image_resp = self.client.get(f'/stacks/share/{stack.id}/image.svg')
        self.assertEqual(image_resp.status_code, 200)

    def test_stack_detail_shows_risk_assessment_when_predictions_exist(self):
        stack = Stack.objects.create(user=self.other, name='Risky', visibility='private')
        StackItem.objects.create(stack=stack, compound=self.compound, recurrence_interval=1, recurrence_unit='daily')

        CompoundADMETPrediction.objects.create(
            compound=self.compound,
            smiles="",
            smiles_sha256="0" * 64,
            model_version="test",
            predictions={"DILI": 0.8, "Bioavailability_Ma": 0.2, "CYP3A4_Veith": 0.6},
        )

        self.client.force_login(self.other)
        resp = self.client.get(f'/stacks/{stack.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Risk Assessment')
        self.assertContains(resp, 'Risk:')

    def test_stack_detail_can_rename_stack(self):
        stack = Stack.objects.create(user=self.other, name='Original', visibility='private')

        self.client.force_login(self.other)
        resp = self.client.post(
            f'/stacks/{stack.id}/',
            data={'update_stack_name': '1', 'name': 'Renamed Stack'},
        )

        self.assertRedirects(resp, f'/stacks/{stack.id}/')
        stack.refresh_from_db()
        self.assertEqual(stack.name, 'Renamed Stack')

    def test_stack_risk_refresh_computes_missing_compound_predictions(self):
        compound2 = Compound.objects.create(name='Compound2', smiles='CCO')
        stack = Stack.objects.create(user=self.other, name='AutoRisk', visibility='private')
        StackItem.objects.create(stack=stack, compound=compound2, recurrence_interval=1, recurrence_unit='daily')

        self.client.force_login(self.other)

        from unittest.mock import patch

        with patch('compounds.admet_ai.is_admet_ai_available', return_value=True), patch(
            'compounds.admet_ai.get_admet_ai_version', return_value='test'
        ), patch('compounds.admet_ai.predict_admet', return_value={'DILI': 0.9, 'Bioavailability_Ma': 0.2}):
            resp = self.client.post(f'/stacks/{stack.id}/risk/refresh/', data={'next': f'/stacks/{stack.id}/'})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CompoundADMETPrediction.objects.filter(compound=compound2).exists())

    def test_stack_detail_does_not_autoload_risk_refresh_while_editing_or_after_attempt(self):
        compound2 = Compound.objects.create(name='Compound3', smiles='CCO')
        stack = Stack.objects.create(user=self.other, name='AutoRiskGuard', visibility='private')
        item = StackItem.objects.create(
            stack=stack,
            compound=compound2,
            recurrence_interval=1,
            recurrence_unit='daily',
        )
        self.client.force_login(self.other)

        from unittest.mock import patch

        with patch('compounds.admet_ai.is_admet_ai_available', return_value=True), patch(
            'compounds.molprop.is_molprop_available', return_value=False
        ):
            resp_edit = self.client.get(f'/stacks/{stack.id}/?edit={item.id}')
            self.assertEqual(resp_edit.status_code, 200)
            self.assertNotContains(resp_edit, 'id="stackRiskRefreshForm"')

            resp_normal = self.client.get(f'/stacks/{stack.id}/')
            self.assertEqual(resp_normal.status_code, 200)
            self.assertContains(resp_normal, 'id="stackRiskRefreshForm"')

            resp_attempted = self.client.get(f'/stacks/{stack.id}/?risk_autoload=1')
            self.assertEqual(resp_attempted.status_code, 200)
            self.assertNotContains(resp_attempted, 'id="stackRiskRefreshForm"')


class AddCompoundFormTests(TestCase):
    def setUp(self):
        self.compound = Compound.objects.create(name='Timed Compound')

    def test_intake_clock_saves_as_next_datetime_with_matching_clock_time(self):
        form = AddCompoundForm(
            data={
                'compound': str(self.compound.id),
                'dosage_amount': '',
                'dosage_unit': 'mg',
                'time_of_day': '',
                'intake_clock': '08:30',
                'recurrence_interval': '1',
                'recurrence_unit': 'daily',
                'notes': '',
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        item = form.save(commit=False)
        self.assertIsNotNone(item.intake_time)
        self.assertEqual(item.intake_time.hour, 8)
        self.assertEqual(item.intake_time.minute, 30)
        self.assertTrue(timezone.is_aware(item.intake_time))


class StackRiskScoringTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='risk_user', password='pw')
        self.compound_high = Compound.objects.create(name='High Signal')
        self.compound_low = Compound.objects.create(name='Low Signal')

    def test_stack_risk_uses_conservative_log_scaled_aggregation(self):
        stack = Stack.objects.create(user=self.user, name='Tempered Risk', visibility='private')
        StackItem.objects.create(stack=stack, compound=self.compound_high, recurrence_interval=1, recurrence_unit='daily')
        StackItem.objects.create(stack=stack, compound=self.compound_low, recurrence_interval=1, recurrence_unit='daily')

        CompoundADMETPrediction.objects.create(
            compound=self.compound_high,
            smiles='',
            smiles_sha256='1' * 64,
            model_version='test',
            predictions={'DILI': 0.9},
        )
        CompoundADMETPrediction.objects.create(
            compound=self.compound_low,
            smiles='',
            smiles_sha256='2' * 64,
            model_version='test',
            predictions={'DILI': 0.2},
        )

        result = get_or_compute_stack_risk(stack, items=list(stack.items.select_related('compound')))

        self.assertEqual(result.assessment.risk_level, 'moderate')
        self.assertLess(result.assessment.risk_score or 0.0, 0.5)
        self.assertEqual(
            result.assessment.details.get('summary', {}).get('score_model_version'),
            STACK_RISK_SCORE_VERSION,
        )

    def test_outdated_cached_risk_is_recomputed_under_new_score_version(self):
        stack = Stack.objects.create(user=self.user, name='Needs Refresh', visibility='private')
        StackItem.objects.create(stack=stack, compound=self.compound_high, recurrence_interval=1, recurrence_unit='daily')

        CompoundADMETPrediction.objects.create(
            compound=self.compound_high,
            smiles='',
            smiles_sha256='3' * 64,
            model_version='test',
            predictions={'DILI': 0.95},
        )

        first = get_or_compute_stack_risk(stack, items=list(stack.items.select_related('compound')))
        self.assertTrue(first.computed)

        outdated_details = dict(first.assessment.details)
        outdated_summary = dict(outdated_details.get('summary', {}))
        outdated_summary.pop('score_model_version', None)
        outdated_details['summary'] = outdated_summary
        first.assessment.details = outdated_details
        first.assessment.save(update_fields=['details'])

        refreshed = get_or_compute_stack_risk(stack, items=list(stack.items.select_related('compound')))

        self.assertTrue(refreshed.computed)
        self.assertEqual(
            refreshed.assessment.details.get('summary', {}).get('score_model_version'),
            STACK_RISK_SCORE_VERSION,
        )


class StackTraitRecommendationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username='trait_user', password='pw')
        self.client.force_authenticate(user=self.user)

        call_command('sync_stack_trait_defaults', stdout=StringIO())

        self.compound_ampk = Compound.objects.create(name='AMPK Activator X')
        self.compound_ar = Compound.objects.create(name='AR Agonist Y')
        self.compound_gaba = Compound.objects.create(name='GABA Agent Z')
        self.target_ampk = Target.objects.create(name='AMPK alpha 1')
        self.target_ar = Target.objects.create(name='Androgen receptor')
        self.target_gaba = Target.objects.create(name='GABA-A receptor alpha 1')

        CompoundTargetInteractionEvidence.objects.create(
            compound=self.compound_ampk,
            target=self.target_ampk,
            source='IUPHAR',
            source_record_id='AMPK-1',
            evidence_uid='ev_ampk_1',
            canonical_mechanism='activator',
            evidence_level='high',
            evidence_weight=1.0,
            context_key='ctx::human::oral',
            species='Homo sapiens',
            route='oral',
        )
        CompoundTargetInteractionEvidence.objects.create(
            compound=self.compound_ar,
            target=self.target_ar,
            source='IUPHAR',
            source_record_id='AR-1',
            evidence_uid='ev_ar_1',
            canonical_mechanism='agonist',
            evidence_level='high',
            evidence_weight=1.0,
            context_key='ctx::human::oral',
            species='Homo sapiens',
            route='oral',
        )
        CompoundTargetInteractionEvidence.objects.create(
            compound=self.compound_gaba,
            target=self.target_gaba,
            source='IUPHAR',
            source_record_id='GABA-1',
            evidence_uid='ev_gaba_1',
            canonical_mechanism='agonist',
            evidence_level='medium',
            evidence_weight=0.9,
            context_key='ctx::human::oral',
            species='Homo sapiens',
            route='oral',
        )

    def test_recommend_api_returns_character_sheet_and_disclaimer(self):
        resp = self.client.post(
            '/api/stacks/recommend/',
            data={
                'goals': {'longevity': 1.0, 'anabolism': 1.0},
                'constraints': {'max_traits': {'cardio_risk': 3.0}},
                'candidate_compound_ids': [
                    self.compound_ampk.id,
                    self.compound_ar.id,
                    self.compound_gaba.id,
                ],
                'max_stack_size': 2,
                'beam_width': 8,
                'top_k': 3,
                'min_evidence_confidence': 'medium',
                'desired_context': {'route': 'oral'},
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn('not medical advice', body.get('disclaimer', '').lower())
        self.assertGreaterEqual(len(body.get('recommendations', [])), 1)
        first = body['recommendations'][0]
        self.assertIn('character_sheet', first)
        self.assertIn('traits', first['character_sheet'])
        self.assertGreater(len(first['character_sheet']['traits']), 0)

    def test_curated_dangerous_pair_rule_blocks_combo(self):
        a_id = min(self.compound_ampk.id, self.compound_ar.id)
        b_id = max(self.compound_ampk.id, self.compound_ar.id)
        StackDangerousPairRule.objects.create(
            compound_a_id=a_id,
            compound_b_id=b_id,
            severity='critical',
            reason='Known unsafe pair for test',
            source='unit-test',
            is_active=True,
        )

        resp = self.client.post(
            '/api/stacks/recommend/',
            data={
                'goals': {'longevity': 1.0, 'anabolism': 1.0},
                'candidate_compound_ids': [self.compound_ampk.id, self.compound_ar.id],
                'max_stack_size': 2,
                'top_k': 5,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        recs = resp.json().get('recommendations', [])
        for rec in recs:
            rec_ids = {item['id'] for item in rec.get('compounds', [])}
            self.assertFalse({self.compound_ampk.id, self.compound_ar.id}.issubset(rec_ids))

    def test_recommend_get_analyzes_user_stack(self):
        stack = Stack.objects.create(user=self.user, name='Trait Stack', visibility='private')
        StackItem.objects.create(stack=stack, compound=self.compound_ampk, recurrence_interval=1, recurrence_unit='daily')

        resp = self.client.get(f'/api/stacks/recommend/?stack_id={stack.id}')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body.get('stack_id'), stack.id)
        self.assertIn('character_sheet', body)
        self.assertIn('traits', body['character_sheet'])

    def test_recommend_command_outputs_json(self):
        out = StringIO()
        call_command(
            'recommend_stacks',
            goal=['longevity=1.0'],
            candidate_id=[self.compound_ampk.id],
            top_k=1,
            json=True,
            stdout=out,
        )
        self.assertIn('"recommendations"', out.getvalue())

    def test_post_recommend_with_stack_id_uses_stack_as_base(self):
        stack = Stack.objects.create(user=self.user, name='Base Stack', visibility='private')
        StackItem.objects.create(stack=stack, compound=self.compound_ampk, recurrence_interval=1, recurrence_unit='daily')

        resp = self.client.post(
            '/api/stacks/recommend/',
            data={
                'stack_id': stack.id,
                'goals': {'anabolism': 1.0},
                'candidate_compound_ids': [self.compound_ar.id, self.compound_ampk.id],
                'max_stack_size': 1,
                'top_k': 2,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['meta']['base_compound_count'], 1)
        for rec in body.get('recommendations', []):
            add_ids = {row['id'] for row in rec.get('compounds', [])}
            self.assertNotIn(self.compound_ampk.id, add_ids)
            full_ids = {row['id'] for row in rec.get('full_stack_compounds', [])}
            self.assertIn(self.compound_ampk.id, full_ids)

    def test_recommend_can_filter_candidates_by_focus_group(self):
        resp = self.client.post(
            '/api/stacks/recommend/',
            data={
                'goals': {'anabolism': 1.0},
                'constraints': {
                    'focus_groups': ['ar'],
                    'min_group_score': 0.5,
                },
                'candidate_compound_ids': [
                    self.compound_ampk.id,
                    self.compound_ar.id,
                    self.compound_gaba.id,
                ],
                'min_evidence_confidence': 'low',
                'max_stack_size': 1,
                'top_k': 3,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        recs = resp.json().get('recommendations', [])
        self.assertGreaterEqual(len(recs), 1)
        for rec in recs:
            added_ids = {row['id'] for row in rec.get('compounds', [])}
            self.assertEqual(added_ids, {self.compound_ar.id})

    def test_recommend_payload_exposes_group_signal_metadata(self):
        resp = self.client.post(
            '/api/stacks/recommend/',
            data={
                'goals': {'anabolism': 1.0},
                'constraints': {'focus_groups': ['anabolism_ar'], 'min_group_score': 0.2},
                'candidate_compound_ids': [self.compound_ar.id],
                'min_evidence_confidence': 'low',
                'max_stack_size': 1,
                'top_k': 1,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        recs = resp.json().get('recommendations', [])
        self.assertGreaterEqual(len(recs), 1)
        added = recs[0]['compounds'][0]
        self.assertIn('group_signals', added)
        self.assertTrue(any(row.get('slug') == 'anabolism_ar' for row in added['group_signals']))

    def test_stack_detail_selector_toggles_drive_recommendations(self):
        stack = Stack.objects.create(user=self.user, name='Selector Stack', visibility='private')
        StackItem.objects.create(
            stack=stack,
            compound=self.compound_ampk,
            recurrence_interval=1,
            recurrence_unit='daily',
        )
        self.client.force_login(self.user)

        resp = self.client.post(
            f'/stacks/{stack.id}/',
            data={
                'recommend_stack_additions': '1',
                'focus_group_anabolism_ar': 'on',
                'min_group_score': '0.2',
                'min_confidence': 'low',
                'max_stack_size': '1',
                'top_k': '3',
                'beam_width': '8',
            },
        )
        self.assertEqual(resp.status_code, 200)
        result = resp.context['stack_recommendation_result']
        self.assertIsNotNone(result)
        recs = result.get('recommendations', [])
        self.assertGreaterEqual(len(recs), 1)
        first_ids = {row['id'] for row in recs[0].get('compounds', [])}
        self.assertIn(self.compound_ar.id, first_ids)

    def test_grouping_presets_cover_requested_trait_categories(self):
        trait_slugs = {row.get('trait_slug') for row in grouping_preset_options()}
        self.assertTrue(
            {
                'anabolism',
                'longevity',
                'sleep',
                'cognition',
                'anti_inflammatory',
                'metabolic_health',
                'anxiety_relief',
                'oncoprotection_hypothesis',
            }.issubset(trait_slugs)
        )

    def test_category_labeled_compound_is_counted_for_focus_group(self):
        labeled = Compound.objects.create(name='Longevity Label Only')
        category = CompoundCategories.objects.create(name='Longevity - AMPK')
        labeled.categories.add(category)

        resp = self.client.post(
            '/api/stacks/recommend/',
            data={
                'goals': {'longevity': 1.0},
                'constraints': {'focus_groups': ['longevity_ampk'], 'min_group_score': 0.5},
                'candidate_compound_ids': [labeled.id],
                'min_evidence_confidence': 'high',
                'max_stack_size': 1,
                'top_k': 1,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        recs = resp.json().get('recommendations', [])
        self.assertGreaterEqual(len(recs), 1)
        ids = {row['id'] for row in recs[0].get('compounds', [])}
        self.assertEqual(ids, {labeled.id})

    def test_recommendation_payload_includes_evidence_profile_and_radar(self):
        resp = self.client.post(
            '/api/stacks/recommend/',
            data={
                'goals': {'longevity': 1.0},
                'candidate_compound_ids': [self.compound_ampk.id],
                'min_evidence_confidence': 'low',
                'max_stack_size': 1,
                'top_k': 1,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        recs = resp.json().get('recommendations', [])
        self.assertGreaterEqual(len(recs), 1)
        rec = recs[0]
        self.assertIn('evidence_profile', rec)
        self.assertIn('posterior_confidence', rec['evidence_profile'])
        self.assertIn('contradiction_radar', rec)
        self.assertIn('rows', rec['contradiction_radar'])

    def test_recommend_cloud_mode_returns_distribution_points(self):
        resp = self.client.post(
            '/api/stacks/recommend/',
            data={
                'goals': {'longevity': 1.0, 'anabolism': 1.0},
                'candidate_compound_ids': [
                    self.compound_ampk.id,
                    self.compound_ar.id,
                    self.compound_gaba.id,
                ],
                'output_mode': 'cloud',
                'max_stack_size': 1,
                'top_k': 2,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['meta']['output_mode'], 'cloud')
        self.assertTrue(body['meta']['distribution_included'])
        distribution = body.get('distribution') or {}
        self.assertEqual(distribution.get('mode'), 'compound_cloud')
        self.assertGreaterEqual(distribution.get('point_count', 0), 1)
        first = (distribution.get('points') or [])[0]
        self.assertIn('goal_score', first)
        self.assertIn('risk_load', first)
        self.assertIn('net_score', first)

    def test_contradiction_radar_detects_opposed_mechanisms_on_same_target(self):
        conflict_compound = Compound.objects.create(name='Conflict Molecule Q')
        target = Target.objects.create(name='Dopamine receptor D2')
        CompoundTargetInteractionEvidence.objects.create(
            compound=conflict_compound,
            target=target,
            source='IUPHAR',
            source_record_id='CONFLICT-1',
            evidence_uid='ev_conflict_1',
            canonical_mechanism='agonist',
            evidence_level='high',
            evidence_weight=1.0,
            context_key='ctx::human::oral',
            species='Homo sapiens',
            route='oral',
        )
        CompoundTargetInteractionEvidence.objects.create(
            compound=conflict_compound,
            target=target,
            source='BindingDB',
            source_record_id='CONFLICT-2',
            evidence_uid='ev_conflict_2',
            canonical_mechanism='antagonist',
            evidence_level='high',
            evidence_weight=1.0,
            context_key='ctx::human::oral',
            species='Homo sapiens',
            route='oral',
        )

        resp = self.client.post(
            '/api/stacks/recommend/',
            data={
                'goals': {'cognition': 1.0},
                'candidate_compound_ids': [conflict_compound.id],
                'min_evidence_confidence': 'low',
                'max_stack_size': 1,
                'top_k': 1,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        recs = resp.json().get('recommendations', [])
        self.assertGreaterEqual(len(recs), 1)
        evidence_profile = recs[0].get('evidence_profile') or {}
        self.assertGreater(float(evidence_profile.get('contradiction_index') or 0.0), 0.0)
        radar_rows = (recs[0].get('contradiction_radar') or {}).get('rows') or []
        self.assertTrue(any((row.get('target') or '') == target.name for row in radar_rows))

    def test_legacy_interaction_fallback_scores_anabolism_when_evidence_missing(self):
        legacy_compound = Compound.objects.create(name='Legacy Testosterone Enanthate')
        CompoundTargetInteraction.objects.create(
            compound=legacy_compound,
            target=self.target_ar,
            mechanism='agonist',
            source='legacy-fixture',
        )

        resp = self.client.post(
            '/api/stacks/recommend/',
            data={
                'goals': {'anabolism': 1.0},
                'candidate_compound_ids': [legacy_compound.id],
                'min_evidence_confidence': 'low',
                'max_stack_size': 1,
                'top_k': 1,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        recs = resp.json().get('recommendations', [])
        self.assertGreaterEqual(len(recs), 1)
        traits = recs[0].get('character_sheet', {}).get('traits', [])
        anabolism = next((row for row in traits if row.get('slug') == 'anabolism'), None)
        self.assertIsNotNone(anabolism)
        self.assertGreater(float(anabolism['score']), 0.0)

    def test_androgenic_name_heuristic_is_low_confidence_and_respects_confidence_floor(self):
        heuristic_compound = Compound.objects.create(name='METHENOLONE ENANTHATE Heuristic')

        low_resp = self.client.post(
            '/api/stacks/recommend/',
            data={
                'goals': {'anabolism': 1.0},
                'candidate_compound_ids': [heuristic_compound.id],
                'min_evidence_confidence': 'low',
                'max_stack_size': 1,
                'top_k': 1,
            },
            format='json',
        )
        self.assertEqual(low_resp.status_code, 200)
        low_recs = low_resp.json().get('recommendations', [])
        self.assertGreaterEqual(len(low_recs), 1)
        low_traits = low_recs[0].get('character_sheet', {}).get('traits', [])
        low_anabolism = next((row for row in low_traits if row.get('slug') == 'anabolism'), None)
        self.assertIsNotNone(low_anabolism)
        self.assertGreater(float(low_anabolism['score']), 0.0)

        high_resp = self.client.post(
            '/api/stacks/recommend/',
            data={
                'goals': {'anabolism': 1.0},
                'candidate_compound_ids': [heuristic_compound.id],
                'min_evidence_confidence': 'high',
                'max_stack_size': 1,
                'top_k': 1,
            },
            format='json',
        )
        self.assertEqual(high_resp.status_code, 200)
        high_recs = high_resp.json().get('recommendations', [])
        self.assertEqual(high_recs, [])


class StackBuilderViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='builder', password='pw')

    def test_builder_allows_negative_safety_deltas_in_compound_props(self):
        compound = Compound.objects.create(name='Builder Renal Compound')
        CompoundSafetyScreening.objects.create(compound=compound, kidney_toxicity=0)
        stack = Stack.objects.create(user=self.user, name='Builder Stack')
        StackItem.objects.create(stack=stack, compound=compound)

        self.client.force_login(self.user)
        resp = self.client.get('/stacks/builder/')
        self.assertEqual(resp.status_code, 200)

        payload = resp.context['compounds_data']
        row = next((entry for entry in payload if entry['id'] == compound.id), None)
        self.assertIsNotNone(row)
        self.assertEqual(row['props']['kidney'], -25.0)
