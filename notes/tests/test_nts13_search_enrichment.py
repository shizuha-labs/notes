"""
API-level tests for SearchView result enrichment — NTS-13 (Slice 2).

Reworked onto NTS-12's build_authorized_queryset base. Verifies:
- score (SearchRank) + match_reason are attached to query results
- P1-B: a TITLE-only match returns a highlighted TITLE snippet (not an empty /
  truncated body excerpt)
- P2-B: match_reason does NOT default to 'body' when there is no body hit
- include_snippets=false suppresses the snippet field (score/match_reason stay)

Requires the Postgres FTS test DB (SearchHeadline/SearchRank + search_vector
trigger) — runs in CI, not the sandbox.
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from ..models import Note, Notebook
from ..views import SearchView


def _mock_user(user_id=1, email='test@example.com'):
    user = MagicMock()
    user.id = user_id
    user.pk = user_id
    user.email = email
    user.is_authenticated = True
    return user


def _search(params, user_id=1, email='test@example.com', org_ids=None):
    factory = APIRequestFactory()
    request = factory.get('/api/search/', params)
    request.user = _mock_user(user_id=user_id, email=email)
    request._user_organization_ids = org_ids or [1]
    request.organization_id = None
    request._pending_organization_id = None
    with patch('notes.services.search.set_organization_context'), \
         patch('notes.services.search.get_user_organization_ids', return_value=org_ids or [1]):
        return SearchView.as_view()(request)


class SearchEnrichmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nb = Notebook.objects.create(organization_id=1, name='NB', created_by_id=1)

    def _note(self, title, content_text=''):
        return Note.objects.create(
            organization_id=1, notebook=self.nb, created_by_id=1,
            title=title, content_text=content_text,
        )

    def test_query_result_has_score_and_match_reason(self):
        self._note('Budget plan', 'the quarterly budget breakdown')
        resp = _search({'q': 'budget'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['results'])
        row = resp.data['results'][0]
        self.assertIn('score', row)
        self.assertIsInstance(row['score'], float)
        self.assertIn('match_reason', row)
        self.assertIn('snippet', row)  # default include_snippets=true

    def test_title_only_match_returns_highlighted_title_snippet(self):
        # P1-B: title matches, body empty → snippet must be the highlighted TITLE.
        self._note('Quarterly Planning', content_text='')
        resp = _search({'q': 'planning'})
        row = resp.data['results'][0]
        self.assertIn('title', row['match_reason'])
        self.assertIn('<mark>', row['snippet'].lower())
        self.assertIn('planning', row['snippet'].lower())

    def test_title_only_match_does_not_claim_body(self):
        # P2-B: no body hit → match_reason must NOT contain 'body'.
        self._note('Quarterly Planning', content_text='')
        resp = _search({'q': 'planning'})
        row = resp.data['results'][0]
        self.assertNotIn('body', row['match_reason'])

    def test_body_match_reason(self):
        self._note('Misc', 'the budget meeting notes')
        resp = _search({'q': 'budget'})
        row = resp.data['results'][0]
        self.assertIn('body', row['match_reason'])

    def test_include_snippets_false_suppresses_snippet(self):
        self._note('Budget plan', 'the quarterly budget breakdown')
        resp = _search({'q': 'budget', 'include_snippets': 'false'})
        row = resp.data['results'][0]
        self.assertNotIn('snippet', row)
        # score + match_reason are still provided (cheap, no headline work).
        self.assertIn('score', row)
        self.assertIn('match_reason', row)
