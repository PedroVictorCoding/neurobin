from datetime import datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from dateutil.relativedelta import relativedelta

from compounds.models import Compound
from compounds.models import CompoundADMETPrediction
from logs.models import IntakeLog
from stacks.models import Stack, StackItem


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
        self.assertContains(resp, 'Caffeine 100.00mg / q1d')

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

    def test_share_page_not_available_for_private_stack(self):
        stack = Stack.objects.create(user=self.owner, name='Secret', visibility='private')
        resp = self.client.get(f'/stacks/share/{stack.id}/')
        self.assertEqual(resp.status_code, 404)
        embed_resp = self.client.get(f'/stacks/share/{stack.id}/embed/')
        self.assertEqual(embed_resp.status_code, 404)

    def test_share_page_available_for_private_stack_owner(self):
        stack = Stack.objects.create(user=self.owner, name='Secret Owner', visibility='private')
        self.client.force_login(self.owner)
        resp = self.client.get(f'/stacks/share/{stack.id}/')
        self.assertEqual(resp.status_code, 200)
        embed_resp = self.client.get(f'/stacks/share/{stack.id}/embed/')
        self.assertEqual(embed_resp.status_code, 200)

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
