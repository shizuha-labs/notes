"""
NTS-9: Tests for autosave draft recovery.

Covers:
- Draft save creates a record, does NOT create a NoteVersion
- Upsert (same session_key) updates the existing draft
- Stale-base flag set when note version exceeds draft base_version
- Draft discard removes the record
- Draft copy produces a new note (live note untouched), with v1 NoteVersion
- Authz isolation: user A cannot read/modify/discard user B's draft
- Bounded retention: creating more than MAX_DRAFTS_PER_USER prunes oldest
"""
import uuid
from django.test import TestCase
from rest_framework.test import APIClient

from notes.tests.api_fixtures import configure_membership
from notes.models import Note, NoteVersion, NoteDraft, Notebook


class _UserStub:
    """Minimal user-like object for tests that use get_user_id()."""
    def __init__(self, user_id, email=''):
        self.id = user_id
        self.pk = user_id
        self.email = email
        self.is_authenticated = True


def _make_org_and_notebook(org_id=1):
    nb = Notebook.objects.create(organization_id=org_id, name=f'nb-{uuid.uuid4().hex[:6]}', created_by_id=10)
    return org_id, nb


def _make_note(org_id, notebook, user_id=1):
    note = Note.objects.create(
        organization_id=org_id,
        notebook=notebook,
        title='Test note',
        content_json={'type': 'doc', 'content': []},
        created_by_id=user_id,
    )
    NoteVersion.objects.create(
        note=note, title=note.title, content_json=note.content_json,
        version_number=1, change_summary='Initial', created_by_id=user_id,
    )
    return note


