"""NTS-8 tests: forward-only restore, stale-restore 409, preview authz, restore-as-copy."""
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from notes.models import Notebook, Note, NoteVersion


class NoteRestoreTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='notes-restore-user',
            email='notes-restore@example.com',
            password='unused',
        )
        self.client.force_authenticate(self.user)
        self.notebook = Notebook.objects.create(
            organization_id=1,
            name='Restore',
            created_by_id=self.user.id,
        )
        self.note = Note.objects.create(
            organization_id=1,
            notebook=self.notebook,
            title='Current title',
            content_json={'type': 'doc', 'content': [{'type': 'paragraph'}]},
            content_text='current body',
            created_by_id=self.user.id,
            created_by_email=self.user.email,
            version=3,  # NTS-6 head concurrency token
        )
        for n, (title, body) in enumerate(
            [('V1 title', 'v1 body'), ('V2 title', 'v2 body'), ('Current title', 'current body')],
            start=1,
        ):
            NoteVersion.objects.create(
                note=self.note,
                title=title,
                content_json={'type': 'doc'},
                content_text=body,
                version_number=n,
                change_summary='Initial version' if n == 1 else f'Auto-saved v{n}',
                created_by_id=self.user.id,
                created_by_email=self.user.email,
            )
        self.base = f'/api/notes/{self.note.id}'
        self.org_header = {'HTTP_X_ORGANIZATION_ID': '1'}

    # ── forward-only restore ────────────────────────────────────────────────
    def test_restore_is_forward_only_and_creates_new_head_version(self):
        resp = self.client.post(
            f'{self.base}/restore-version/1/',
            {'expected_version': 3},
            format='json',
            **self.org_header,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.note.refresh_from_db()
        # live note now holds v1's content, as a NEW canonical save (version bumped)
        self.assertEqual(self.note.title, 'V1 title')
        self.assertEqual(self.note.content_text, 'v1 body')
        self.assertEqual(self.note.version, 4)
        # a NEW forward history row was appended; history was NOT mutated in place
        self.assertEqual(self.note.versions.count(), 4)
        latest = self.note.versions.order_by('-version_number').first()
        self.assertEqual(latest.version_number, 4)
        self.assertEqual(latest.change_summary, 'Restored from v1')
        self.assertEqual(latest.content_text, 'v1 body')
        # original v1 row is untouched
        self.assertEqual(self.note.versions.get(version_number=1).title, 'V1 title')

    # ── stale restore conflict ──────────────────────────────────────────────
    def test_stale_restore_returns_409_and_writes_nothing(self):
        resp = self.client.post(
            f'{self.base}/restore-version/1/',
            {'expected_version': 2},  # head is 3 → stale
            format='json',
            **self.org_header,
        )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.note.refresh_from_db()
        self.assertEqual(self.note.title, 'Current title')
        self.assertEqual(self.note.content_text, 'current body')
        self.assertEqual(self.note.version, 3)
        self.assertEqual(self.note.versions.count(), 3)  # no forward row written

    def test_restore_without_expected_version_returns_400(self):
        resp = self.client.post(
            f'{self.base}/restore-version/1/', {}, format='json', **self.org_header,
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.note.refresh_from_db()
        self.assertEqual(self.note.version, 3)
        self.assertEqual(self.note.versions.count(), 3)

    # ── preview read path + authz ───────────────────────────────────────────
    def test_version_preview_returns_historical_content_without_mutating(self):
        resp = self.client.get(f'{self.base}/versions/1/', **self.org_header)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['title'], 'V1 title')
        self.assertEqual(resp.data['content_text'], 'v1 body')
        # live note untouched by a preview
        self.note.refresh_from_db()
        self.assertEqual(self.note.title, 'Current title')
        self.assertEqual(self.note.version, 3)
        self.assertEqual(self.note.versions.count(), 3)

    def test_version_preview_denied_for_non_owner(self):
        other = get_user_model().objects.create_user(
            username='other-user', email='other@example.com', password='unused',
        )
        self.client.force_authenticate(other)
        resp = self.client.get(f'{self.base}/versions/1/', **self.org_header)
        # not in the other user's queryset (org/creator scope) → not found
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    # ── restore-as-copy ─────────────────────────────────────────────────────
    def test_restore_as_copy_creates_new_note_and_leaves_live_untouched(self):
        resp = self.client.post(
            f'{self.base}/restore-version/1/as-copy/', {}, format='json', **self.org_header,
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        # a brand-new note was created from v1's content
        self.assertEqual(resp.data['title'], 'V1 title (restored copy)')
        self.assertEqual(resp.data['content_text'], 'v1 body')
        self.assertNotEqual(str(resp.data['id']), str(self.note.id))
        self.assertEqual(Note.objects.count(), 2)
        # the live note is completely untouched
        self.note.refresh_from_db()
        self.assertEqual(self.note.title, 'Current title')
        self.assertEqual(self.note.version, 3)
        self.assertEqual(self.note.versions.count(), 3)
        # the copy carries its own seeded v1 with provenance in the summary
        copy = Note.objects.exclude(pk=self.note.pk).get()
        v1 = copy.versions.get(version_number=1)
        self.assertIn('Restored as copy', v1.change_summary)
