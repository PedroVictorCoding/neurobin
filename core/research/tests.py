from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch
import json

from compounds.models import Compound
from research.content_format import render_snippet_content
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


class SnippetContentRenderTests(TestCase):
    def test_plain_text_content_renders_with_line_breaks(self):
        rendered = render_snippet_content("Line one\nLine two")
        self.assertEqual(rendered, "Line one<br>Line two")

    def test_rich_content_sanitizes_unsafe_html_and_keeps_images(self):
        raw = (
            '<p>Hello <strong>world</strong></p>'
            '<img src="data:image/png;base64,AAAA" alt="x">'
            '<script>alert(1)</script>'
        )
        rendered = render_snippet_content(raw)
        self.assertIn("<strong>world</strong>", rendered)
        self.assertIn("<img ", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("alert(1)", rendered)


class SnippetContentSaveTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user(username="snippet_saver", password="StrongPass123!")
        self.compound = Compound.objects.create(name="Snippet Save Compound", slug="snippet-save-compound")
        self.client.login(username="snippet_saver", password="StrongPass123!")

    def test_create_snippet_sanitizes_rich_html_content(self):
        payload = {
            "title": "Sanitized snippet",
            "content": (
                '<p>Safe <strong>text</strong></p>'
                '<img src="data:image/png;base64,AAAA" alt="img">'
                '<script>alert(1)</script>'
            ),
            "compound": str(self.compound.pk),
            "snippet_type": "general",
            "source_title": "",
            "source_url": "",
            "doi": "",
        }

        response = self.client.post(reverse("research:create_snippet"), data=payload)
        self.assertEqual(response.status_code, 302)
        snippet = ResearchSnippet.objects.get(title="Sanitized snippet")
        self.assertIn("<strong>text</strong>", snippet.content)
        self.assertIn("<img ", snippet.content)
        self.assertNotIn("<script>", snippet.content)
        self.assertNotIn("alert(1)", snippet.content)

    def test_create_snippet_keeps_plain_text_content_unchanged(self):
        plain_text = "Line one\nLine two"
        payload = {
            "title": "Plain text snippet",
            "content": plain_text,
            "compound": str(self.compound.pk),
            "snippet_type": "general",
            "source_title": "",
            "source_url": "",
            "doi": "",
        }

        response = self.client.post(reverse("research:create_snippet"), data=payload)
        self.assertEqual(response.status_code, 302)
        snippet = ResearchSnippet.objects.get(title="Plain text snippet")
        self.assertEqual(snippet.content, plain_text)


class SnippetDetailMetadataTests(TestCase):
    def test_snippet_detail_og_title_uses_snippet_title(self):
        User = get_user_model()
        author = User.objects.create_user(username="meta_author", password="StrongPass123!")
        compound = Compound.objects.create(name="Metadata Compound", slug="metadata-compound")
        snippet = ResearchSnippet.objects.create(
            title="OG Title Should Match Snippet",
            content="Body",
            compound=compound,
            created_by=author,
            visibility="public",
            status="submitted",
        )

        response = self.client.get(reverse("research:snippet_detail", kwargs={"pk": snippet.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<meta property="og:title" content="OG Title Should Match Snippet">',
            html=True,
        )
        self.assertContains(
            response,
            '<meta name="twitter:title" content="OG Title Should Match Snippet">',
            html=True,
        )

    def test_snippet_detail_metadata_description_includes_compound_and_avoids_ai_summary(self):
        User = get_user_model()
        author = User.objects.create_user(username="meta_desc_author", password="StrongPass123!")
        compound = Compound.objects.create(name="Trestolone Acetate", slug="trestolone-acetate")
        snippet = ResearchSnippet.objects.create(
            title="Signal pathway notes",
            content="Body",
            ai_summary="THIS_AI_SUMMARY_SHOULD_NOT_APPEAR",
            compound=compound,
            created_by=author,
            visibility="public",
            status="submitted",
        )

        response = self.client.get(reverse("research:snippet_detail", kwargs={"pk": snippet.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<meta property="og:description" content="Research snippet for Trestolone Acetate. Community findings and source context.">',
            html=True,
        )
        self.assertContains(
            response,
            '<meta name="twitter:description" content="Research snippet for Trestolone Acetate. Community findings and source context.">',
            html=True,
        )
        self.assertNotContains(response, "THIS_AI_SUMMARY_SHOULD_NOT_APPEAR")


class SnippetDetailCommentFormTests(TestCase):
    def test_snippet_author_page_includes_csrf_token_for_comment_form(self):
        User = get_user_model()
        author = User.objects.create_user(username="comment_author", password="StrongPass123!")
        compound = Compound.objects.create(name="Comment Flow Compound", slug="comment-flow-compound")
        snippet = ResearchSnippet.objects.create(
            title="Comment flow snippet",
            content="Body",
            compound=compound,
            created_by=author,
            visibility="public",
            status="submitted",
        )

        self.client.login(username="comment_author", password="StrongPass123!")
        response = self.client.get(reverse("research:snippet_detail", kwargs={"pk": snippet.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="comment-form"', html=False)
        self.assertContains(response, 'name="csrfmiddlewaretoken"', html=False)


class SnippetCommentEndpointTests(TestCase):
    def test_add_comment_response_includes_author_profile_url(self):
        User = get_user_model()
        author = User.objects.create_user(username="profile_link_user", password="StrongPass123!")
        compound = Compound.objects.create(name="Comment Endpoint Compound", slug="comment-endpoint-compound")
        snippet = ResearchSnippet.objects.create(
            title="Endpoint snippet",
            content="Body",
            compound=compound,
            created_by=author,
            visibility="public",
            status="submitted",
        )

        self.client.login(username="profile_link_user", password="StrongPass123!")
        response = self.client.post(
            reverse("research:add_snippet_comment", kwargs={"pk": snippet.pk}),
            data=json.dumps({"content": "This is a valid test comment."}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload.get("success"))
        self.assertEqual(
            payload["comment"].get("author_profile_url"),
            reverse("user_profile", kwargs={"username": author.username}),
        )


class CompoundSnippetOrderingTests(TestCase):
    def test_compound_snippets_orders_by_view_count_desc(self):
        User = get_user_model()
        author = User.objects.create_user(username="view_sort_author", password="StrongPass123!")
        compound = Compound.objects.create(name="View Sort Compound", slug="view-sort-compound")

        low_views = ResearchSnippet.objects.create(
            title="Lower views snippet",
            content="Body",
            compound=compound,
            created_by=author,
            visibility="public",
            status="submitted",
            snippet_type="general",
            view_count=3,
        )
        high_views = ResearchSnippet.objects.create(
            title="Higher views snippet",
            content="Body",
            compound=compound,
            created_by=author,
            visibility="public",
            status="submitted",
            snippet_type="general",
            view_count=42,
        )

        response = self.client.get(reverse("research:compound_snippets", kwargs={"slug": compound.slug}))

        self.assertEqual(response.status_code, 200)
        snippet_groups = response.context["snippet_groups"]
        ordered_ids = [snippet.id for group in snippet_groups.values() for snippet in group]
        self.assertEqual(ordered_ids[:2], [high_views.id, low_views.id])


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
