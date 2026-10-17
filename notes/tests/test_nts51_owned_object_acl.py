"""NTS-51: same-org IDOR + relation-injection + break-glass invariants.

The NTS-36 suite proves cross-ORG isolation (Bob in ORG_B), so it structurally
cannot catch the P1s ichi found: SAME-ORG User A reaching User B's notebook/tag,
serializer relation injection, org-scoped trash empty, and audited admin
break-glass. These fixtures put Alice and Carol in the SAME org.

Contract (NTS-34 / ichi ruling): notes, notebooks, and tags are per-user data —
owner | explicit share | audited admin break-glass, org-partitioned.
"""

from notes.tests.api_fixtures import response_items
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.db import connection
import unittest
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from types import SimpleNamespace

from notes.models import (
    AccessAudit, Note, Notebook, NoteDraft, NoteShare, NoteVersion,
    OwnedObjectShare, Tag,
)
from django.core.files.uploadedfile import SimpleUploadedFile
from notes.views import (
    AttachmentViewSet, BulkNoteView, NoteViewSet, NotebookViewSet, TagViewSet, TrashView,
)

ORG_A = 9101
ORG_OTHER = 9102
ALICE, ALICE_EMAIL = 601, 'alice@org-a.com'
CAROL, CAROL_EMAIL = 602, 'carol@org-a.com'   # same org as Alice
BOB, BOB_EMAIL = 603, 'bob@org-other.com'     # different org
ADA, ADA_EMAIL = 604, 'ada@org-a.com'         # org-A admin


def _user(uid, email, *, admin=False, superuser=False):
    return SimpleNamespace(
        id=uid, pk=uid, email=email, is_authenticated=True, is_active=True,
        is_anonymous=False, is_staff=False, is_superuser=superuser,
        organization_role='admin' if admin else None,
        enabled_services=['notes'])


def _nb(org, user, name=None):
    return Notebook.objects.create(organization_id=org, name=name or f'NB-{org}-{user}',
                                   created_by_id=user)


def _tag(org, user, name=None):
    return Tag.objects.create(organization_id=org, name=name or f'TG-{org}-{user}',
                              slug=f'tg-{org}-{user}', created_by_id=user)


def _note(org, title, user, notebook=None):
    return Note.objects.create(organization_id=org, notebook=notebook or _nb(org, user),
                               title=title, created_by_id=user, content_json={'type': 'doc'})


def _grant(obj, user=ALICE, permission='view', **kwargs):
    return OwnedObjectShare.objects.create(
        object_type='notebook' if isinstance(obj, Notebook) else 'tag',
        object_id=obj.id,
        organization_id=obj.organization_id,
        shared_with_user_id=user,
        permission=permission,
        shared_by_id=getattr(obj, 'created_by_id', CAROL) or CAROL,
        **kwargs,
    )


def _req(method, path, user, org, org_ids=None, data=None, fmt='json'):
    request = getattr(APIRequestFactory(), method)(path, data or {}, format=fmt)
    force_authenticate(request, user=user)
    request.user = user
    request._org_ids = list(org_ids if org_ids is not None else [org])
    request.organization_id = org
    request._pending_organization_id = org
    return request


def _dispatch(viewset, action_map, request, pk=None, **kw):
    with patch('notes.services.search.get_user_organization_ids', return_value=request._org_ids), \
         patch('notes.middleware.get_user_organization_ids', return_value=request._org_ids), \
         patch('notes.middleware.set_organization_context', lambda r: None):
        view = viewset.as_view(action_map)
        return view(request, pk=str(pk), **kw) if pk is not None else view(request, **kw)


class SameOrgNotebookTagIDOR(TestCase):
    def test_same_org_user_cannot_retrieve_others_notebook(self):
        nb = _nb(ORG_A, CAROL)
        resp = _dispatch(NotebookViewSet, {'get': 'retrieve'},
                         _req('get', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A), pk=nb.id)
        self.assertEqual(resp.status_code, 404)

    def test_same_org_user_cannot_update_others_notebook(self):
        nb = _nb(ORG_A, CAROL, name='carol-secret')
        resp = _dispatch(NotebookViewSet, {'patch': 'partial_update'},
                         _req('patch', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A,
                              data={'name': 'hijacked'}), pk=nb.id)
        self.assertIn(resp.status_code, (403, 404))
        nb.refresh_from_db()
        self.assertEqual(nb.name, 'carol-secret')

    def test_same_org_user_cannot_delete_others_tag(self):
        tag = _tag(ORG_A, CAROL)
        resp = _dispatch(TagViewSet, {'delete': 'destroy'},
                         _req('delete', '/api/tags/', _user(ALICE, ALICE_EMAIL), ORG_A), pk=tag.id)
        self.assertIn(resp.status_code, (403, 404))
        self.assertTrue(Tag.objects.filter(pk=tag.id).exists())

    def test_notebook_list_excludes_same_org_others(self):
        mine = _nb(ORG_A, ALICE)
        _nb(ORG_A, CAROL)
        resp = _dispatch(NotebookViewSet, {'get': 'list'},
                         _req('get', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A))
        self.assertEqual(resp.status_code, 200)
        ids = {n['id'] for n in response_items(resp)}
        self.assertEqual(ids, {str(mine.id)})

    def test_tag_list_excludes_same_org_others(self):
        mine = _tag(ORG_A, ALICE)
        _tag(ORG_A, CAROL)
        resp = _dispatch(TagViewSet, {'get': 'list'},
                         _req('get', '/api/tags/', _user(ALICE, ALICE_EMAIL), ORG_A))
        self.assertEqual(resp.status_code, 200)
        ids = {t['id'] for t in response_items(resp)}
        self.assertEqual(ids, {str(mine.id)})

    def test_tree_excludes_foreign_children_and_private_note_counts(self):
        mine = _nb(ORG_A, ALICE, name='mine-root')
        Notebook.objects.create(
            organization_id=ORG_A,
            name='carol-child',
            parent=mine,
            created_by_id=CAROL,
        )
        _note(ORG_A, 'carol-private', CAROL, notebook=mine)
        response = _dispatch(
            NotebookViewSet,
            {'get': 'tree'},
            _req('get', '/api/notebooks/tree/', _user(ALICE, ALICE_EMAIL), ORG_A),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['id'], str(mine.id))
        self.assertEqual(response.data[0]['children'], [])
        self.assertEqual(response.data[0]['note_count'], 0)
        self.assertEqual(response.data[0]['total_note_count'], 0)


