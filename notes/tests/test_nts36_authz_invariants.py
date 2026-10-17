"""NTS-36: cross-user authorization-invariant suite (object-level / IDOR).

Two users in DIFFERENT orgs; every Notes operation from User A against User B's
objects must return 403/404 and NEVER B's data — with NO share grant. Complements
NTS-18 (search/browse isolation) with the object-level endpoint (IDOR) matrix the
NTS-3 predicate (`created_by_id == caller OR active non-expired share`) must
enforce server-side on retrieve/update/delete/share/comment/version/duplicate.

THREAT: an external customer reading/modifying/deleting another user's (or an
admin's) note without an explicitly-granted permission. Access-control only — no
credential rotation (operator directive 2026-07-03).
"""
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from types import SimpleNamespace

from notes.models import Note, Notebook, Tag, NoteShare, NoteComment, NoteVersion
from notes.views import NoteViewSet, NotebookViewSet, TagViewSet, BulkNoteView

ALICE, ALICE_EMAIL, ORG_A = 501, 'alice@ext-a.com', 9001
BOB, BOB_EMAIL, ORG_B = 502, 'bob@ext-b.com', 9002


def _user(uid, email, *, admin=False):
    return SimpleNamespace(
        id=uid, pk=uid, email=email, is_authenticated=True, is_active=True,
        is_anonymous=False, is_staff=False, is_superuser=False,
        organization_role='admin' if admin else None,
        enabled_services=['notes'])


def _nb(org, user):
    return Notebook.objects.create(organization_id=org, name=f'NB-{org}-{user}',
                                   created_by_id=user)


def _note(org, title, user):
    return Note.objects.create(organization_id=org, notebook=_nb(org, user),
                               title=title, created_by_id=user,
                               content_json={'type': 'doc'})


def _active_share(note, user_id, permission='view', *, by=BOB, is_active=True, revoked_at=None):
    return NoteShare.objects.create(note=note, shared_by_id=by,
                                    shared_with_user_id=user_id, permission=permission,
                                    is_active=is_active, revoked_at=revoked_at)


def _req(method, path, user, org_ids, data=None):
    factory = APIRequestFactory()
    fn = getattr(factory, method)
    request = fn(path, data or {}, format='json')
    force_authenticate(request, user=user)
    request.user = user
    request._user_organization_ids = list(org_ids)
    request.organization_id = None
    request._pending_organization_id = None
    return request


def _dispatch(action_map, request, pk, **kw):
    with patch('notes.services.search.get_user_organization_ids',
               return_value=request._user_organization_ids), \
         patch('notes.middleware.get_user_organization_ids',
               return_value=request._user_organization_ids):
        return NoteViewSet.as_view(action_map)(request, pk=str(pk), **kw)


