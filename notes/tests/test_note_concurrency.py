"""Regression tests for NTS-6 optimistic note update concurrency."""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from notes.models import Notebook, Note, NoteVersion


class NoteOptimisticConcurrencyTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='notes-user',
            email='notes-user@example.com',
            password='unused',
        )
        self.client.force_authenticate(self.user)
        self.notebook = Notebook.objects.create(
            organization_id=1,
            name='Concurrency',
            created_by_id=self.user.id,
        )
        self.note = Note.objects.create(
            organization_id=1,
            notebook=self.notebook,
            title='Original title',
            content_json={'type': 'doc', 'content': [{'type': 'paragraph'}]},
            content_text='original body',
            created_by_id=self.user.id,
            created_by_email=self.user.email,
            version=2,
        )
        NoteVersion.objects.create(
            note=self.note,
            title=self.note.title,
            content_json=self.note.content_json,
            content_text=self.note.content_text,
            version_number=1,
            change_summary='Initial version',
            created_by_id=self.user.id,
            created_by_email=self.user.email,
        )
        self.url = f'/api/notes/{self.note.id}/'
        self.org_header = {'HTTP_X_ORGANIZATION_ID': '1'}

    def test_stale_expected_version_returns_409_without_writing_note_or_history(self):
        response = self.client.patch(
            self.url,
            {
                'expected_version': 1,
                'title': 'Stale overwrite attempt',
                'content_text': 'stale body',
            },
            format='json',
            **self.org_header,
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.note.refresh_from_db()
        self.assertEqual(self.note.title, 'Original title')
        self.assertEqual(self.note.content_text, 'original body')
        self.assertEqual(self.note.version, 2)
        self.assertEqual(self.note.versions.count(), 1)

    def test_current_expected_version_updates_and_creates_forward_history(self):
        response = self.client.patch(
            self.url,
            {
                'expected_version': 2,
                'title': 'Fresh edit',
                'content_text': 'fresh body',
            },
            format='json',
            **self.org_header,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.note.refresh_from_db()
        self.assertEqual(self.note.title, 'Fresh edit')
        self.assertEqual(self.note.content_text, 'fresh body')
        self.assertEqual(self.note.version, 3)
        self.assertEqual(response.data['version'], 3)
        self.assertEqual(self.note.versions.count(), 2)
        latest = self.note.versions.order_by('-version_number').first()
        self.assertEqual(latest.version_number, 2)
        self.assertEqual(latest.title, 'Fresh edit')
        self.assertEqual(latest.content_text, 'fresh body')

    def test_missing_expected_version_returns_400_without_writing(self):
        response = self.client.patch(
            self.url,
            {
                'title': 'Legacy write attempt',
                'content_text': 'legacy body',
            },
            format='json',
            **self.org_header,
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.note.refresh_from_db()
        self.assertEqual(self.note.title, 'Original title')
        self.assertEqual(self.note.content_text, 'original body')
        self.assertEqual(self.note.version, 2)
        self.assertEqual(self.note.versions.count(), 1)
