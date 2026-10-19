"""PLAT-11915: ?trash=true must list trashed notes, not active ones."""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from notes.models import Notebook, Note


class TrashFilterTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='trash-filter-user',
            email='trash-filter@example.com',
            password='unused',
        )
        self.client.force_authenticate(self.user)
        self.notebook = Notebook.objects.create(
            organization_id=1,
            name='Trash',
            created_by_id=self.user.id,
        )
        self.active = Note.objects.create(
            organization_id=1,
            notebook=self.notebook,
            title='Active',
            content_text='active',
            created_by_id=self.user.id,
            created_by_email=self.user.email,
        )
        self.trashed = Note.objects.create(
            organization_id=1,
            notebook=self.notebook,
            title='Gone',
            content_text='gone',
            status='trashed',
            created_by_id=self.user.id,
            created_by_email=self.user.email,
        )
        self.org = {'HTTP_X_ORGANIZATION_ID': '1'}

    def _ids(self, response):
        rows = response.data.get('results', response.data)
        return {row['id'] for row in rows}

    def test_trash_true_lists_only_trashed(self):
        response = self.client.get('/api/notes/?trash=true', **self.org)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self._ids(response)
        self.assertIn(str(self.trashed.id), ids)
        self.assertNotIn(str(self.active.id), ids)

    def test_default_list_hides_trashed(self):
        response = self.client.get('/api/notes/', **self.org)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self._ids(response)
        self.assertIn(str(self.active.id), ids)
        self.assertNotIn(str(self.trashed.id), ids)

    def test_trashed_note_is_readable_and_restorable(self):
        detail = self.client.get(f'/api/notes/{self.trashed.id}/', **self.org)
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        restored = self.client.post(f'/api/notes/{self.trashed.id}/restore/', **self.org)
        self.assertEqual(restored.status_code, status.HTTP_200_OK)
        self.trashed.refresh_from_db()
        self.assertNotEqual(self.trashed.status, 'trashed')
