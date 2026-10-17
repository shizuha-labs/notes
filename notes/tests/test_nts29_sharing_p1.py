"""NTS-29 P1: shared predicate, share revocation, and audit tests."""
from datetime import timedelta
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from notes.models import Attachment, Notebook, Note, NoteShare, NoteShareAudit
from notes.services.access import can_access
from notes.services.search import build_authorized_queryset
from notes.views import AttachmentViewSet, NoteViewSet, NotebookViewSet


class _User(SimpleNamespace):
    @property
    def is_authenticated(self):
        return True


def _request(user_id, *, email=None, org_ids=None, org_id=None):
    request = RequestFactory().get('/')
    request.user = _User(id=user_id, pk=user_id, email=email or f'u{user_id}@example.com')
    request.organization_id = org_id
    request.organization_role = None
    request._user_organization_ids = org_ids or []
    return request


class NTS29SharingP1Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nb = Notebook.objects.create(organization_id=1, name='NTS29', created_by_id=1)
        cls.note = Note.objects.create(
            organization_id=1,
            notebook=cls.nb,
            title='Owner note',
            content_text='secret body',
            created_by_id=1,
            status='published',
        )

    def test_authorized_queryset_is_owner_or_active_share_not_org_membership(self):
        org_peer = _request(2, org_ids=[1])
        self.assertNotIn(self.note.id, set(build_authorized_queryset(org_peer).values_list('id', flat=True)))

        share = NoteShare.objects.create(
            note=self.note,
            shared_with_user_id=2,
            shared_by_id=1,
            permission='view',
        )
        self.assertIn(self.note.id, set(build_authorized_queryset(org_peer).values_list('id', flat=True)))
        self.assertEqual(can_access(2, self.note, request=org_peer).role, 'view')

        share.revoked_at = timezone.now()
        share.is_active = False
        share.save(update_fields=['revoked_at', 'is_active', 'updated_at'])
        self.assertNotIn(self.note.id, set(build_authorized_queryset(org_peer).values_list('id', flat=True)))

    def test_expired_and_org_scoped_shares_fail_closed(self):
        expired = NoteShare.objects.create(
            note=self.note,
            shared_with_user_id=3,
            shared_by_id=1,
            permission='view',
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertFalse(can_access(3, self.note, request=_request(3, org_ids=[1])).allowed)
        expired.delete()

        share = NoteShare.objects.create(
            note=self.note,
            shared_with_user_id=3,
            shared_by_id=1,
            permission='comment',
            organization_id=7,
        )
        self.assertFalse(can_access(3, self.note, request=_request(3, org_ids=[1])).allowed)
        allowed = can_access(3, self.note, request=_request(3, org_ids=[7]))
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.role, 'comment')
        share.delete()

    def test_share_create_and_revoke_api_are_owner_only_and_audited(self):
        create_view = NoteViewSet.as_view({'post': 'shares'})
        revoke_view = NoteViewSet.as_view({'delete': 'revoke_share'})
        owner = _User(id=1, pk=1, email='owner@example.com')

        factory = APIRequestFactory()
        request = factory.post('/notes/{}/shares/'.format(self.note.id), {
            'shared_with_user_id': 4,
            'permission': 'comment',
        }, format='json')
        request.organization_id = None
        request._user_organization_ids = [1]
        force_authenticate(request, user=owner)
        response = create_view(request, pk=str(self.note.id))
        self.assertEqual(response.status_code, 201)
        share = NoteShare.objects.get(shared_with_user_id=4)
        self.assertTrue(NoteShareAudit.objects.filter(event_type='share_created', share=share).exists())
        self.assertEqual(can_access(4, self.note, request=_request(4)).role, 'comment')

        request = factory.delete('/notes/{}/shares/{}/'.format(self.note.id, share.id))
        request.organization_id = None
        request._user_organization_ids = [1]
        force_authenticate(request, user=owner)
        response = revoke_view(request, pk=str(self.note.id), share_id=str(share.id))
        self.assertEqual(response.status_code, 204)
        share.refresh_from_db()
        self.assertFalse(share.is_active)
        self.assertIsNotNone(share.revoked_at)
        self.assertEqual(share.revoked_by_id, 1)
        self.assertTrue(NoteShareAudit.objects.filter(event_type='share_revoked', share=share).exists())
        self.assertFalse(can_access(4, self.note, request=_request(4)).allowed)

    def test_comment_role_required_for_comment_creation(self):
        comments_view = NoteViewSet.as_view({'post': 'comments'})
        factory = APIRequestFactory()

        NoteShare.objects.create(note=self.note, shared_with_user_id=5, shared_by_id=1, permission='view')
        viewer = _User(id=5, pk=5, email='viewer@example.com')
        request = factory.post('/notes/{}/comments/'.format(self.note.id), {'content': 'hi'}, format='json')
        request.organization_id = None
        request._user_organization_ids = []
        force_authenticate(request, user=viewer)
        response = comments_view(request, pk=str(self.note.id))
        self.assertEqual(response.status_code, 403)

        NoteShare.objects.filter(shared_with_user_id=5).update(permission='comment')
        request = factory.post('/notes/{}/comments/'.format(self.note.id), {'content': 'hi'}, format='json')
        request.organization_id = None
        request._user_organization_ids = []
        force_authenticate(request, user=viewer)
        response = comments_view(request, pk=str(self.note.id))
        self.assertEqual(response.status_code, 201)
        self.assertTrue(NoteShareAudit.objects.filter(event_type='comment_added').exists())

    def test_notebook_notes_action_uses_note_share_predicate(self):
        view = NotebookViewSet.as_view({'get': 'notes'})
        factory = APIRequestFactory()
        peer = _User(id=2, pk=2, email='peer@example.com')

        request = factory.get('/notebooks/{}/notes/'.format(self.nb.id))
        request.organization_id = None
        request._user_organization_ids = [1]
        force_authenticate(request, user=peer)
        response = view(request, pk=str(self.nb.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data], [])

        NoteShare.objects.create(note=self.note, shared_with_user_id=2, shared_by_id=1, permission='view')
        request = factory.get('/notebooks/{}/notes/'.format(self.nb.id))
        request.organization_id = None
        request._user_organization_ids = [1]
        force_authenticate(request, user=peer)
        response = view(request, pk=str(self.nb.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data], [str(self.note.id)])

    def test_attachment_list_and_file_stream_use_note_share_predicate(self):
        attachment = Attachment.objects.create(
            note=self.note,
            file=SimpleUploadedFile('private.txt', b'secret', content_type='text/plain'),
            original_filename='private.txt',
            file_type='document',
            mime_type='text/plain',
            file_size=6,
            created_by_id=1,
        )
        list_view = AttachmentViewSet.as_view({'get': 'list'})
        file_view = AttachmentViewSet.as_view({'get': 'serve_file'})
        factory = APIRequestFactory()
        peer = _User(id=2, pk=2, email='peer@example.com')

        request = factory.get('/attachments/')
        request.organization_id = None
        request._user_organization_ids = [1]
        force_authenticate(request, user=peer)
        response = list_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])

        request = factory.get('/attachments/{}/file/'.format(attachment.id))
        request.organization_id = None
        request._user_organization_ids = [1]
        force_authenticate(request, user=peer)
        response = file_view(request, pk=str(attachment.id))
        self.assertEqual(response.status_code, 404)

        NoteShare.objects.create(note=self.note, shared_with_user_id=2, shared_by_id=1, permission='view')
        request = factory.get('/attachments/')
        request.organization_id = None
        request._user_organization_ids = [1]
        force_authenticate(request, user=peer)
        response = list_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['id'], str(attachment.id))

        request = factory.get('/attachments/{}/file/'.format(attachment.id))
        request.organization_id = None
        request._user_organization_ids = [1]
        force_authenticate(request, user=peer)
        response = file_view(request, pk=str(attachment.id))
        self.assertEqual(response.status_code, 200)

    def test_attachment_create_requires_edit_role_on_note(self):
        view = AttachmentViewSet.as_view({'post': 'create'})
        factory = APIRequestFactory()
        peer = _User(id=2, pk=2, email='peer@example.com')

        request = factory.post('/attachments/', {
            'note': str(self.note.id),
            'file': SimpleUploadedFile('blocked.txt', b'nope', content_type='text/plain'),
        }, format='multipart')
        request.organization_id = None
        request._user_organization_ids = [1]
        force_authenticate(request, user=peer)
        response = view(request)
        self.assertEqual(response.status_code, 404)

        NoteShare.objects.create(note=self.note, shared_with_user_id=2, shared_by_id=1, permission='view')
        request = factory.post('/attachments/', {
            'note': str(self.note.id),
            'file': SimpleUploadedFile('view-only.txt', b'nope', content_type='text/plain'),
        }, format='multipart')
        request.organization_id = None
        request._user_organization_ids = [1]
        force_authenticate(request, user=peer)
        response = view(request)
        self.assertEqual(response.status_code, 403)