class SerializerRelationInjection(TestCase):
    def test_note_create_rejects_same_org_foreign_tag(self):
        carol_tag = _tag(ORG_A, CAROL)
        alice_nb = _nb(ORG_A, ALICE)
        resp = _dispatch(NoteViewSet, {'post': 'create'},
                         _req('post', '/api/notes/', _user(ALICE, ALICE_EMAIL), ORG_A,
                              data={'title': 'x', 'notebook': str(alice_nb.id),
                                    'tags': [str(carol_tag.id)], 'content_json': {'type': 'doc'}}))
        self.assertEqual(resp.status_code, 400)

    def test_note_create_rejects_cross_org_notebook(self):
        bob_nb = _nb(ORG_OTHER, BOB)
        resp = _dispatch(NoteViewSet, {'post': 'create'},
                         _req('post', '/api/notes/', _user(ALICE, ALICE_EMAIL), ORG_A,
                              data={'title': 'x', 'notebook': str(bob_nb.id),
                                    'content_json': {'type': 'doc'}}))
        self.assertEqual(resp.status_code, 400)

    def test_note_update_rejects_same_org_foreign_tag(self):
        note = _note(ORG_A, 'mine', ALICE)
        carol_tag = _tag(ORG_A, CAROL)
        resp = _dispatch(NoteViewSet, {'patch': 'partial_update'},
                         _req('patch', '/api/notes/', _user(ALICE, ALICE_EMAIL), ORG_A,
                              data={'tags': [str(carol_tag.id)]}), pk=note.id)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(note.tags.count(), 0)

    def test_note_create_accepts_own_tag(self):
        my_tag = _tag(ORG_A, ALICE)
        my_nb = _nb(ORG_A, ALICE)
        resp = _dispatch(NoteViewSet, {'post': 'create'},
                         _req('post', '/api/notes/', _user(ALICE, ALICE_EMAIL), ORG_A,
                              data={'title': 'ok', 'notebook': str(my_nb.id),
                                    'tags': [str(my_tag.id)], 'content_json': {'type': 'doc'}}))
        self.assertEqual(resp.status_code, 201)

    def test_cross_org_edit_share_cannot_repoint_note_to_selected_org_notebook(self):
        foreign_note = _note(ORG_OTHER, 'carol-org-other', CAROL)
        NoteShare.objects.create(
            note=foreign_note,
            shared_with_user_id=ALICE,
            shared_by_id=CAROL,
            organization_id=ORG_A,
            permission='edit',
        )
        selected_org_notebook = _nb(ORG_A, ALICE, name='alice-selected-org')

        resp = _dispatch(
            NoteViewSet,
            {'patch': 'partial_update'},
            _req(
                'patch', '/api/notes/', _user(ALICE, ALICE_EMAIL), ORG_A,
                data={
                    'notebook': str(selected_org_notebook.id),
                    'expected_version': foreign_note.version,
                },
            ),
            pk=foreign_note.id,
        )

        self.assertEqual(resp.status_code, 400)
        foreign_note.refresh_from_db()
        self.assertEqual(foreign_note.organization_id, ORG_OTHER)
        self.assertNotEqual(foreign_note.notebook_id, selected_org_notebook.id)

    def test_cross_org_edit_share_cannot_attach_selected_org_tag(self):
        foreign_note = _note(ORG_OTHER, 'carol-org-other', CAROL)
        NoteShare.objects.create(
            note=foreign_note,
            shared_with_user_id=ALICE,
            shared_by_id=CAROL,
            organization_id=ORG_A,
            permission='edit',
        )
        selected_org_tag = _tag(ORG_A, ALICE, name='alice-selected-org-tag')

        resp = _dispatch(
            NoteViewSet,
            {'patch': 'partial_update'},
            _req(
                'patch', '/api/notes/', _user(ALICE, ALICE_EMAIL), ORG_A,
                data={
                    'tags': [str(selected_org_tag.id)],
                    'expected_version': foreign_note.version,
                },
            ),
            pk=foreign_note.id,
        )

        self.assertEqual(resp.status_code, 400)
        foreign_note.refresh_from_db()
        self.assertEqual(foreign_note.organization_id, ORG_OTHER)
        self.assertFalse(foreign_note.tags.filter(pk=selected_org_tag.id).exists())


