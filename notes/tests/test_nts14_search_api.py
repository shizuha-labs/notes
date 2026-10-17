"""
API-level tests for SearchView filter + sort exposure — NTS-14.

These tests verify the HTTP contract:
- GET /search/ with all filter params returns correct results
- Sort enum works for all 7 modes
- Empty q with a filter → 200 filtered browse (updated_desc default)
- Empty q with no filter → 400 validation error
- page_size is capped at 50
"""
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from ..models import Note, Notebook, Tag, NoteShare
from ..views import SearchView


def _mock_user(user_id=1, email='test@example.com'):
    user = MagicMock()
    user.id = user_id
    user.pk = user_id
    user.email = email
    user.is_authenticated = True
    return user


def _search(query_string='', user_id=1, email='test@example.com', org_ids=None):
    """Call SearchView.get() with a fake authenticated request."""
    factory = APIRequestFactory()
    request = factory.get('/api/search/', query_string)
    request.user = _mock_user(user_id=user_id, email=email)
    request._user_organization_ids = org_ids or [1]
    request.organization_id = None
    request._pending_organization_id = None

    with patch('notes.services.search.set_organization_context'), \
         patch('notes.services.search.get_user_organization_ids', return_value=org_ids or [1]):
        view = SearchView.as_view()
        return view(request)


class SearchViewEmptyQTests(TestCase):
    """Validation: empty q with/without filters."""

    def test_empty_q_no_filters_returns_400(self):
        response = _search()
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.data)

    def test_empty_q_with_filter_returns_200(self):
        nb = Notebook.objects.create(organization_id=1, name='NB', created_by_id=1)
        Note.objects.create(organization_id=1, notebook=nb, title='Fav', created_by_id=1, is_favorite=True)
        response = _search({'favorite': 'true'})
        self.assertEqual(response.status_code, 200)

    def test_q_only_returns_200(self):
        nb = Notebook.objects.create(organization_id=1, name='NB2', created_by_id=1)
        Note.objects.create(organization_id=1, notebook=nb, title='Hello world', created_by_id=1)
        response = _search({'q': 'hello'})
        self.assertEqual(response.status_code, 200)


class SearchViewSortTests(TestCase):
    """All 7 sort modes accepted without error."""

    @classmethod
    def setUpTestData(cls):
        cls.nb = Notebook.objects.create(organization_id=1, name='SortNB', created_by_id=1)
        Note.objects.create(organization_id=1, notebook=cls.nb, title='A Note', created_by_id=1)

    def _assert_sort_ok(self, sort_value):
        response = _search({'q': 'note', 'sort': sort_value})
        self.assertEqual(response.status_code, 200, f"sort={sort_value} failed with {response.status_code}")
        self.assertEqual(response.data['sort'], sort_value)

    def test_sort_relevance(self):
        self._assert_sort_ok('relevance')

    def test_sort_updated_desc(self):
        self._assert_sort_ok('updated_desc')

    def test_sort_updated_asc(self):
        self._assert_sort_ok('updated_asc')

    def test_sort_created_desc(self):
        self._assert_sort_ok('created_desc')

    def test_sort_created_asc(self):
        self._assert_sort_ok('created_asc')

    def test_sort_title_asc(self):
        self._assert_sort_ok('title_asc')

    def test_sort_title_desc(self):
        self._assert_sort_ok('title_desc')


class SearchViewFilterTests(TestCase):
    """Filter params exposed correctly on the API."""

    @classmethod
    def setUpTestData(cls):
        cls.nb = Notebook.objects.create(organization_id=1, name='FilterNB', created_by_id=1)
        cls.nb2 = Notebook.objects.create(organization_id=1, name='FilterNB2', created_by_id=1)
        cls.tag = Tag.objects.create(organization_id=1, name='work', slug='work')
        cls.note_fav = Note.objects.create(
            organization_id=1, notebook=cls.nb, title='Favorite Note',
            created_by_id=1, is_favorite=True,
        )
        cls.note_pin = Note.objects.create(
            organization_id=1, notebook=cls.nb, title='Pinned Note',
            created_by_id=1, is_pinned=True,
        )
        cls.note_nb2 = Note.objects.create(
            organization_id=1, notebook=cls.nb2, title='NB2 Note', created_by_id=1,
        )
        cls.note_tagged = Note.objects.create(
            organization_id=1, notebook=cls.nb, title='Tagged Note', created_by_id=1,
        )
        cls.note_tagged.tags.add(cls.tag)

    def _ids(self, response):
        return {r['id'] for r in response.data['results']}

    def test_favorite_filter(self):
        response = _search({'favorite': 'true'})
        self.assertEqual(response.status_code, 200)
        ids = self._ids(response)
        self.assertIn(str(self.note_fav.id), ids)
        self.assertNotIn(str(self.note_pin.id), ids)

    def test_pinned_filter(self):
        response = _search({'pinned': 'true'})
        self.assertEqual(response.status_code, 200)
        ids = self._ids(response)
        self.assertIn(str(self.note_pin.id), ids)
        self.assertNotIn(str(self.note_fav.id), ids)

    def test_notebook_filter(self):
        response = _search({'notebook': str(self.nb2.id)})
        self.assertEqual(response.status_code, 200)
        ids = self._ids(response)
        self.assertIn(str(self.note_nb2.id), ids)
        self.assertNotIn(str(self.note_fav.id), ids)

    def test_tag_filter(self):
        response = _search({'tag': str(self.tag.id)})
        self.assertEqual(response.status_code, 200)
        ids = self._ids(response)
        self.assertIn(str(self.note_tagged.id), ids)
        self.assertNotIn(str(self.note_fav.id), ids)

    def test_shared_with_me_filter(self):
        """shared_with_me=true shows notes shared with the caller."""
        shared_note = Note.objects.create(
            organization_id=1, notebook=self.nb, title='Shared Note', created_by_id=1,
        )
        NoteShare.objects.create(
            note=shared_note, shared_with_user_id=42, shared_by_id=1, revoked_at=None,
        )
        response = _search({'shared_with_me': 'true'}, user_id=42)
        self.assertEqual(response.status_code, 200)
        ids = self._ids(response)
        self.assertIn(str(shared_note.id), ids)
        shared_note.delete()

    def test_browse_mode_default_sort_is_updated_desc(self):
        """`GET /search/?favorite=true` (no q) returns results in updated_desc order."""
        response = _search({'favorite': 'true'})
        self.assertEqual(response.status_code, 200)
        # relevance with no query degrades to -updated_at; API echoes 'updated_desc'
        self.assertEqual(response.data['sort'], 'updated_desc')

    def test_page_size_capped_at_50(self):
        response = _search({'favorite': 'true', 'page_size': '200'})
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(response.data['page_size'], 50)

    def test_response_includes_sort_field(self):
        response = _search({'q': 'note', 'sort': 'title_asc'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('sort', response.data)
        self.assertEqual(response.data['sort'], 'title_asc')
