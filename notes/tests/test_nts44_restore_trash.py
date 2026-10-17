"""NTS-44: a user can restore their own trashed note through the restore action."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from notes.models import Note, Notebook
from notes.views import NoteViewSet


USER_ID = 4401
USER_EMAIL = 'nts44-owner@example.com'
ORG_ID = 14401


def _user():
    return SimpleNamespace(
        id=USER_ID,
        pk=USER_ID,
        email=USER_EMAIL,
        is_authenticated=True,
        is_active=True,
        is_anonymous=False,
        is_staff=False,
        is_superuser=False,
        organization_role=None,
        enabled_services=['notes'],
    )


def _request(method, path, user, data=None):
    factory = APIRequestFactory()
    req = getattr(factory, method)(path, data or {}, format='json')
    force_authenticate(req, user=user)
    req.user = user
    req._user_organization_ids = [ORG_ID]
    req.organization_id = None
    req._pending_organization_id = None
    return req


def _dispatch_restore(request, note_id):
    with patch('notes.services.search.get_user_organization_ids', return_value=[ORG_ID]), \
         patch('notes.middleware.get_user_organization_ids', return_value=[ORG_ID]):
        return NoteViewSet.as_view({'post': 'restore'})(request, pk=str(note_id))


def _dispatch_retrieve(request, note_id):
    with patch('notes.services.search.get_user_organization_ids', return_value=[ORG_ID]), \
         patch('notes.middleware.get_user_organization_ids', return_value=[ORG_ID]):
        return NoteViewSet.as_view({'get': 'retrieve'})(request, pk=str(note_id))


class RestoreTrashedNoteTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.notebook = Notebook.objects.create(
            organization_id=ORG_ID,
            name='NTS-44 notebook',
            created_by_id=USER_ID,
        )
        self.note = Note.objects.create(
            organization_id=ORG_ID,
            notebook=self.notebook,
            title='NTS-44 trashed note',
            content_json={'type': 'doc'},
            content_text='cvqa27 restore me',
            status='trashed',
            created_by_id=USER_ID,
            created_by_email=USER_EMAIL,
        )

    def test_owner_can_restore_their_own_trashed_note(self):
        req = _request('post', f'/api/notes/{self.note.id}/restore/', self.user)

        response = _dispatch_restore(req, self.note.id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'status': 'restored'})
        self.note.refresh_from_db()
        self.assertEqual(self.note.status, 'draft')
        self.assertIsNone(self.note.trashed_at)

        detail_req = _request('get', f'/api/notes/{self.note.id}/', self.user)
        detail = _dispatch_retrieve(detail_req, self.note.id)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data['status'], 'draft')
