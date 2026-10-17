"""NTS-42: active organization scope must constrain same-user note visibility.

Regression for WIKI-27: a multi-org user scoped to org 1 saw their own org 20
Notes results through list/search because the owner leg of the authorized-note
predicate ignored ``request.organization_id``.
"""

from notes.tests.api_fixtures import response_items
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from notes.models import Note, Notebook
from notes.views import NoteViewSet, SearchView

ORG_A = 1
ORG_B = 20
USER_ID = 4242


class _User(SimpleNamespace):
    @property
    def is_authenticated(self):
        return True


def _notebook(org, name):
    return Notebook.objects.create(organization_id=org, name=name, created_by_id=USER_ID)


def _note(org, title, *, status='published'):
    return Note.objects.create(
        organization_id=org,
        notebook=_notebook(org, f'nb-{org}-{title}'),
        title=title,
        content_text=title,
        created_by_id=USER_ID,
        status=status,
    )


def _request(path, params):
    factory = APIRequestFactory()
    request = factory.get(path, params, HTTP_X_ORGANIZATION_ID=str(ORG_A))
    request.organization_id = ORG_A
    request._pending_organization_id = ORG_A
    request._user_organization_ids = [ORG_A, ORG_B]
    force_authenticate(request, user=_User(id=USER_ID, pk=USER_ID, email='multi@example.com'))
    return request


class ActiveOrgScopeTests(TestCase):
    def setUp(self):
        self.org1_note = _note(ORG_A, 'org1 visible private term', status='trashed')
        self.org20_note = _note(ORG_B, 'org20 private leak term', status='trashed')

    def _patch_org_context(self):
        return patch.multiple(
            'notes.services.search',
            set_organization_context=lambda request: None,
            get_user_organization_ids=lambda request: [ORG_A, ORG_B],
        )

    def test_note_list_status_filter_respects_requested_org_for_same_user(self):
        request = _request('/api/notes/', {'status': 'trashed', 'q': 'org20 private leak term'})
        with self._patch_org_context(), patch('notes.views.set_organization_context', lambda request: None):
            response = NoteViewSet.as_view({'get': 'list'})(request)

        self.assertEqual(response.status_code, 200)
        ids = {row['id'] for row in response_items(response)}
        self.assertIn(str(self.org1_note.id), ids)
        self.assertNotIn(str(self.org20_note.id), ids)

    def test_search_filter_browse_respects_requested_org_for_same_user(self):
        request = _request('/api/search/', {'status': 'trashed'})
        with self._patch_org_context(), patch('notes.views.set_organization_context', lambda request: None):
            response = SearchView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        ids = {row['id'] for row in response.data['results']}
        self.assertIn(str(self.org1_note.id), ids)
        self.assertNotIn(str(self.org20_note.id), ids)