class CrossUserNoteAccessTests(TestCase):
    """User A (org A) against User B's (org B) note — no share. Every op → 403/404."""

    def setUp(self):
        self.alice = _user(ALICE, ALICE_EMAIL)
        self.bobs_note = _note(ORG_B, "Bob's private note", BOB)

    def _as_alice(self, method, path, data=None):
        return _req(method, path, self.alice, (ORG_A,), data)

    def _assert_denied(self, resp):
        self.assertIn(resp.status_code, (403, 404),
                      f'expected 403/404, got {resp.status_code}: {getattr(resp, "data", None)}')
        # never leak Bob's title/content
        body = str(getattr(resp, 'data', '') or '')
        self.assertNotIn("Bob's private note", body)

    def test_retrieve_denied(self):
        r = self._dispatch_get()
        self._assert_denied(r)

    def _dispatch_get(self):
        req = self._as_alice('get', f'/api/notes/{self.bobs_note.id}/')
        return _dispatch({'get': 'retrieve'}, req, self.bobs_note.id)

    def test_update_denied(self):
        req = self._as_alice('patch', f'/api/notes/{self.bobs_note.id}/', {'title': 'hacked'})
        r = _dispatch({'patch': 'partial_update'}, req, self.bobs_note.id)
        self._assert_denied(r)
        self.bobs_note.refresh_from_db()
        self.assertEqual(self.bobs_note.title, "Bob's private note")  # unchanged

    def test_delete_denied(self):
        req = self._as_alice('delete', f'/api/notes/{self.bobs_note.id}/')
        r = _dispatch({'delete': 'destroy'}, req, self.bobs_note.id)
        self._assert_denied(r)
        self.assertTrue(Note.objects.filter(id=self.bobs_note.id).exists())  # not deleted

    def test_share_denied(self):
        req = self._as_alice('post', f'/api/notes/{self.bobs_note.id}/shares/',
                             {'shared_with_email': 'mallory@x.com', 'permission': 'edit'})
        r = _dispatch({'post': 'shares'}, req, self.bobs_note.id)
        self._assert_denied(r)
        self.assertFalse(NoteShare.objects.filter(note=self.bobs_note).exists())  # no grant created

    def test_list_shares_denied(self):
        req = self._as_alice('get', f'/api/notes/{self.bobs_note.id}/shares/')
        r = _dispatch({'get': 'shares'}, req, self.bobs_note.id)
        self._assert_denied(r)

    def test_add_comment_denied(self):
        req = self._as_alice('post', f'/api/notes/{self.bobs_note.id}/comments/', {'content': 'hi'})
        r = _dispatch({'post': 'comments'}, req, self.bobs_note.id)
        self._assert_denied(r)
        self.assertFalse(NoteComment.objects.filter(note=self.bobs_note).exists())

    def test_list_comments_denied(self):
        NoteComment.objects.create(note=self.bobs_note, author_id=BOB, author_email=BOB_EMAIL, content='secret')
        req = self._as_alice('get', f'/api/notes/{self.bobs_note.id}/comments/')
        r = _dispatch({'get': 'comments'}, req, self.bobs_note.id)
        self._assert_denied(r)
        self.assertNotIn('secret', str(getattr(r, 'data', '') or ''))

    def test_versions_denied(self):
        NoteVersion.objects.create(note=self.bobs_note, version_number=1,
                                   title="Bob's private note", content_json={'type': 'doc'},
                                   created_by_id=BOB)
        req = self._as_alice('get', f'/api/notes/{self.bobs_note.id}/versions/')
        r = _dispatch({'get': 'versions'}, req, self.bobs_note.id)
        self._assert_denied(r)

    def test_restore_version_denied(self):
        NoteVersion.objects.create(note=self.bobs_note, version_number=1,
                                   title='v1', content_json={'type': 'doc'}, created_by_id=BOB)
        req = self._as_alice('post', f'/api/notes/{self.bobs_note.id}/restore-version/1/')
        r = _dispatch({'post': 'restore_version'}, req, self.bobs_note.id, version_number='1')
        self._assert_denied(r)

    def test_duplicate_denied(self):
        req = self._as_alice('post', f'/api/notes/{self.bobs_note.id}/duplicate/')
        r = _dispatch({'post': 'duplicate'}, req, self.bobs_note.id)
        self._assert_denied(r)
        # Alice did not get a copy of Bob's note in her org.
        self.assertFalse(
            Note.objects.filter(created_by_id=ALICE, title__icontains="Bob's private note").exists())

    def test_restore_from_trash_denied(self):
        self.bobs_note.status = 'trashed'
        self.bobs_note.save(update_fields=['status'])
        req = self._as_alice('post', f'/api/notes/{self.bobs_note.id}/restore/')
        r = _dispatch({'post': 'restore'}, req, self.bobs_note.id)
        self._assert_denied(r)


class CrossOrgListIsolationTests(TestCase):
    """List/bulk paths never surface another user's note to A."""

    def setUp(self):
        self.alice = _user(ALICE, ALICE_EMAIL)
        self.alice_note = _note(ORG_A, 'Alice note', ALICE)
        self.bobs_note = _note(ORG_B, "Bob's note", BOB)

    def test_list_excludes_other_users_notes(self):
        req = _req('get', '/api/notes/', self.alice, (ORG_A,))
        with patch('notes.services.search.get_user_organization_ids', return_value=[ORG_A]), \
             patch('notes.middleware.get_user_organization_ids', return_value=[ORG_A]):
            resp = NoteViewSet.as_view({'get': 'list'})(req)
        body = str(getattr(resp, 'data', '') or '')
        self.assertNotIn("Bob's note", body)

    def test_authorized_queryset_excludes_unshared_foreign_note(self):
        from notes.services.search import build_authorized_queryset
        req = _req('get', '/api/notes/', self.alice, (ORG_A,))
        with patch('notes.services.search.get_user_organization_ids', return_value=[ORG_A]):
            ids = set(build_authorized_queryset(req).values_list('id', flat=True))
        self.assertIn(self.alice_note.id, ids)
        self.assertNotIn(self.bobs_note.id, ids)


