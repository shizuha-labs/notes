"""NTS-83 cure: no raw MinIO presigned URL may reach the browser in ANY
serialized attachment field.

Post-merge live probe FAIL receipt (cmt 1039007): the 201 attachment
response still served the raw MinIO presigned URL (in-cluster host +
``minioadmin`` credential) via the legacy ``file`` field — and the same
leak class rode on ``thumbnail`` — even after the fixed ``file_url``
correctly returned the note-scoped edge route. The serializer now aliases
the legacy keys to the credential-safe values; this suite keeps the cure
green, including the fixture that proves the detector still detects.
"""
import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from notes.models import Attachment
from notes.serializers import AttachmentSerializer
from notes.tests.test_attachment_delivery import (  # reuse the lap's fixture helpers
    ALICE,
    ALICE_EMAIL,
    ORG_A,
    _note,
    _req,
    _user,
)

# The leak markers that must never appear in a serialized attachment field.
# "minioadmin" is the storage root credential identity; the in-cluster host
# names the storage plane the browser must never see named.
LEAK_MARKERS = ("minioadmin", "minio.minio.svc.cluster.local", "X-Amz-Credential")


class NoPresignedUrlInRepresentationTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.override = override_settings(MEDIA_ROOT=self.directory.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.attachment = Attachment.objects.create(
            note=_note(ORG_A, 'Attachment rep', ALICE),
            file=SimpleUploadedFile('rep.txt', b'Attachment bytes'),
            original_filename='rep.txt',
            mime_type='text/plain',
            file_size=15,
            created_by_id=ALICE,
        )

    def serialized(self):
        request = _req('get', f'/api/attachments/{self.attachment.id}/', _user(ALICE, ALICE_EMAIL), (ORG_A,))
        return AttachmentSerializer(self.attachment, context={'request': request}).data

    def test_no_leak_marker_in_any_field(self):
        rep = self.serialized()
        for key, value in rep.items():
            for marker in LEAK_MARKERS:
                self.assertNotIn(marker, str(value), f"field {key!r} leaked a raw storage marker")

    def test_legacy_file_key_is_aliased_to_edge_route(self):
        rep = self.serialized()
        self.assertEqual(rep['file'], rep['file_url'])
        self.assertIn('/api/attachments/', rep['file'])
        self.assertNotIn('X-Amz-', rep['file'])

    def test_legacy_thumbnail_key_is_aliased_to_server_safe_route(self):
        rep = self.serialized()
        self.assertEqual(rep['thumbnail'], rep['thumbnail_url'])
