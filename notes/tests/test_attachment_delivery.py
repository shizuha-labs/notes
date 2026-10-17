"""Private attachments retain their owner boundary on byte delivery."""
import tempfile
from unittest.mock import patch
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from notes.models import Attachment
from notes.views import AttachmentViewSet
from notes.tests.test_nts36_authz_invariants import _note, _req, _user, ALICE, ALICE_EMAIL, BOB, BOB_EMAIL, ORG_A, ORG_B


class AttachmentDeliveryTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.payload = b'Owner-only attachment bytes'
        self.attachment = Attachment.objects.create(note=_note(ORG_A, 'Attachment owner', ALICE),
            file=SimpleUploadedFile('private.txt', self.payload), original_filename='private.txt',
            mime_type='text/plain', file_size=len(self.payload), created_by_id=ALICE)

    def request(self, user, org):
        request = _req('get', f'/api/attachments/{self.attachment.id}/file/', user, (org,))
        with patch('notes.services.access.get_user_organization_ids', return_value=[org]), \
             patch('notes.views.set_organization_context'):
            return AttachmentViewSet.as_view({'get': 'serve_file'})(request, pk=str(self.attachment.id))

    def test_owner_receives_exact_bytes_without_shared_cache_permission(self):
        response = self.request(_user(ALICE, ALICE_EMAIL), ORG_A)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), self.payload)
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        response.close()

    def test_other_tenant_cannot_fetch_attachment_by_known_uuid(self):
        response = self.request(_user(BOB, BOB_EMAIL), ORG_B)
        self.assertIn(response.status_code, (403, 404))
        self.assertNotIn(self.payload.decode(), str(getattr(response, 'data', '')))
