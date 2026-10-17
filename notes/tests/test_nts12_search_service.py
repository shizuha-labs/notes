"""
Unit tests for the shared search service — NTS-12.

Coverage:
- Cross-org notes do NOT appear in another org's authorized queryset.
- Revoked shares are excluded from the authorized queryset.
- Trashed notes are excluded by apply_filters() by default.
- apply_filters() status override includes trashed when explicitly requested.
- apply_filters() filter params: notebook, tag (AND/OR), favorite, pinned,
  shared_with_me, date range.
- apply_sort() enum mapping and default ordering.
"""
import uuid
from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase, RequestFactory
from django.utils import timezone

from ..models import Note, Notebook, Tag, NoteShare
from ..services.search import (
    build_authorized_queryset,
    apply_filters,
    apply_sort,
    _parse_iso,
)


def _make_request(user_id=1, user_email='user@example.com', org_ids=None, org_id=None):
    """Return a minimal mock request for the search service."""
    factory = RequestFactory()
    request = factory.get('/')
    request.user = MagicMock()
    request.user.id = user_id
    request.user.pk = user_id
    request.user.email = user_email
    request.user.is_authenticated = True
    # Pre-set org context (skips the admin API call in tests)
    request.organization_id = org_id
    request._user_organization_ids = org_ids or []
    request._pending_organization_id = org_id
    return request


def _make_org_request(org_ids, user_id=1, user_email='user@example.com'):
    """Request whose user belongs to the given list of org IDs."""
    return _make_request(user_id=user_id, user_email=user_email, org_ids=org_ids)


class BuildAuthorizedQuerysetTests(TestCase):
    """build_authorized_queryset must enforce org boundary and share predicate."""

    @classmethod
    def setUpTestData(cls):
        cls.nb_org1 = Notebook.objects.create(
            organization_id=1, name='NB-Org1', created_by_id=10,
        )
        cls.nb_org2 = Notebook.objects.create(
            organization_id=2, name='NB-Org2', created_by_id=20,
        )
        cls.note_org1 = Note.objects.create(
            organization_id=1, notebook=cls.nb_org1,
            title='Org1 Note', created_by_id=10,
        )
        cls.note_org2 = Note.objects.create(
            organization_id=2, notebook=cls.nb_org2,
            title='Org2 Note', created_by_id=20,
        )

    @patch('notes.services.search.set_organization_context')
    def test_cross_org_notes_excluded(self, mock_set_org):
        """A caller in org 1 must NOT see org 2 notes."""
        request = _make_org_request(org_ids=[1], user_id=10)
        qs = build_authorized_queryset(request)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.note_org1.id, ids)
        self.assertNotIn(self.note_org2.id, ids)

    @patch('notes.services.search.set_organization_context')
    def test_revoked_share_excluded(self, mock_set_org):
        """A note shared with user 99 but then revoked must NOT appear.

        User 99 is in org 1 (NOT org 2), so the only path to see note_org2 is
        via the share predicate. A revoked share must not grant access.
        """
        request = _make_org_request(org_ids=[1], user_id=99)
        NoteShare.objects.create(
            note=self.note_org2,
            shared_with_user_id=99,
            shared_by_id=20,
            revoked_at=timezone.now(),  # already revoked
        )
        qs = build_authorized_queryset(request)
        ids = set(qs.values_list('id', flat=True))
        self.assertNotIn(self.note_org2.id, ids,
                         "Revoked share must not grant access")

    @patch('notes.services.search.set_organization_context')
    def test_active_share_grants_access(self, mock_set_org):
        """A note shared (non-revoked) with user 99 must appear even if outside their org."""
        request = _make_org_request(org_ids=[1], user_id=99)
        share = NoteShare.objects.create(
            note=self.note_org2,
            shared_with_user_id=99,
            shared_by_id=20,
            revoked_at=None,
        )
        qs = build_authorized_queryset(request)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.note_org2.id, ids)
        share.delete()

    @patch('notes.services.search.set_organization_context')
    def test_email_share_fallback(self, mock_set_org):
        """An email-only share grants access to a user whose user_id wasn't resolved."""
        request = _make_request(user_id=77, user_email='newcomer@example.com', org_ids=[1])
        share = NoteShare.objects.create(
            note=self.note_org2,
            shared_with_email='newcomer@example.com',
            shared_by_id=20,
            revoked_at=None,
        )
        qs = build_authorized_queryset(request)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.note_org2.id, ids)
        share.delete()


