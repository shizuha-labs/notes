"""NTS-38: object-level authz gaps in metadata/routing paths (from the NTS-35 audit).

Complements NTS-36 (owner/share predicate on note CRUD) with the three paths that
skipped the predicate or trusted client-supplied target IDs:
  #1 GET /api/tags/{pk}/notes/  — must not leak another member's private tagged note
  #2 POST /api/notes/bulk-move/ — target notebook_id must be same-org/owned
  #3 POST /api/notes/bulk-tag/  — tag_ids must be same-org

Access-control only — NOT credential rotation (operator directive 2026-07-03).

Run: DJANGO_SETTINGS_MODULE=notes.tests.authz_ci_settings \
     python manage.py test notes.tests.test_nts38_authz_gaps
"""
from unittest.mock import patch

from django.test import TestCase, SimpleTestCase, override_settings

from notes.models import Note, Notebook, Tag, NoteShare
from notes.views import TagViewSet, BulkNoteView
from notes.tests.test_nts36_authz_invariants import _user, _nb, _note, _req

ORG = 9100          # shared org for the intra-org tag-leak test
ORG_A = 9101        # Alice's org for the bulk target-validation tests
ORG_B = 9102        # a foreign org Alice does NOT belong to
ALICE, ALICE_EMAIL = 701, 'alice@nts38.com'
BOB, BOB_EMAIL = 702, 'bob@nts38.com'
MALLORY = 999


class NTS38TagNotesLeakTests(TestCase):
    """#1: two members of the SAME org; /tags/{pk}/notes must only return the
    caller's authorized notes (owner ∪ share), never another member's private
    note that merely shares the tag."""

    def setUp(self):
        self.alice = _user(ALICE, ALICE_EMAIL)
        self.tag = Tag.objects.create(
            organization_id=ORG, name='shared', slug='shared', created_by_id=ALICE
        )
        self.bobs_note = _note(ORG, "Bob's private tagged note", BOB)
        self.bobs_note.tags.add(self.tag)
        self.alice_note = _note(ORG, "Alice's own tagged note", ALICE)
        self.alice_note.tags.add(self.tag)

    def _dispatch_notes(self):
        req = _req('get', f'/api/tags/{self.tag.id}/notes/', self.alice, (ORG,))
        with patch('notes.services.access.get_user_organization_ids', return_value=[ORG]), \
             patch('notes.views.set_organization_context'), \
             patch('notes.services.search.get_user_organization_ids', return_value=[ORG]):
            return TagViewSet.as_view({'get': 'notes'})(req, pk=str(self.tag.id))

    def test_tag_notes_excludes_other_members_private_note(self):
        resp = self._dispatch_notes()
        self.assertEqual(resp.status_code, 200)
        titles = {row.get('title') for row in resp.data}
        self.assertIn("Alice's own tagged note", titles)          # own note visible
        self.assertNotIn("Bob's private tagged note", titles)     # NTS-38 #1: no leak
        body = str(resp.data)
        self.assertNotIn("Bob's private tagged note", body)

    def test_tag_notes_includes_note_shared_with_caller(self):
        NoteShare.objects.create(note=self.bobs_note, shared_by_id=BOB,
                                 shared_with_user_id=ALICE, permission='view', is_active=True)
        resp = self._dispatch_notes()
        self.assertEqual(resp.status_code, 200)
        titles = {row.get('title') for row in resp.data}
        self.assertIn("Bob's private tagged note", titles)        # positive: share grants read


