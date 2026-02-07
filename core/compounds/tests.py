from unittest.mock import patch

import hashlib
from io import StringIO
from django.core.management import call_command
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .interaction_engine import canonicalize_mechanism
from .management.commands.import_chembl_interactions import ChEMBLImporter, Command
from .models import (
    Compound,
    CompoundADMETPrediction,
    CompoundTargetInteraction,
    CompoundToCompoundTargetInteraction,
    Target,
)
from .admet_mechanisms import extract_predicted_mechanisms


class CompoundAdmetAiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user", password="pass")
        self.compound = Compound.objects.create(name="Test Compound", smiles="CCO")

    def test_compound_detail_renders_without_prediction(self):
        response = self.client.get(
            reverse("compound_detail", kwargs={"slug": self.compound.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("admet_ai_available", response.context)
        self.assertIn("admet_ai_prediction", response.context)

    def test_compound_search_api_returns_slug(self):
        resp = self.client.get('/api/compounds/compound-search/', data={'q': 'Test', 'limit': 5})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('compounds', data)
        self.assertTrue(any('slug' in c for c in data['compounds']))

    def test_admet_mechanism_label_strips_drugbank_percentile_text(self):
        mechanisms = extract_predicted_mechanisms(
            {"SR-ATAD5_drugbank_approved_percentile": 0.9}
        )
        self.assertEqual(len(mechanisms), 1)
        self.assertNotIn("drugbank approved percentile", mechanisms[0]["label"].lower())

    def test_admet_refresh_requires_login(self):
        url = reverse("compound_admet_ai_refresh", kwargs={"slug": self.compound.slug})
        response = self.client.post(url, {"next": "/"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_molprop_refresh_requires_login(self):
        url = reverse("compound_molprop_refresh", kwargs={"slug": self.compound.slug})
        response = self.client.post(url, {"next": "/"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_admet_refresh_missing_smiles(self):
        self.client.login(username="user", password="pass")
        no_smiles = Compound.objects.create(name="No Smiles", smiles="")
        url = reverse("compound_admet_ai_refresh", kwargs={"slug": no_smiles.slug})
        next_url = reverse("compound_detail", kwargs={"slug": no_smiles.slug})
        response = self.client.post(url, {"next": next_url})
        self.assertEqual(response.status_code, 302)
        self.assertIn("admet=missing_smiles", response["Location"])
        self.assertFalse(CompoundADMETPrediction.objects.filter(compound=no_smiles).exists())

    def test_compound_detail_includes_graphs_when_cached_prediction_exists(self):
        smiles = self.compound.smiles
        CompoundADMETPrediction.objects.create(
            compound=self.compound,
            smiles=smiles,
            smiles_sha256=hashlib.sha256(smiles.encode("utf-8")).hexdigest(),
            model_version="test",
            predictions={
                "DILI": 0.8,
                "Bioavailability_Ma": 0.2,
                "CYP3A4_Veith": 0.5,
                "logP": 3.1,
                "NR-AR": 0.77,
            },
        )
        response = self.client.get(
            reverse("compound_detail", kwargs={"slug": self.compound.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admetAiPredictions")
        self.assertContains(response, "admetAiChartTox")
        self.assertContains(response, "admetAiKeyTable")
        self.assertContains(response, "admetAiChartOrgan")
        self.assertContains(response, "Predicted mechanisms")
        self.assertIn("admet_ai_mechanism_context", response.context)

    @patch("compounds.admet_ai.is_admet_ai_available", return_value=True)
    @patch("compounds.admet_ai.get_admet_ai_version", return_value="test")
    @patch("compounds.admet_ai.predict_admet", return_value={"a": 1.0, "b": "x"})
    def test_admet_refresh_stores_prediction(self, _predict, _version, _available):
        self.client.login(username="user", password="pass")
        url = reverse("compound_admet_ai_refresh", kwargs={"slug": self.compound.slug})
        next_url = reverse("compound_detail", kwargs={"slug": self.compound.slug})
        response = self.client.post(url, {"next": next_url})
        self.assertEqual(response.status_code, 302)
        self.assertIn("admet=ok", response["Location"])

        pred = CompoundADMETPrediction.objects.get(compound=self.compound)
        self.assertEqual(pred.model_version, "test")
        self.assertEqual(pred.predictions.get("a"), 1.0)

    @patch("compounds.molprop.is_molprop_available", return_value=True)
    @patch("compounds.molprop.get_molprop_version", return_value="test")
    @patch("compounds.molprop.predict_molprop", return_value=({"DILI": 0.2}, {"DILI": 0.1}))
    def test_molprop_refresh_stores_prediction(self, _predict, _version, _available):
        from .models import CompoundMolPropPrediction

        self.client.login(username="user", password="pass")
        url = reverse("compound_molprop_refresh", kwargs={"slug": self.compound.slug})
        next_url = reverse("compound_detail", kwargs={"slug": self.compound.slug})
        response = self.client.post(url, {"next": next_url})
        self.assertEqual(response.status_code, 302)
        self.assertIn("molprop=ok", response["Location"])

        pred = CompoundMolPropPrediction.objects.get(compound=self.compound)
        self.assertEqual(pred.model_version, "test")
        self.assertEqual(pred.predictions.get("DILI"), 0.2)
        self.assertEqual(pred.uncertainty.get("DILI"), 0.1)


class CompoundInteractionModelTests(TestCase):
    def setUp(self):
        self.compound_a = Compound.objects.create(name="Compound A")
        self.compound_b = Compound.objects.create(name="Compound B")
        self.target = Target.objects.create(name="Target X")

    def test_get_compound_mechanism_handles_multiple_rows(self):
        CompoundTargetInteraction.objects.create(
            compound=self.compound_a,
            target=self.target,
            mechanism="antagonist",
        )
        CompoundTargetInteraction.objects.create(
            compound=self.compound_a,
            target=self.target,
            mechanism="binder",
        )
        CompoundTargetInteraction.objects.create(
            compound=self.compound_b,
            target=self.target,
            mechanism="inhibitor",
        )

        pair = CompoundToCompoundTargetInteraction.objects.create(
            compound_a=self.compound_a,
            compound_b=self.compound_b,
            target=self.target,
            interaction_type="competitive",
            description="test",
            source="test",
        )

        self.assertEqual(pair.get_compound_a_mechanism(), "antagonist, binder")
        self.assertEqual(pair.get_compound_b_mechanism(), "inhibitor")


class ChemblImportInferenceTests(TestCase):
    def setUp(self):
        self.command = Command()

    def test_target_activity_filtering_affinity_is_target_specific(self):
        importer = ChEMBLImporter()
        activities = [
            {"target_chembl_id": "CHEMBL_T1", "standard_value": "50", "standard_units": "nM"},
            {"target_chembl_id": "CHEMBL_T2", "standard_value": "5000", "standard_units": "nM"},
        ]

        t1_activities = importer.filter_activities_for_target(activities, "CHEMBL_T1")
        missing_activities = importer.filter_activities_for_target(activities, "CHEMBL_MISSING")

        self.assertEqual(importer.calculate_affinity_level(t1_activities), "high")
        self.assertEqual(importer.calculate_affinity_level(missing_activities), "unknown")

    def test_infer_interaction_type_multi_is_deterministic(self):
        type_a, _ = self.command.infer_interaction_type_multi(
            ["substrate", "agonist"],
            ["inhibitor"],
        )
        type_b, _ = self.command.infer_interaction_type_multi(
            ["agonist", "substrate"],
            ["inhibitor"],
        )

        self.assertEqual(type_a, "enzyme_inhibition")
        self.assertEqual(type_a, type_b)

    def test_create_compound_interactions_uses_all_mechanisms(self):
        compound_a = Compound.objects.create(name="Compound Pair A")
        compound_b = Compound.objects.create(name="Compound Pair B")
        target = Target.objects.create(name="Pair Target")

        CompoundTargetInteraction.objects.create(
            compound=compound_a,
            target=target,
            mechanism="agonist",
        )
        CompoundTargetInteraction.objects.create(
            compound=compound_a,
            target=target,
            mechanism="substrate",
        )
        CompoundTargetInteraction.objects.create(
            compound=compound_b,
            target=target,
            mechanism="inhibitor",
        )

        self.command.create_compound_interactions()

        pair = CompoundToCompoundTargetInteraction.objects.get(target=target)
        self.assertEqual(pair.interaction_type, "enzyme_inhibition")
        self.assertIn("agonist", pair.description)
        self.assertIn("substrate", pair.description)
        self.assertIn("inhibitor", pair.description)


class MechanismNormalizationTests(TestCase):
    def test_action_type_priority_over_mechanism_text(self):
        mechanism = canonicalize_mechanism(
            action_type="POSITIVE ALLOSTERIC MODULATOR",
            mechanism_of_action="competitive antagonist",
            notes="Action: POSITIVE ALLOSTERIC MODULATOR",
        )
        self.assertEqual(mechanism, "pam")

    def test_binding_agent_maps_to_binder(self):
        mechanism = canonicalize_mechanism(
            mechanism_of_action="High affinity binding",
        )
        self.assertEqual(mechanism, "binder")

    def test_notes_action_releasing_agent_maps_to_activator(self):
        mechanism = canonicalize_mechanism(
            notes="Mechanism: Dopamine transporter releasing agent; Action: RELEASING AGENT",
        )
        self.assertEqual(mechanism, "activator")

    def test_stabiliser_maps_to_modulator(self):
        mechanism = canonicalize_mechanism(
            mechanism_of_action="Tubulin stabiliser",
        )
        self.assertEqual(mechanism, "modulator")

    def test_degrader_maps_to_inhibitor(self):
        mechanism = canonicalize_mechanism(
            action_type="DEGRADER",
            mechanism_of_action="Estrogen receptor alpha degrader",
        )
        self.assertEqual(mechanism, "inhibitor")


class ReclassifyUnknownMechanismsCommandTests(TestCase):
    def test_reclassify_merges_unique_constraint_collisions(self):
        compound = Compound.objects.create(name="Collision Compound")
        target = Target.objects.create(name="Collision Target")

        existing = CompoundTargetInteraction.objects.create(
            compound=compound,
            target=target,
            mechanism="inhibitor",
            notes="existing inhibitor row",
            source="ChEMBL",
        )
        unknown = CompoundTargetInteraction.objects.create(
            compound=compound,
            target=target,
            mechanism="unknown",
            notes="Mechanism: receptor blocker; Action: INHIBITOR",
            source="ChEMBL",
        )

        call_command("reclassify_unknown_mechanisms", stdout=StringIO())

        self.assertFalse(CompoundTargetInteraction.objects.filter(pk=unknown.pk).exists())
        kept = CompoundTargetInteraction.objects.get(pk=existing.pk)
        self.assertEqual(kept.mechanism, "inhibitor")
        self.assertIn("INHIBITOR", kept.notes)