class CopyDestinationAuthorization(TestCase):
    """Every copy endpoint authorizes its implicit notebook/tag destination."""

    def _edit_share(self, note):
        return NoteShare.objects.create(
            note=note,
            shared_with_user_id=ALICE,
            shared_by_id=CAROL,
            organization_id=ORG_A,
            permission='edit',
        )

    def test_duplicate_denies_private_source_notebook_destination(self):
        private_notebook = _nb(ORG_A, CAROL, name='carol-private-destination')
        note = _note(ORG_A, 'shared note', CAROL, notebook=private_notebook)
        self._edit_share(note)

        resp = _dispatch(
            NoteViewSet,
            {'post': 'duplicate'},
            _req('post', '/api/notes/duplicate/', _user(ALICE, ALICE_EMAIL), ORG_A),
            pk=note.id,
        )

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(Note.objects.filter(
            created_by_id=ALICE, title='shared note (Copy)'
        ).exists())

    def test_duplicate_rolls_back_note_when_tag_copy_fails(self):
        notebook = _nb(ORG_A, ALICE, name='alice-destination')
        note = _note(ORG_A, 'shared note', CAROL, notebook=notebook)
        tag = _tag(ORG_A, ALICE, name='alice-tag')

        with patch.object(type(note.tags), 'set', side_effect=RuntimeError('tag write failed')):
            with self.assertRaises(RuntimeError):
                note.duplicate(user_id=ALICE, notebook=notebook, tags=[tag])

        self.assertFalse(Note.objects.filter(
            created_by_id=ALICE, title='shared note (Copy)'
        ).exists())

    def test_restore_as_copy_denies_private_source_tag_destination(self):
        notebook = _nb(ORG_A, CAROL, name='carol-shared-destination')
        private_tag = _tag(ORG_A, CAROL, name='carol-private-tag')
        note = _note(ORG_A, 'shared note', CAROL, notebook=notebook)
        note.tags.add(private_tag)
        _grant(notebook, user=ALICE, permission='edit')
        self._edit_share(note)
        NoteVersion.objects.create(
            note=note,
            title='historical title',
            content_json={'type': 'doc'},
            content_text='historical content',
            version_number=1,
            created_by_id=CAROL,
        )

        resp = _dispatch(
            NoteViewSet,
            {'post': 'restore_version_as_copy'},
            _req('post', '/api/notes/restore-as-copy/', _user(ALICE, ALICE_EMAIL), ORG_A),
            pk=note.id,
            version_number='1',
        )

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(Note.objects.filter(
            created_by_id=ALICE, title='historical title (restored copy)'
        ).exists())

    def test_draft_copy_denies_private_source_notebook_destination(self):
        private_notebook = _nb(ORG_A, CAROL, name='carol-private-destination')
        note = _note(ORG_A, 'shared note', CAROL, notebook=private_notebook)
        self._edit_share(note)
        draft = NoteDraft.objects.create(
            note=note,
            user_id=ALICE,
            session_key='alice-session',
            title='alice draft',
            content_json={'type': 'doc'},
            base_version=note.version,
        )

        resp = _dispatch(
            NoteViewSet,
            {'post': 'draft_copy'},
            _req('post', '/api/notes/draft-copy/', _user(ALICE, ALICE_EMAIL), ORG_A),
            pk=note.id,
            draft_id=str(draft.id),
        )

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(Note.objects.filter(
            created_by_id=ALICE, title='alice draft'
        ).exists())


class ExplicitOwnedObjectShares(TestCase):
    def test_view_grant_lists_and_retrieves_but_cannot_mutate(self):
        nb = _nb(ORG_A, CAROL, name='shared-view')
        _grant(nb, permission='view')

        list_resp = _dispatch(
            NotebookViewSet,
            {'get': 'list'},
            _req('get', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A),
        )
        self.assertIn(str(nb.id), {item['id'] for item in response_items(list_resp)})
        get_resp = _dispatch(
            NotebookViewSet,
            {'get': 'retrieve'},
            _req('get', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A),
            pk=nb.id,
        )
        self.assertEqual(get_resp.status_code, 200)

        patch_resp = _dispatch(
            NotebookViewSet,
            {'patch': 'partial_update'},
            _req(
                'patch', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A,
                data={'name': 'must-not-change'},
            ),
            pk=nb.id,
        )
        self.assertEqual(patch_resp.status_code, 404)
        nb.refresh_from_db()
        self.assertEqual(nb.name, 'shared-view')

    def test_edit_grants_are_accepted_by_relation_inputs(self):
        nb = _nb(ORG_A, CAROL)
        tag = _tag(ORG_A, CAROL)
        _grant(nb, permission='edit')
        _grant(tag, permission='edit')
        response = _dispatch(
            NoteViewSet,
            {'post': 'create'},
            _req(
                'post', '/api/notes/', _user(ALICE, ALICE_EMAIL), ORG_A,
                data={
                    'title': 'shared-container-note',
                    'notebook': str(nb.id),
                    'tags': [str(tag.id)],
                    'content_json': {'type': 'doc'},
                },
            ),
        )
        self.assertEqual(response.status_code, 201)

    def test_revoked_and_expired_grants_fail_closed(self):
        revoked = _nb(ORG_A, CAROL, name='revoked')
        expired = _nb(ORG_A, CAROL, name='expired')
        _grant(revoked, revoked_at=timezone.now())
        _grant(expired, expires_at=timezone.now() - timedelta(seconds=1))
        response = _dispatch(
            NotebookViewSet,
            {'get': 'list'},
            _req('get', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A),
        )
        ids = {item['id'] for item in response_items(response)}
        self.assertNotIn(str(revoked.id), ids)
        self.assertNotIn(str(expired.id), ids)