class NTS38BulkMoveTargetTests(TestCase):
    """#2: bulk-move must reject a target notebook outside the caller's org scope;
    the raw .update() previously trusted the client notebook_id."""

    def setUp(self):
        self.alice = _user(ALICE, ALICE_EMAIL)
        self.alice_note = _note(ORG_A, 'Alice movable note', ALICE)
        self.foreign_nb = _nb(ORG_B, MALLORY)  # notebook in an org Alice is not in

    def _bulk_move(self, notebook_id):
        payload = {'note_ids': [str(self.alice_note.id)], 'notebook_id': str(notebook_id)}
        req = _req('post', '/api/notes/bulk/move/', self.alice, (ORG_A,), payload)
        with patch('notes.services.search.get_user_organization_ids', return_value=[ORG_A]), \
             patch('notes.middleware.get_user_organization_ids', return_value=[ORG_A]):
            return BulkNoteView.as_view()(req, action='move')

    def test_bulk_move_rejects_cross_org_target_notebook(self):
        original_nb = self.alice_note.notebook_id
        resp = self._bulk_move(self.foreign_nb.id)
        self.assertEqual(resp.status_code, 404)                   # NTS-38 #2
        self.alice_note.refresh_from_db()
        self.assertEqual(self.alice_note.notebook_id, original_nb)  # not moved cross-org

    def test_bulk_move_allows_same_org_target(self):
        dest = _nb(ORG_A, ALICE)
        resp = self._bulk_move(dest.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data.get('moved'), 1)
        self.alice_note.refresh_from_db()
        self.assertEqual(self.alice_note.notebook_id, dest.id)


class NTS38BulkTagTargetTests(TestCase):
    """#3: bulk-tag must only attach tags within the caller's org scope; M2M
    .add() previously accepted arbitrary Tag PKs (cross-tenant tag reference)."""

    def setUp(self):
        self.alice = _user(ALICE, ALICE_EMAIL)
        self.alice_note = _note(ORG_A, 'Alice taggable note', ALICE)
        self.same_org_tag = Tag.objects.create(
            organization_id=ORG_A, name='mine', slug='mine', created_by_id=ALICE
        )
        self.foreign_tag = Tag.objects.create(
            organization_id=ORG_B, name='foreign', slug='foreign', created_by_id=MALLORY
        )

    def _bulk_tag(self, tag_ids):
        payload = {'note_ids': [str(self.alice_note.id)], 'tag_ids': [str(t) for t in tag_ids]}
        req = _req('post', '/api/notes/bulk/tag/', self.alice, (ORG_A,), payload)
        with patch('notes.services.search.get_user_organization_ids', return_value=[ORG_A]), \
             patch('notes.middleware.get_user_organization_ids', return_value=[ORG_A]):
            return BulkNoteView.as_view()(req, action='tag')

    def test_bulk_tag_rejects_cross_org_tag(self):
        resp = self._bulk_tag([self.foreign_tag.id])
        self.assertEqual(resp.status_code, 404)
        attached = set(self.alice_note.tags.values_list('id', flat=True))
        self.assertNotIn(self.foreign_tag.id, attached)           # NTS-38 #3: no cross-org tag

    def test_bulk_tag_allows_same_org_tag(self):
        resp = self._bulk_tag([self.same_org_tag.id])
        self.assertEqual(resp.status_code, 200)
        attached = set(self.alice_note.tags.values_list('id', flat=True))
        self.assertIn(self.same_org_tag.id, attached)             # positive: same-org tag attaches


class NTS38ServeMediaGateTests(SimpleTestCase):
    """#4: the unauthenticated local-media route must be registered ONLY in
    DEBUG, and must contain resolution within MEDIA_ROOT (reject `../`)."""

    @override_settings(DEBUG=False)
    def test_media_route_absent_in_production(self):
        from notes.media_serving import media_urlpatterns
        self.assertEqual(media_urlpatterns(), [])  # NTS-38 #4: no unauth route in prod

    @override_settings(DEBUG=True)
    def test_media_route_present_only_in_debug(self):
        from notes.media_serving import media_urlpatterns
        names = [getattr(p, "name", None) for p in media_urlpatterns()]
        self.assertIn("serve_media", names)

    def test_serve_media_rejects_path_traversal(self):
        from django.http import Http404
        from notes.media_serving import serve_media
        with self.assertRaises(Http404):
            serve_media(None, "../../../../etc/passwd")
