from django.contrib.auth import get_user_model
from django.test import TestCase

from compounds.models import Compound
from research.models import ResearchSnippet, SnippetTag, SnippetTagging


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