class SelectedOrganizationPartition(TestCase):
    def test_selected_org_does_not_widen_to_other_memberships(self):
        own_a = _nb(ORG_A, ALICE, name='a')
        own_other = _nb(ORG_OTHER, ALICE, name='other')
        request = _req(
            'get', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A,
            org_ids=[ORG_A, ORG_OTHER],
        )
        response = _dispatch(NotebookViewSet, {'get': 'list'}, request)
        self.assertEqual({item['id'] for item in response_items(response)}, {str(own_a.id)})

        detail = _dispatch(
            NotebookViewSet,
            {'get': 'retrieve'},
            _req(
                'get', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A,
                org_ids=[ORG_A, ORG_OTHER],
            ),
            pk=own_other.id,
        )
        self.assertEqual(detail.status_code, 404)

    def test_selected_org_rejects_other_membership_relation(self):
        other_nb = _nb(ORG_OTHER, ALICE)
        response = _dispatch(
            NoteViewSet,
            {'post': 'create'},
            _req(
                'post', '/api/notes/', _user(ALICE, ALICE_EMAIL), ORG_A,
                org_ids=[ORG_A, ORG_OTHER],
                data={
                    'title': 'wrong workspace',
                    'notebook': str(other_nb.id),
                    'content_json': {'type': 'doc'},
                },
            ),
        )
        self.assertEqual(response.status_code, 400)

    def test_can_access_denies_owned_note_in_other_selected_workspace(self):
        # revi round-5 P1 (direct predicate): an owner leg must NOT bypass the
        # selected-org partition. Alice owns a note in ORG_OTHER but is selected
        # into ORG_A — can_access must fail closed even though she owns it.
        from notes.services.access import can_access
        other_note = _note(ORG_OTHER, 'owned-elsewhere', ALICE)
        request = _req(
            'get', '/api/notes/', _user(ALICE, ALICE_EMAIL), ORG_A,
            org_ids=[ORG_A, ORG_OTHER])
        self.assertFalse(can_access(ALICE, other_note, request=request).allowed)
        # Sanity: the same owner is allowed when SELECTED into that note's own
        # workspace (the partition gates cross-workspace, not the owner leg itself).
        in_workspace = _req('get', '/api/notes/', _user(ALICE, ALICE_EMAIL), ORG_OTHER,
                            org_ids=[ORG_OTHER])
        self.assertTrue(can_access(ALICE, other_note, request=in_workspace).allowed)

    def test_attachment_create_denied_on_owned_note_in_other_workspace(self):
        # revi round-5 P1 (endpoint): POSTing an attachment to a cross-selected-org
        # owned note must NOT persist (previously returned 201).
        from notes.models import Attachment
        other_note = _note(ORG_OTHER, 'owned-elsewhere', ALICE)
        request = _req(
            'post', '/api/attachments/', _user(ALICE, ALICE_EMAIL), ORG_A,
            org_ids=[ORG_A, ORG_OTHER],
            data={'note': str(other_note.id),
                  'file': SimpleUploadedFile('x.txt', b'x', content_type='text/plain')},
            fmt='multipart')
        response = _dispatch(AttachmentViewSet, {'post': 'create'}, request)
        self.assertNotIn(response.status_code, (200, 201))
        self.assertEqual(Attachment.objects.filter(note=other_note).count(), 0)

    def test_selected_org_scopes_tag_list_and_detail(self):
        own_a = _tag(ORG_A, ALICE, name='tag-a')
        own_other = _tag(ORG_OTHER, ALICE, name='tag-other')
        response = _dispatch(
            TagViewSet,
            {'get': 'list'},
            _req(
                'get', '/api/tags/', _user(ALICE, ALICE_EMAIL), ORG_A,
                org_ids=[ORG_A, ORG_OTHER],
            ),
        )
        self.assertEqual({item['id'] for item in response_items(response)}, {str(own_a.id)})
        detail = _dispatch(
            TagViewSet,
            {'get': 'retrieve'},
            _req(
                'get', '/api/tags/', _user(ALICE, ALICE_EMAIL), ORG_A,
                org_ids=[ORG_A, ORG_OTHER],
            ),
            pk=own_other.id,
        )
        self.assertEqual(detail.status_code, 404)

    def test_selected_org_rejects_other_membership_tag_relation(self):
        note = _note(ORG_A, 'workspace-a', ALICE)
        other_tag = _tag(ORG_OTHER, ALICE)
        response = _dispatch(
            NoteViewSet,
            {'patch': 'partial_update'},
            _req(
                'patch', '/api/notes/', _user(ALICE, ALICE_EMAIL), ORG_A,
                org_ids=[ORG_A, ORG_OTHER], data={'tags': [str(other_tag.id)]},
            ),
            pk=note.id,
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(note.tags.exists())

    def test_selected_org_blocks_cross_workspace_break_glass(self):
        other_nb = _nb(ORG_OTHER, CAROL)
        response = _dispatch(
            NotebookViewSet,
            {'get': 'retrieve'},
            _req(
                'get', '/api/notebooks/', _user(ADA, ADA_EMAIL, admin=True), ORG_A,
                org_ids=[ORG_A, ORG_OTHER],
            ),
            pk=other_nb.id,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(AccessAudit.objects.count(), 0)


class AdminBreakGlass(TestCase):
    def test_admin_retrieves_org_notebook_with_audit(self):
        nb = _nb(ORG_A, CAROL)
        self.assertEqual(AccessAudit.objects.count(), 0)
        resp = _dispatch(NotebookViewSet, {'get': 'retrieve'},
                         _req('get', '/api/notebooks/', _user(ADA, ADA_EMAIL, admin=True), ORG_A), pk=nb.id)
        self.assertEqual(resp.status_code, 200)
        audits = AccessAudit.objects.filter(object_type='notebook', object_id=str(nb.id))
        self.assertEqual(audits.count(), 1)
        self.assertEqual(audits.first().decision, 'allow')
        self.assertEqual(audits.first().actor_id, ADA)

    def test_break_glass_denied_when_audit_cannot_persist(self):
        nb = _nb(ORG_A, CAROL)
        with patch('notes.models.AccessAudit.objects.create', side_effect=Exception('db down')):
            resp = _dispatch(NotebookViewSet, {'get': 'retrieve'},
                             _req('get', '/api/notebooks/', _user(ADA, ADA_EMAIL, admin=True), ORG_A), pk=nb.id)
        self.assertEqual(resp.status_code, 404)

    def test_owner_access_is_not_audited(self):
        nb = _nb(ORG_A, ALICE)
        resp = _dispatch(NotebookViewSet, {'get': 'retrieve'},
                         _req('get', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A), pk=nb.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(AccessAudit.objects.count(), 0)

    def test_note_break_glass_via_can_access_is_audited(self):
        # Note CONTENT stays owner∪share on the API surface (NTS-3 hard rule);
        # admin access is an EXPLICIT audited break-glass through the helper
        # ichi's P1-#4 names — not ambient API read. Prove it at that helper.
        from notes.services.access import can_access
        note = _note(ORG_A, 'carol-note', CAROL)
        req = _req('get', '/api/notes/', _user(ADA, ADA_EMAIL, admin=True), ORG_A)
        with patch('notes.middleware.get_user_organization_ids', return_value=[ORG_A]):
            decision = can_access(req.user, note, request=req)
        self.assertTrue(decision.allowed)
        self.assertEqual(
            AccessAudit.objects.filter(object_type='note', object_id=str(note.id), decision='allow').count(), 1)

    def test_note_break_glass_denied_when_audit_fails(self):
        from notes.services.access import can_access
        note = _note(ORG_A, 'carol-note', CAROL)
        req = _req('get', '/api/notes/', _user(ADA, ADA_EMAIL, admin=True), ORG_A)
        with patch('notes.middleware.get_user_organization_ids', return_value=[ORG_A]), \
             patch('notes.models.AccessAudit.objects.create', side_effect=Exception('db down')):
            decision = can_access(req.user, note, request=req)
        self.assertFalse(decision.allowed)

    def test_non_admin_gets_no_note_break_glass(self):
        from notes.services.access import can_access
        note = _note(ORG_A, 'carol-note', CAROL)
        req = _req('get', '/api/notes/', _user(ALICE, ALICE_EMAIL), ORG_A)
        with patch('notes.middleware.get_user_organization_ids', return_value=[ORG_A]):
            decision = can_access(req.user, note, request=req)
        self.assertFalse(decision.allowed)


class TrashOrgScope(TestCase):
    def test_empty_trash_only_touches_authorized_in_scope_notes(self):
        from notes.views import TrashView
        # Alice owns a trashed note in ORG_A and one in ORG_OTHER (multi-org owner).
        a = _note(ORG_A, 'a-trash', ALICE); a.status = 'trashed'; a.save()
        other = _note(ORG_OTHER, 'other-trash', ALICE); other.status = 'trashed'; other.save()
        # Carol's trashed note in ORG_A must never be deleted by Alice.
        carol = _note(ORG_A, 'carol-trash', CAROL); carol.status = 'trashed'; carol.save()
        req = _req('delete', '/api/trash/', _user(ALICE, ALICE_EMAIL), ORG_A, org_ids=[ORG_A])
        with patch('notes.services.search.get_user_organization_ids', return_value=[ORG_A]), \
             patch('notes.middleware.get_user_organization_ids', return_value=[ORG_A]):
            resp = TrashView.as_view()(req)
        self.assertEqual(resp.status_code, 200)
        # Only Alice's ORG_A note deleted; her ORG_OTHER note and Carol's survive.
        self.assertFalse(Note.objects.filter(pk=a.id).exists())
        self.assertTrue(Note.objects.filter(pk=other.id).exists())
        self.assertTrue(Note.objects.filter(pk=carol.id).exists())

    def test_empty_trash_never_deletes_a_shared_note(self):
        own = _note(ORG_A, 'own-trash', ALICE); own.status = 'trashed'; own.save()
        shared = _note(ORG_A, 'shared-trash', CAROL); shared.status = 'trashed'; shared.save()
        NoteShare.objects.create(
            note=shared,
            shared_with_user_id=ALICE,
            shared_by_id=CAROL,
            organization_id=ORG_A,
            permission='edit',
        )
        request = _req('delete', '/api/trash/', _user(ALICE, ALICE_EMAIL), ORG_A)
        with patch('notes.services.search.get_user_organization_ids', return_value=[ORG_A]), \
             patch('notes.middleware.get_user_organization_ids', return_value=[ORG_A]):
            response = TrashView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Note.objects.filter(pk=own.id).exists())
        self.assertTrue(Note.objects.filter(pk=shared.id).exists())


class BulkTargetAuthorization(TestCase):
    def _bulk(self, action, data):
        request = _req(
            'post', f'/api/notes/bulk-{action}/',
            _user(ALICE, ALICE_EMAIL), ORG_A, data=data,
        )
        with patch('notes.services.search.get_user_organization_ids', return_value=[ORG_A]), \
             patch('notes.middleware.get_user_organization_ids', return_value=[ORG_A]):
            return BulkNoteView.as_view()(request, action=action)

    def test_bulk_move_rejects_same_org_foreign_notebook(self):
        source_nb = _nb(ORG_A, ALICE, name='source')
        foreign_nb = _nb(ORG_A, CAROL, name='foreign')
        note = _note(ORG_A, 'mine', ALICE, notebook=source_nb)
        response = self._bulk('move', {
            'note_ids': [str(note.id)], 'notebook_id': str(foreign_nb.id),
        })
        self.assertEqual(response.status_code, 404)
        note.refresh_from_db()
        self.assertEqual(note.notebook_id, source_nb.id)

    def test_bulk_tag_rejects_same_org_foreign_tag(self):
        note = _note(ORG_A, 'mine', ALICE)
        foreign_tag = _tag(ORG_A, CAROL)
        response = self._bulk('tag', {
            'note_ids': [str(note.id)], 'tag_ids': [str(foreign_tag.id)],
        })
        self.assertEqual(response.status_code, 404)
        self.assertFalse(note.tags.filter(pk=foreign_tag.id).exists())

    def test_bulk_targets_accept_edit_grants(self):
        source_nb = _nb(ORG_A, ALICE, name='source')
        shared_nb = _nb(ORG_A, CAROL, name='shared-destination')
        shared_tag = _tag(ORG_A, CAROL)
        _grant(shared_nb, permission='edit')
        _grant(shared_tag, permission='edit')
        note = _note(ORG_A, 'mine', ALICE, notebook=source_nb)

        moved = self._bulk('move', {
            'note_ids': [str(note.id)], 'notebook_id': str(shared_nb.id),
        })
        self.assertEqual(moved.status_code, 200)
        note.refresh_from_db()
        self.assertEqual(note.notebook_id, shared_nb.id)

        tagged = self._bulk('tag', {
            'note_ids': [str(note.id)], 'tag_ids': [str(shared_tag.id)],
        })
        self.assertEqual(tagged.status_code, 200)
        self.assertTrue(note.tags.filter(pk=shared_tag.id).exists())


class NTS51ReviewP5CascadeDelete(TestCase):
    """revi PR#5 P1: an edit share on a notebook must not let the sharee CASCADE-
    delete contained notes they cannot edit (Note.notebook on_delete=CASCADE)."""

    def test_edit_share_cannot_cascade_delete_unshared_note(self):
        nb = _nb(ORG_A, CAROL, name='carol-nb')
        private = _note(ORG_A, 'carol-private', CAROL, notebook=nb)
        _grant(nb, user=ALICE, permission='edit')  # Alice: edit share on the notebook
        resp = _dispatch(NotebookViewSet, {'delete': 'destroy'},
                         _req('delete', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A), pk=nb.id)
        self.assertIn(resp.status_code, (403, 404))
        self.assertTrue(Note.objects.filter(pk=private.id).exists(), 'private note cascade-deleted')
        self.assertTrue(Notebook.objects.filter(pk=nb.id).exists())

    def test_edit_share_cannot_cascade_delete_via_descendant(self):
        root = _nb(ORG_A, CAROL, name='carol-root')
        child = Notebook.objects.create(organization_id=ORG_A, name='carol-child',
                                        parent=root, created_by_id=CAROL)
        private = _note(ORG_A, 'deep-private', CAROL, notebook=child)
        _grant(root, user=ALICE, permission='edit')
        resp = _dispatch(NotebookViewSet, {'delete': 'destroy'},
                         _req('delete', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A), pk=root.id)
        self.assertIn(resp.status_code, (403, 404))
        self.assertTrue(Note.objects.filter(pk=private.id).exists())

    def test_edit_share_cannot_cascade_delete_unshared_descendant_notebook(self):
        # revi round 2 P1(a): an EMPTY unshared child notebook (no notes) must not be
        # cascade-deleted via an edit share on the root — perform_destroy previously
        # authorized only contained NOTES, so an empty child passed.
        root = _nb(ORG_A, CAROL, name='carol-root')
        child = Notebook.objects.create(organization_id=ORG_A, name='carol-empty-child',
                                        parent=root, created_by_id=CAROL)
        _grant(root, user=ALICE, permission='edit')
        resp = _dispatch(NotebookViewSet, {'delete': 'destroy'},
                         _req('delete', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A), pk=root.id)
        self.assertIn(resp.status_code, (403, 404))
        self.assertTrue(Notebook.objects.filter(pk=child.id).exists(),
                        'unshared descendant notebook cascade-deleted')

    def test_edit_share_cannot_cascade_delete_archived_descendant_note(self):
        # revi round 2 P1(b): an ARCHIVED child (omitted by get_descendants) containing
        # a private note must still be authorized — the DB FK cascade deletes it
        # regardless of the is_archived filter.
        root = _nb(ORG_A, CAROL, name='carol-root')
        archived = Notebook.objects.create(organization_id=ORG_A, name='carol-archived',
                                           parent=root, created_by_id=CAROL, is_archived=True)
        private = _note(ORG_A, 'archived-private', CAROL, notebook=archived)
        _grant(root, user=ALICE, permission='edit')
        resp = _dispatch(NotebookViewSet, {'delete': 'destroy'},
                         _req('delete', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A), pk=root.id)
        self.assertIn(resp.status_code, (403, 404))
        self.assertTrue(Note.objects.filter(pk=private.id).exists(),
                        'archived descendant private note cascade-deleted')
        self.assertTrue(Notebook.objects.filter(pk=archived.id).exists())

    def test_owner_can_delete_own_notebook_with_own_notes(self):
        nb = _nb(ORG_A, CAROL, name='carol-own')
        note = _note(ORG_A, 'carol-note', CAROL, notebook=nb)
        resp = _dispatch(NotebookViewSet, {'delete': 'destroy'},
                         _req('delete', '/api/notebooks/', _user(CAROL, CAROL_EMAIL), ORG_A), pk=nb.id)
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Notebook.objects.filter(pk=nb.id).exists())
        self.assertFalse(Note.objects.filter(pk=note.id).exists())

    def test_admin_break_glass_can_cascade_delete_with_audit(self):
        # revi round 3: an AUDITED admin break-glass MUST be able to cascade-delete a
        # notebook containing foreign descendants/notes — the guard authorizes through
        # the full owner ∪ share ∪ audited break-glass predicate (can_access_owned /
        # can_access), not owner/share only (which excluded break-glass and 403'd).
        root = _nb(ORG_A, CAROL, name='carol-root')
        child = Notebook.objects.create(organization_id=ORG_A, name='carol-child',
                                        parent=root, created_by_id=CAROL)
        note = _note(ORG_A, 'carol-note', CAROL, notebook=child)
        req = _req('delete', '/api/notebooks/', _user(ADA, ADA_EMAIL, admin=True), ORG_A)
        with patch('notes.middleware.get_user_organization_ids', return_value=[ORG_A]):
            resp = _dispatch(NotebookViewSet, {'delete': 'destroy'}, req, pk=root.id)
        self.assertEqual(resp.status_code, 204,
                         getattr(resp, 'data', getattr(resp, 'status_code', None)))
        self.assertFalse(Notebook.objects.filter(pk=root.id).exists())
        self.assertFalse(Notebook.objects.filter(pk=child.id).exists())
        self.assertFalse(Note.objects.filter(pk=note.id).exists())
        # break-glass audited per cascaded object.
        self.assertTrue(AccessAudit.objects.filter(
            object_type='notebook', object_id=str(child.id), decision='allow').exists())

    def test_cascade_delete_denied_when_break_glass_audit_fails(self):
        # revi round 3: if the mandatory break-glass audit cannot persist, deny and
        # preserve the FULL subtree (fail-closed).
        root = _nb(ORG_A, CAROL, name='carol-root')
        child = Notebook.objects.create(organization_id=ORG_A, name='carol-child',
                                        parent=root, created_by_id=CAROL)
        note = _note(ORG_A, 'carol-note', CAROL, notebook=child)
        req = _req('delete', '/api/notebooks/', _user(ADA, ADA_EMAIL, admin=True), ORG_A)
        with patch('notes.middleware.get_user_organization_ids', return_value=[ORG_A]), \
             patch('notes.models.AccessAudit.objects.create', side_effect=Exception('db down')):
            resp = _dispatch(NotebookViewSet, {'delete': 'destroy'}, req, pk=root.id)
        self.assertIn(resp.status_code, (403, 404))
        self.assertTrue(Notebook.objects.filter(pk=root.id).exists())
        self.assertTrue(Notebook.objects.filter(pk=child.id).exists())
        self.assertTrue(Note.objects.filter(pk=note.id).exists())


class NTS51ReviewP5NotebookUpdateACL(TestCase):
    """revi PR#5 P1: notebook PATCH must not reparent under a notebook the caller
    lacks edit authority for, nor reassign ownership."""

    def test_reparent_under_foreign_notebook_rejected(self):
        alice_nb = _nb(ORG_A, ALICE, name='alice-nb')
        carol_nb = _nb(ORG_A, CAROL, name='carol-nb')
        resp = _dispatch(NotebookViewSet, {'patch': 'partial_update'},
                         _req('patch', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A,
                              data={'parent': str(carol_nb.id)}), pk=alice_nb.id)
        self.assertIn(resp.status_code, (400, 403, 404))
        alice_nb.refresh_from_db()
        self.assertIsNone(alice_nb.parent_id)

    def test_ownership_reassignment_is_ignored(self):
        alice_nb = _nb(ORG_A, ALICE, name='alice-nb')
        resp = _dispatch(NotebookViewSet, {'patch': 'partial_update'},
                         _req('patch', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A,
                              data={'created_by_id': CAROL}), pk=alice_nb.id)
        self.assertIn(resp.status_code, (200, 202))
        alice_nb.refresh_from_db()
        self.assertEqual(alice_nb.created_by_id, ALICE, 'ownership was reassigned')

    def test_reparent_with_edit_grant_is_allowed(self):
        alice_nb = _nb(ORG_A, ALICE, name='alice-nb')
        carol_nb = _nb(ORG_A, CAROL, name='carol-nb')
        _grant(carol_nb, user=ALICE, permission='edit')
        resp = _dispatch(NotebookViewSet, {'patch': 'partial_update'},
                         _req('patch', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A,
                              data={'parent': str(carol_nb.id)}), pk=alice_nb.id)
        self.assertIn(resp.status_code, (200, 202))
        alice_nb.refresh_from_db()
        self.assertEqual(alice_nb.parent_id, carol_nb.id)


class NTS51ReviewP5DefaultScoping(TestCase):
    """revi PR#5 P1: setting one's own default notebook must not clear another
    user's default (the invariant is per-user, not per-org)."""

    def test_setting_own_default_does_not_clear_other_users(self):
        carol_default = Notebook.objects.create(
            organization_id=ORG_A, name='carol-default', created_by_id=CAROL, is_default=True)
        alice_nb = _nb(ORG_A, ALICE, name='alice-nb')
        resp = _dispatch(NotebookViewSet, {'patch': 'partial_update'},
                         _req('patch', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A,
                              data={'is_default': True}), pk=alice_nb.id)
        self.assertIn(resp.status_code, (200, 202))
        carol_default.refresh_from_db()
        self.assertTrue(carol_default.is_default, "another user's default was cleared")
        alice_nb.refresh_from_db()
        self.assertTrue(alice_nb.is_default)

    def test_edit_share_cannot_change_owner_default(self):
        # revi round 2 P1: is_default is an owner-only per-user preference. An edit
        # sharee flipping it would rewrite the OWNER's default set — reject it.
        carol_default = Notebook.objects.create(
            organization_id=ORG_A, name='carol-default', created_by_id=CAROL, is_default=True)
        carol_other = Notebook.objects.create(
            organization_id=ORG_A, name='carol-other', created_by_id=CAROL)
        _grant(carol_other, user=ALICE, permission='edit')
        resp = _dispatch(NotebookViewSet, {'patch': 'partial_update'},
                         _req('patch', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A,
                              data={'is_default': True}), pk=carol_other.id)
        self.assertIn(resp.status_code, (403, 404))
        carol_default.refresh_from_db()
        self.assertTrue(carol_default.is_default, "owner's default cleared via edit share")
        carol_other.refresh_from_db()
        self.assertFalse(carol_other.is_default, 'is_default set by a non-owner')


class NTS51ReviewP5CountACL(TestCase):
    """revi PR#5 P1: notebook detail/list note/children counts and tag autocomplete
    counts must only include notes/children the caller is authorized to see."""

    def test_view_shared_notebook_detail_hides_private_note_count(self):
        nb = _nb(ORG_A, CAROL, name='carol-nb')
        _note(ORG_A, 'carol-private', CAROL, notebook=nb)
        _grant(nb, user=ALICE, permission='view')
        resp = _dispatch(NotebookViewSet, {'get': 'retrieve'},
                         _req('get', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A), pk=nb.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['note_count'], 0, "leaked unauthorized note count")

    def test_view_shared_notebook_hides_foreign_children_count(self):
        nb = _nb(ORG_A, CAROL, name='carol-nb')
        Notebook.objects.create(organization_id=ORG_A, name='carol-child',
                                parent=nb, created_by_id=CAROL)
        _grant(nb, user=ALICE, permission='view')
        resp = _dispatch(NotebookViewSet, {'get': 'retrieve'},
                         _req('get', '/api/notebooks/', _user(ALICE, ALICE_EMAIL), ORG_A), pk=nb.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['children_count'], 0, "leaked unauthorized children count")

    @unittest.skipUnless(connection.vendor == 'postgresql',
                         'tag autocomplete uses TrigramSimilarity (postgres-only)')
    def test_tag_autocomplete_count_excludes_unauthorized_notes(self):
        alice_tag = _tag(ORG_A, ALICE, name='shared-topic')
        alice_note = _note(ORG_A, 'alice-note', ALICE)
        alice_note.tags.add(alice_tag)
        carol_note = _note(ORG_A, 'carol-note', CAROL)   # Alice cannot see this
        carol_note.tags.add(alice_tag)
        resp = _dispatch(TagViewSet, {'get': 'autocomplete'},
                         _req('get', '/api/tags/autocomplete/?q=shared',
                              _user(ALICE, ALICE_EMAIL), ORG_A))
        self.assertEqual(resp.status_code, 200)
        match = [r for r in resp.data['results'] if r['id'] == str(alice_tag.id)]
        self.assertTrue(match, 'own tag missing from autocomplete')
        self.assertEqual(match[0]['note_count'], 1, "leaked unauthorized tagged-note count")


@unittest.skipUnless(
    connection.vendor == 'postgresql',
    'Django omits SELECT FOR UPDATE on sqlite; the subtree lock this asserts is only '
    'emitted on postgres. The sqlite authz gate still covers that this atomic+lock '
    'refactor preserves the delete AUTHORIZATION via the existing cascade / break-glass '
    'tests.')
class NTS51CascadeDeleteLocksSubtree(TestCase):
    """revi round-4 P1: perform_destroy must authorize + delete as ONE transaction that
    LOCKS the whole subtree FOR UPDATE before enumerating it, so a note inserted into
    the subtree while a delete is authorizing it cannot be silently cascade-deleted
    without ever being authorized (a check-then-delete TOCTOU).

    A structural proof that the lock is taken: it asserts perform_destroy issues
    ``SELECT ... FOR UPDATE`` on the notebook subtree (root + descendant) during a real
    DELETE, inside a single transaction. That the held FOR UPDATE actually BLOCKS a
    concurrent FK note insert (FOR KEY SHARE) is a PostgreSQL guarantee — verified out
    of band with two raw connections — so together the race window is closed. A live
    two-connection behavioral test is deliberately omitted here: it can only assert the
    block via a lock-wait timeout, which is timing-based and risks wedging the CI test
    job if the wait is ever mis-cancelled.
    """

    def test_perform_destroy_locks_the_notebook_subtree_for_update(self):
        from django.test.utils import CaptureQueriesContext

        root = _nb(ORG_A, CAROL, name='lock-root')
        child = _nb(ORG_A, CAROL, name='lock-child')
        child.parent = root
        child.save()
        _note(ORG_A, 'n', CAROL, notebook=child)

        carol = _user(CAROL, CAROL_EMAIL)  # the owner deletes their own subtree
        req = _req('delete', f'/notebooks/{root.pk}/', carol, ORG_A)
        with CaptureQueriesContext(connection) as cap:
            resp = _dispatch(NotebookViewSet, {'delete': 'destroy'}, req, pk=root.pk)
        self.assertIn(resp.status_code, (204, 200), getattr(resp, 'data', None))

        nb_table = Notebook._meta.db_table
        for_update_on_notebook = [
            q['sql'] for q in cap.captured_queries
            if 'FOR UPDATE' in q['sql'] and nb_table in q['sql']
        ]
        self.assertTrue(
            for_update_on_notebook,
            'perform_destroy must SELECT ... FOR UPDATE the notebook subtree before '
            'enumerating/deleting it (revi round-4 TOCTOU fix)')
        # The whole authorized subtree is gone.
        self.assertFalse(Notebook.objects.filter(pk__in=[root.pk, child.pk]).exists())
        self.assertFalse(Note.objects.filter(notebook_id__in=[root.pk, child.pk]).exists())