class BulkOpCrossUserTests(TestCase):
    """Bulk delete/move/tag must silently exclude notes A is not authorized on —
    a foreign note id in the payload must NOT be trashed/moved/tagged."""

    def setUp(self):
        self.alice = _user(ALICE, ALICE_EMAIL)
        self.bobs_note = _note(ORG_B, "Bob's bulk note", BOB)

    def _bulk(self, action, extra=None):
        payload = {'note_ids': [str(self.bobs_note.id)]}
        payload.update(extra or {})
        req = _req('post', f'/api/notes/bulk/{action}/', self.alice, (ORG_A,), payload)
        with patch('notes.services.search.get_user_organization_ids', return_value=[ORG_A]), \
             patch('notes.middleware.get_user_organization_ids', return_value=[ORG_A]):
            return BulkNoteView.as_view()(req, action=action)

    def test_bulk_delete_does_not_trash_foreign_note(self):
        r = self._bulk('delete')
        self.assertEqual(r.data.get('trashed'), 0)  # nothing A can touch
        self.bobs_note.refresh_from_db()
        self.assertNotEqual(self.bobs_note.status, 'trashed')

    def test_bulk_move_does_not_move_foreign_note(self):
        alice_nb = _nb(ORG_A, ALICE)
        original_nb = self.bobs_note.notebook_id
        r = self._bulk('move', {'notebook_id': str(alice_nb.id)})
        self.assertEqual(r.data.get('moved'), 0)
        self.bobs_note.refresh_from_db()
        self.assertEqual(self.bobs_note.notebook_id, original_nb)  # unmoved

    def test_bulk_tag_does_not_tag_foreign_note(self):
        r = self._bulk('tag', {'tag_ids': []})
        self.assertEqual(r.data.get('tagged'), 0)


class NotebookTagCrossAccessTests(TestCase):
    """A cannot retrieve/update/delete B's notebook or tag across the org boundary."""

    def setUp(self):
        self.alice = _user(ALICE, ALICE_EMAIL)
        self.bobs_nb = Notebook.objects.create(organization_id=ORG_B, name="Bob's NB",
                                               created_by_id=BOB)
        self.bobs_tag = Tag.objects.create(organization_id=ORG_B, name='bob-tag',
                                           slug='bob-tag')

    def _dispatch(self, viewset, action_map, pk, method, data=None):
        req = _req(method, f'/api/x/{pk}/', self.alice, (ORG_A,), data)
        with patch('notes.services.access.get_user_organization_ids', return_value=[ORG_A]), \
             patch('notes.views.set_organization_context'):
            return viewset.as_view(action_map)(req, pk=str(pk))

    def _denied(self, r):
        self.assertIn(r.status_code, (403, 404),
                      f'got {r.status_code}: {getattr(r, "data", None)}')

    def test_retrieve_foreign_notebook_denied(self):
        self._denied(self._dispatch(NotebookViewSet, {'get': 'retrieve'}, self.bobs_nb.id, 'get'))

    def test_update_foreign_notebook_denied(self):
        self._denied(self._dispatch(NotebookViewSet, {'patch': 'partial_update'},
                                    self.bobs_nb.id, 'patch', {'name': 'hijacked'}))
        self.bobs_nb.refresh_from_db()
        self.assertEqual(self.bobs_nb.name, "Bob's NB")

    def test_delete_foreign_notebook_denied(self):
        self._denied(self._dispatch(NotebookViewSet, {'delete': 'destroy'}, self.bobs_nb.id, 'delete'))
        self.assertTrue(Notebook.objects.filter(id=self.bobs_nb.id).exists())

    def test_retrieve_foreign_tag_denied(self):
        self._denied(self._dispatch(TagViewSet, {'get': 'retrieve'}, self.bobs_tag.id, 'get'))

    def test_delete_foreign_tag_denied(self):
        self._denied(self._dispatch(TagViewSet, {'delete': 'destroy'}, self.bobs_tag.id, 'delete'))
        self.assertTrue(Tag.objects.filter(id=self.bobs_tag.id).exists())


class GrantMakesItVisibleTests(TestCase):
    """Positive control: an explicit active share DOES grant A access — proving the
    negatives above are the ABSENCE of a grant, not a blanket block."""

    def setUp(self):
        self.alice = _user(ALICE, ALICE_EMAIL)
        self.bobs_note = _note(ORG_B, "Bob shares this", BOB)

    def test_active_share_grants_retrieve(self):
        _active_share(self.bobs_note, ALICE, 'view')
        req = _req('get', f'/api/notes/{self.bobs_note.id}/', self.alice, (ORG_A,))
        r = _dispatch({'get': 'retrieve'}, req, self.bobs_note.id)
        self.assertEqual(r.status_code, 200)

    def test_revoked_share_does_not_grant(self):
        from django.utils import timezone
        _active_share(self.bobs_note, ALICE, 'view', is_active=False, revoked_at=timezone.now())
        req = _req('get', f'/api/notes/{self.bobs_note.id}/', self.alice, (ORG_A,))
        r = _dispatch({'get': 'retrieve'}, req, self.bobs_note.id)
        self.assertIn(r.status_code, (403, 404))