class DraftSaveTest(TestCase):
    def setUp(self):
        self.org_id, self.nb = _make_org_and_notebook()
        self.note = _make_note(self.org_id, self.nb, user_id=10)
        self.client = APIClient()
        self.client.force_authenticate(_UserStub(10, 'u10@example.com'))
        configure_membership(self, self.org_id)

    def test_post_creates_draft_not_noteversion(self):
        version_count_before = NoteVersion.objects.filter(note=self.note).count()
        resp = self.client.post(
            f'/api/notes/{self.note.id}/drafts/',
            {
                'session_key': 'session-abc',
                'title': 'Draft title',
                'content_json': {'type': 'doc', 'content': [{'type': 'paragraph'}]},
                'base_version': 1,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(NoteVersion.objects.filter(note=self.note).count(), version_count_before)
        draft = NoteDraft.objects.get(note=self.note, user_id=10, session_key='session-abc')
        self.assertEqual(draft.base_version, 1)
        self.assertFalse(resp.data['is_stale'])

    def test_upsert_updates_existing_draft(self):
        NoteDraft.objects.create(
            note=self.note, user_id=10, session_key='session-abc',
            title='Old title', content_json={}, base_version=1,
        )
        resp = self.client.post(
            f'/api/notes/{self.note.id}/drafts/',
            {'session_key': 'session-abc', 'title': 'New title',
             'content_json': {'updated': True}, 'base_version': 1},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)  # 200 = update
        self.assertEqual(resp.data['title'], 'New title')
        self.assertEqual(NoteDraft.objects.filter(note=self.note, user_id=10).count(), 1)

    def test_stale_flag_when_note_advanced(self):
        # Advance note version beyond draft base
        self.note.version = 3
        self.note.save(update_fields=['version'])
        NoteDraft.objects.create(
            note=self.note, user_id=10, session_key='stale-session',
            title='Stale draft', content_json={}, base_version=1,
        )
        resp = self.client.get(f'/api/notes/{self.note.id}/drafts/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data[0]['is_stale'])

    def test_list_returns_only_own_drafts(self):
        # Draft by user 10
        NoteDraft.objects.create(
            note=self.note, user_id=10, session_key='s1', title='', content_json={}, base_version=1,
        )
        # Draft by user 20 (different user)
        NoteDraft.objects.create(
            note=self.note, user_id=20, session_key='s1', title='', content_json={}, base_version=1,
        )
        resp = self.client.get(f'/api/notes/{self.note.id}/drafts/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        # Only user 10's draft
        self.assertNotIn(20, [d.get('user_id') for d in resp.data])


class DraftDetailTest(TestCase):
    def setUp(self):
        self.org_id, self.nb = _make_org_and_notebook()
        self.note = _make_note(self.org_id, self.nb, user_id=10)
        self.draft = NoteDraft.objects.create(
            note=self.note, user_id=10, session_key='ses',
            title='My draft', content_json={'text': 'hello'}, base_version=1,
        )
        self.client = APIClient()
        self.client.force_authenticate(_UserStub(10, 'u10@example.com'))
        configure_membership(self, self.org_id)

    def test_get_draft(self):
        resp = self.client.get(f'/api/notes/{self.note.id}/drafts/{self.draft.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['title'], 'My draft')

    def test_discard_draft(self):
        resp = self.client.delete(f'/api/notes/{self.note.id}/drafts/{self.draft.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(NoteDraft.objects.filter(id=self.draft.id).exists())

    def test_other_user_cannot_access_draft(self):
        other_client = APIClient()
        other_client.force_authenticate(_UserStub(99, 'u99@example.com'))
        resp = other_client.get(f'/api/notes/{self.note.id}/drafts/{self.draft.id}/')
        self.assertEqual(resp.status_code, 404)

    def test_other_user_cannot_delete_draft(self):
        other_client = APIClient()
        other_client.force_authenticate(_UserStub(99))
        resp = other_client.delete(f'/api/notes/{self.note.id}/drafts/{self.draft.id}/')
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(NoteDraft.objects.filter(id=self.draft.id).exists())


class DraftCopyTest(TestCase):
    def setUp(self):
        self.org_id, self.nb = _make_org_and_notebook()
        self.note = _make_note(self.org_id, self.nb, user_id=10)
        self.draft = NoteDraft.objects.create(
            note=self.note, user_id=10, session_key='ses',
            title='Draft to copy', content_json={'type': 'doc'}, base_version=1,
        )
        self.client = APIClient()
        self.client.force_authenticate(_UserStub(10, 'u10@example.com'))
        configure_membership(self, self.org_id)

    def test_copy_creates_new_note_leaves_live_note_unchanged(self):
        original_content = self.note.content_json
        original_version = self.note.version

        resp = self.client.post(f'/api/notes/{self.note.id}/drafts/{self.draft.id}/copy/')
        self.assertEqual(resp.status_code, 201)

        # New note created
        new_note = Note.objects.get(id=resp.data['id'])
        self.assertNotEqual(new_note.id, self.note.id)
        self.assertEqual(new_note.title, 'Draft to copy')
        self.assertEqual(new_note.content_json, {'type': 'doc'})
        # New note has a v1 NoteVersion
        self.assertEqual(NoteVersion.objects.filter(note=new_note, version_number=1).count(), 1)

        # Live note unchanged
        self.note.refresh_from_db()
        self.assertEqual(self.note.content_json, original_content)
        self.assertEqual(self.note.version, original_version)

    def test_other_user_cannot_copy_draft(self):
        other_client = APIClient()
        other_client.force_authenticate(_UserStub(99))
        resp = other_client.post(f'/api/notes/{self.note.id}/drafts/{self.draft.id}/copy/')
        self.assertEqual(resp.status_code, 404)


class DraftRetentionTest(TestCase):
    def setUp(self):
        self.org_id, self.nb = _make_org_and_notebook()
        self.note = _make_note(self.org_id, self.nb, user_id=10)
        self.client = APIClient()
        self.client.force_authenticate(_UserStub(10, 'u10@example.com'))
        configure_membership(self, self.org_id)

    def test_bounded_retention_prunes_oldest(self):
        # Pre-create MAX_DRAFTS_PER_USER drafts for user 10
        cap = NoteDraft.MAX_DRAFTS_PER_USER
        for i in range(cap):
            NoteDraft.objects.create(
                note=self.note, user_id=10,
                session_key=f'old-session-{i}',
                title=f'Old draft {i}', content_json={}, base_version=1,
            )
        self.assertEqual(NoteDraft.objects.filter(note=self.note, user_id=10).count(), cap)

        # Saving one more should prune the oldest
        resp = self.client.post(
            f'/api/notes/{self.note.id}/drafts/',
            {'session_key': 'new-session', 'title': 'New draft',
             'content_json': {}, 'base_version': 1},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        # Count should remain at cap
        self.assertEqual(
            NoteDraft.objects.filter(note=self.note, user_id=10).count(), cap
        )
