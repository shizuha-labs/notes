"""
NTS-22: regression test for short-query recall with trigram word similarity.

title__trigram_similar (% operator) uses whole-string similarity and drops
verbatim short words inside long titles (e.g. "budget" vs "Annual Budget
Planning Q4 2024" scores ≈ 0.21, below the 0.3 threshold).

title__trigram_word_similar (%> operator) scores against the closest matching
word in the title; "budget" vs any title containing the word "budget" scores 1.0.
This file verifies the regression is fixed and stays fixed.

Requires PostgreSQL with pg_trgm (installed by migration 0007).
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase

from rest_framework.test import APIRequestFactory

from ..models import Note, Notebook
from ..views import SearchView


def _mock_user(user_id=1):
    u = MagicMock()
    u.id = user_id
    u.pk = user_id
    u.email = 'test@example.com'
    u.is_authenticated = True
    return u


def _search(params, user_id=1):
    factory = APIRequestFactory()
    request = factory.get('/api/search/', params)
    request.user = _mock_user(user_id)
    request._user_organization_ids = [1]
    request.organization_id = None
    request._pending_organization_id = None
    with patch('notes.services.search.set_organization_context'), \
         patch('notes.services.search.get_user_organization_ids', return_value=[1]):
        return SearchView.as_view()(request)


class ShortQueryRecallTests(TestCase):
    """NTS-22: short verbatim word inside a long title must be found."""

    @classmethod
    def setUpTestData(cls):
        cls.nb = Notebook.objects.create(organization_id=1, name='NTS22-NB', created_by_id=1)
        cls.long_title_note = Note.objects.create(
            organization_id=1,
            notebook=cls.nb,
            title='Annual Budget Planning Q4 2024',
            created_by_id=1,
        )
        cls.short_title_note = Note.objects.create(
            organization_id=1,
            notebook=cls.nb,
            title='Budget',
            created_by_id=1,
        )
        cls.unrelated_note = Note.objects.create(
            organization_id=1,
            notebook=cls.nb,
            title='Q4 Revenue Forecast',
            created_by_id=1,
        )

    def _ids(self, resp):
        return {str(item['id']) for item in resp.data['results']}

    def test_short_word_matches_long_title(self):
        """'budget' must match 'Annual Budget Planning Q4 2024'."""
        resp = _search({'q': 'budget'})
        self.assertEqual(resp.status_code, 200)
        ids = self._ids(resp)
        self.assertIn(
            str(self.long_title_note.id), ids,
            "'budget' query must match a title containing the word 'budget', "
            "even when the overall string similarity is low.",
        )

    def test_short_word_matches_exact_title(self):
        """'budget' must also match a note titled exactly 'Budget'."""
        resp = _search({'q': 'budget'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(str(self.short_title_note.id), self._ids(resp))

    def test_unrelated_note_not_returned(self):
        """Notes without 'budget' in title or content must not be returned."""
        resp = _search({'q': 'budget'})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(str(self.unrelated_note.id), self._ids(resp))

    def test_multi_word_short_query(self):
        """'Q4 2024' (two short tokens) must match the long title."""
        resp = _search({'q': 'Q4 2024'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(str(self.long_title_note.id), self._ids(resp))