class ApplyFiltersTests(TestCase):
    """apply_filters: each filter param applied correctly; trashed excluded by default."""

    @classmethod
    def setUpTestData(cls):
        cls.nb = Notebook.objects.create(
            organization_id=1, name='Test NB', created_by_id=1,
        )
        cls.nb2 = Notebook.objects.create(
            organization_id=1, name='Other NB', created_by_id=1,
        )
        cls.tag_a = Tag.objects.create(organization_id=1, name='alpha', slug='alpha')
        cls.tag_b = Tag.objects.create(organization_id=1, name='beta', slug='beta')

        cls.note_live = Note.objects.create(
            organization_id=1, notebook=cls.nb,
            title='Live Note', created_by_id=1,
            status='published', is_favorite=True, is_pinned=False,
        )
        cls.note_trashed = Note.objects.create(
            organization_id=1, notebook=cls.nb,
            title='Trashed Note', created_by_id=1,
            status='trashed',
        )
        cls.note_pinned = Note.objects.create(
            organization_id=1, notebook=cls.nb,
            title='Pinned Note', created_by_id=1,
            is_pinned=True,
        )
        cls.note_nb2 = Note.objects.create(
            organization_id=1, notebook=cls.nb2,
            title='Other NB Note', created_by_id=1,
        )
        cls.note_tagged = Note.objects.create(
            organization_id=1, notebook=cls.nb,
            title='Tagged Note', created_by_id=1,
        )
        cls.note_tagged.tags.add(cls.tag_a, cls.tag_b)

    def _base_qs(self):
        return Note.objects.filter(organization_id=1)

    def test_trashed_excluded_by_default(self):
        qs = apply_filters(self._base_qs(), {}, user_id=1)
        ids = set(qs.values_list('id', flat=True))
        self.assertNotIn(self.note_trashed.id, ids)
        self.assertIn(self.note_live.id, ids)

    def test_status_override_includes_trashed(self):
        qs = apply_filters(self._base_qs(), {'status': 'trashed'}, user_id=1)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.note_trashed.id, ids)
        self.assertNotIn(self.note_live.id, ids)

    def test_notebook_filter(self):
        qs = apply_filters(self._base_qs(), {'notebook': str(self.nb2.id)}, user_id=1)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.note_nb2.id, ids)
        self.assertNotIn(self.note_live.id, ids)

    def test_favorite_filter(self):
        qs = apply_filters(self._base_qs(), {'favorite': 'true'}, user_id=1)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.note_live.id, ids)
        self.assertNotIn(self.note_pinned.id, ids)

    def test_pinned_filter(self):
        qs = apply_filters(self._base_qs(), {'pinned': 'true'}, user_id=1)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.note_pinned.id, ids)
        self.assertNotIn(self.note_live.id, ids)

    def test_tag_and_mode(self):
        """Default AND: note must have ALL specified tags."""
        params = {'tag_ids': f'{self.tag_a.id},{self.tag_b.id}', 'tag_mode': 'all'}
        qs = apply_filters(self._base_qs(), params, user_id=1)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.note_tagged.id, ids)
        # Note with only one of the tags should not appear
        single_tagged = Note.objects.create(
            organization_id=1, notebook=self.nb, title='Single Tag', created_by_id=1,
        )
        single_tagged.tags.add(self.tag_a)
        qs2 = apply_filters(self._base_qs(), params, user_id=1)
        ids2 = set(qs2.values_list('id', flat=True))
        self.assertNotIn(single_tagged.id, ids2)
        single_tagged.delete()

    def test_tag_any_mode(self):
        """OR mode: note with either tag appears."""
        params = {'tag': str(self.tag_a.id), 'tag_mode': 'any'}
        qs = apply_filters(self._base_qs(), params, user_id=1)
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(self.note_tagged.id, ids)

    def test_shared_with_me_filter(self):
        """shared_with_me=true restricts to notes with an active share for this user."""
        user_id = 55
        shared_note = Note.objects.create(
            organization_id=1, notebook=self.nb,
            title='Shared with 55', created_by_id=1,
        )
        NoteShare.objects.create(
            note=shared_note, shared_with_user_id=user_id,
            shared_by_id=1, revoked_at=None,
        )
        qs = apply_filters(
            Note.objects.filter(organization_id=1),
            {'shared_with_me': 'true'},
            user_id=user_id,
        )
        ids = set(qs.values_list('id', flat=True))
        self.assertIn(shared_note.id, ids)
        self.assertNotIn(self.note_live.id, ids)
        shared_note.delete()

    def test_date_range_created_after(self):
        early = Note.objects.create(
            organization_id=1, notebook=self.nb,
            title='Early Note', created_by_id=1,
        )
        # Manually backdate to a very old timestamp — not possible via auto_now_add.
        # Use update() to bypass auto_now_add.
        Note.objects.filter(id=early.id).update(
            created_at=datetime(2020, 1, 1, tzinfo=dt_timezone.utc)
        )
        qs = apply_filters(
            Note.objects.filter(organization_id=1),
            {'created_after': '2025-01-01'},
            user_id=1,
        )
        ids = set(qs.values_list('id', flat=True))
        self.assertNotIn(early.id, ids)
        early.delete()


