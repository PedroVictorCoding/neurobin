from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from compounds.models import Compound
from research.models import ResearchSnippet, SnippetTag, SnippetTagging, ResearchImportJob
from research.importer import PubMedArticle
from research.views import _sanitize_graph_payload


class ResearchUserDeleteRetentionTests(TestCase):
    def test_deleting_user_keeps_snippet_and_tagging_with_null_author_fields(self):
        User = get_user_model()
        author = User.objects.create_user(username="snippet_owner", password="pw")
        compound = Compound.objects.create(name="Retention Test Compound")
        snippet = ResearchSnippet.objects.create(
            title="Retention snippet",
            content="Retention body",
            compound=compound,
            created_by=author,
            visibility="public",
            status="submitted",
        )
        tag = SnippetTag.objects.create(name="retention-tag", color="#123456")
        tagging = SnippetTagging.objects.create(snippet=snippet, tag=tag, tagged_by=author)

        author.delete()

        snippet.refresh_from_db()
        tagging.refresh_from_db()
        self.assertIsNone(snippet.created_by)
        self.assertIsNone(tagging.tagged_by)


class CompoundResearchExplorerTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="explorer", password="StrongPass123!")
        self.compound = Compound.objects.create(name="Primobolan", slug="primobolan")

    @patch("research.views.fetch_pubmed_articles")
    @patch("research.views.search_pubmed_ids")
    def test_explorer_page_renders_compound_scoped_results(self, mock_search_ids, mock_fetch_articles):
        mock_search_ids.return_value = ["123456"]
        mock_fetch_articles.return_value = [
            PubMedArticle(
                pmid="123456",
                title="Primobolan anabolic effects",
                abstract="Effects in skeletal muscle tissue were measured.",
                journal="Test Journal",
                pubdate="2024",
                doi="10.1000/test",
            )
        ]

        response = self.client.get(
            reverse("research:compound_research_explorer", kwargs={"slug": self.compound.slug}),
            {"q": "anabolic effects"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Explore Primobolan Research")
        self.assertContains(response, "Primobolan anabolic effects")
        self.assertContains(response, "Active query")
        self.assertContains(response, "paperUrlConfirmModal")

    def test_save_paper_with_note_creates_research_snippet(self):
        self.client.login(username="explorer", password="StrongPass123!")
        response = self.client.post(
            reverse("research:compound_research_explorer", kwargs={"slug": self.compound.slug}),
            data={
                "action": "save_paper_snippet",
                "paper_title": "Anabolic signaling in primobolan use",
                "paper_pmid": "555555",
                "paper_abstract": "Observed receptor-level response.",
                "paper_journal": "Journal of Testing",
                "paper_pubdate": "2022",
                "paper_doi": "10.1000/abc",
                "user_note": "Important result for downstream pathway discussion.",
            },
        )

        self.assertEqual(response.status_code, 302)
        snippet = ResearchSnippet.objects.get(compound=self.compound, source_url="https://pubmed.ncbi.nlm.nih.gov/555555/")
        self.assertEqual(snippet.created_by, self.user)
        self.assertIn("User Notes", snippet.content)
        self.assertIn("downstream pathway", snippet.content)

    def test_graph_context_endpoint_returns_nodes(self):
        response = self.client.post(
            reverse("research:compound_explorer_graph_context", kwargs={"slug": self.compound.slug}),
            data={
                "query": "anabolic receptor signaling",
                "papers": [
                    {
                        "title": "Androgen receptor modulation in primobolan",
                        "abstract": "Signal transduction and anabolic outcomes.",
                    }
                ],
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("nodes", payload)
        self.assertTrue(len(payload["nodes"]) >= 1)
        self.assertEqual(payload["nodes"][0]["id"], "compound")

    @patch("research.views._generate_gemini_graph_context")
    def test_graph_context_endpoint_returns_implication_edges_from_gemini(self, mock_graph_context):
        self.client.login(username="explorer", password="StrongPass123!")
        mock_graph_context.return_value = {
            "source": "gemini",
            "nodes": [
                {"id": "compound", "label": "Primobolan", "kind": "compound"},
                {"id": "oxidative_stress", "label": "oxidative stress", "kind": "effect"},
            ],
            "edges": [
                {"source": "compound", "target": "oxidative_stress", "relation": "modulates"},
            ],
            "subsearch_terms": ["oxidative stress"],
        }

        response = self.client.post(
            reverse("research:compound_explorer_graph_context", kwargs={"slug": self.compound.slug}),
            data={"query": "oxidative", "papers": []},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "gemini")
        self.assertEqual(payload["edges"][0]["relation"], "modulates")

    def test_url_graph_context_requires_login(self):
        response = self.client.post(
            reverse("research:compound_explorer_url_graph_context", kwargs={"slug": self.compound.slug}),
            data={"url": "https://example.org/paper"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("Login is required", response.json().get("error", ""))

    @patch("research.views._generate_gemini_pdf_graph_context")
    @patch("research.views._resolve_pdf_from_research_url")
    def test_url_graph_context_returns_graph_payload(self, mock_resolve_pdf, mock_generate_pdf_graph):
        self.client.login(username="explorer", password="StrongPass123!")
        mock_resolve_pdf.return_value = {
            "resolved_url": "https://example.org/paper",
            "pdf_url": "https://example.org/paper.pdf",
            "pdf_bytes": b"%PDF-test",
        }
        mock_generate_pdf_graph.return_value = {
            "source": "gemini_pdf",
            "nodes": [
                {"id": "compound", "label": "Primobolan", "kind": "compound"},
                {"id": "oxidative_stress", "label": "oxidative stress", "kind": "effect"},
            ],
            "edges": [
                {"source": "compound", "target": "oxidative_stress", "relation": "modulates"},
            ],
            "subsearch_terms": ["oxidative stress"],
        }

        response = self.client.post(
            reverse("research:compound_explorer_url_graph_context", kwargs={"slug": self.compound.slug}),
            data={
                "url": "https://example.org/paper",
                "query": "oxidative stress",
                "paper_title": "Primobolan signaling paper",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"], "gemini_pdf")
        self.assertEqual(payload["resolved_url"], "https://example.org/paper")
        self.assertEqual(payload["pdf_url"], "https://example.org/paper.pdf")
        self.assertEqual(payload["edges"][0]["relation"], "modulates")


class GraphPayloadSanitizationTests(TestCase):
    def test_sanitize_accepts_implication_triples(self):
        payload = _sanitize_graph_payload(
            "EDARAVONE",
            {
                "triples": [
                    {"source": "EDARAVONE", "predicate": "modulates", "target": "oxidative stress"},
                    {"source": "neuroprotection", "predicate": "mitigates", "target": "oxidative stress"},
                ],
            },
        )

        self.assertIn("nodes", payload)
        self.assertIn("edges", payload)
        self.assertTrue(any(edge["relation"] == "modulates" for edge in payload["edges"]))
        self.assertTrue(any(edge["relation"] == "mitigates" for edge in payload["edges"]))


class ResearchImportQueueSignalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="queue_staff",
            password="StrongPass123!",
            is_staff=True,
        )
        self.compound = Compound.objects.create(name="Queue Test Compound", slug="queue-test-compound")

    @patch("research.signals.run_import_job.apply_async")
    def test_queue_create_dispatches_async_task(self, mock_apply_async):
        with self.captureOnCommitCallbacks(execute=True):
            job = ResearchImportJob.objects.create(
                compound=self.compound,
                requested_by=self.user,
                status="queued",
                max_results=10,
            )

        mock_apply_async.assert_called_once_with(args=[job.id], ignore_result=True)
        self.assertEqual(
            ResearchImportJob.objects.get(id=job.id).status,
            "queued",
        )

    @patch("research.signals.run_import_job.apply_async", side_effect=RuntimeError("broker unavailable"))
    def test_queue_create_survives_dispatch_failure(self, mock_apply_async):
        with self.captureOnCommitCallbacks(execute=True):
            job = ResearchImportJob.objects.create(
                compound=self.compound,
                requested_by=self.user,
                status="queued",
                max_results=10,
            )

        mock_apply_async.assert_called_once_with(args=[job.id], ignore_result=True)
        self.assertTrue(ResearchImportJob.objects.filter(id=job.id, status="queued").exists())