class ApplySortTests(TestCase):
    """apply_sort: sort enum mapped to correct ordering."""

    def _dummy_qs(self):
        return Note.objects.none()

    def test_sort_updated_desc(self):
        qs = apply_sort(self._dummy_qs(), 'updated_desc')
        self.assertEqual(list(qs.query.order_by), ['-updated_at'])

    def test_sort_title_asc(self):
        qs = apply_sort(self._dummy_qs(), 'title_asc')
        self.assertEqual(list(qs.query.order_by), ['title'])

    def test_sort_relevance_without_query(self):
        qs = apply_sort(self._dummy_qs(), 'relevance', has_query=False)
        self.assertEqual(list(qs.query.order_by), ['-updated_at'])

    def test_sort_relevance_with_query(self):
        """has_query=True enables ranked ordering by search_rank then recency."""
        from django.db.models import FloatField, Value
        # Annotate a dummy queryset with search_rank (mirrors what SearchView does
        # before calling apply_sort) so Django accepts the order_by field.
        qs = Note.objects.none().annotate(search_rank=Value(0.0, output_field=FloatField()))
        result = apply_sort(qs, 'relevance', has_query=True)
        self.assertEqual(list(result.query.order_by), ['-search_rank', '-updated_at'])

    def test_default_sort(self):
        qs = apply_sort(self._dummy_qs(), None)
        self.assertEqual(list(qs.query.order_by), ['-is_pinned', '-updated_at'])


class ParseIsoTests(TestCase):
    """_parse_iso handles common date/datetime formats."""

    def test_date_only(self):
        result = _parse_iso('2026-01-15')
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2026)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 15)

    def test_datetime_z(self):
        result = _parse_iso('2026-06-28T10:00:00Z')
        self.assertIsNotNone(result)
        self.assertEqual(result.tzinfo, dt_timezone.utc)

    def test_invalid_returns_none(self):
        self.assertIsNone(_parse_iso('not-a-date'))
        self.assertIsNone(_parse_iso(''))
        self.assertIsNone(_parse_iso(None))


class SharedServiceIntegrationTests(TestCase):
    """SearchView.get() and NoteViewSet.get_queryset() both call build_authorized_queryset.

    Guards against a future local re-implementation drifting from the shared security
    predicate — if either view forks the logic, these patches will fail to intercept.
    """

    def _make_request(self, data=None):
        factory = RequestFactory()
        request = factory.get('/', data or {})
        request.user = MagicMock()
        request.user.id = 1
        request.user.pk = 1
        request.user.email = 'test@example.com'
        request.user.is_authenticated = True
        request.organization_id = 1
        request._user_organization_ids = [1]
        # query_params is the DRF alias for GET — add it so views can call it
        request.query_params = request.GET
        return request

    @patch('notes.views.build_authorized_queryset', return_value=Note.objects.none())
    def test_search_view_delegates_to_shared_service(self, mock_baq):
        from notes.views import SearchView
        request = self._make_request(data={'q': 'test'})
        SearchView().get(request)
        mock_baq.assert_called_once_with(request)

    @patch('notes.views.build_authorized_queryset', return_value=Note.objects.none())
    def test_note_viewset_delegates_to_shared_service(self, mock_baq):
        from notes.views import NoteViewSet
        request = self._make_request()
        vs = NoteViewSet()
        vs.request = request
        vs.get_queryset()
        mock_baq.assert_called_once_with(request)
