"""NTS-18 (NTS-11 Slice 8) — security acceptance matrix for search.

The mandatory must-all-pass security tests from the acceptance gate: a user must
never see another org's notes, a revoked share must disappear, email-fallback
shares reach the right user only, public-link shares are NOT authed-searchable,
and `shared_with_me` returns only the caller's active shares.

These exercise the access boundary in BROWSE / `shared_with_me` mode (empty `q` +
a filter), so they assert the org/share access control directly and are
DB-agnostic (no dependency on the Postgres FTS text-match backend). The
perf-at-scale half of the gate (100k/1M-note p95 + EXPLAIN GIN-trigram usage) is a
separate run that needs an isolated seeded corpus.

Access model (notes/services/search.py): a note is visible iff
`organization_id ∈ caller_orgs` OR an ACTIVE (`revoked_at IS NULL`) share to the
caller's `shared_with_user_id` OR to the caller's `shared_with_email`. Public-link
shares carry neither a user nor an email, so they never match. `shared_with_me`
restricts to the share legs only.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from ..models import Note, Notebook, NoteShare
from ..views import SearchView
from rest_framework.test import APIRequestFactory

ORG_A, ORG_B, ORG_C = 1, 2, 3
ALICE, ALICE_EMAIL = 10, 'alice@a.example'
BOB, BOB_EMAIL = 20, 'bob@b.example'


def _search(params=None, *, user_id=ALICE, email=ALICE_EMAIL, org_ids=(ORG_A,)):
    factory = APIRequestFactory()
    request = factory.get('/api/search/', params or {})
    user = MagicMock()
    user.id = user.pk = user_id
    user.email = email
    user.is_authenticated = True
    request.user = user
    request._user_organization_ids = list(org_ids)
    request.organization_id = None
    request._pending_organization_id = None
    with patch('notes.services.search.set_organization_context'), \
         patch('notes.services.search.get_user_organization_ids', return_value=list(org_ids)):
        return SearchView.as_view()(request)


def _ids(response):
    return {str(r['id']) for r in response.data['results']}


def _nb(org, user=ALICE):
    return Notebook.objects.create(organization_id=org, name=f'NB-{org}-{user}', created_by_id=user)


def _note(org, title, *, user=ALICE, nb=None, **kw):
    return Note.objects.create(
        organization_id=org, notebook=nb or _nb(org, user), title=title, created_by_id=user, **kw,
    )


def _share(note, *, by=BOB, user_id=None, email=None, public=False, revoked=False):
    s = NoteShare.objects.create(
        note=note, shared_by_id=by, shared_with_user_id=user_id,
        shared_with_email=email, is_public_link=public,
    )
    if revoked:
        s.revoked_at = timezone.now()
        s.save(update_fields=['revoked_at'])
    return s


class CrossOrgIsolationTests(TestCase):
    def test_browse_excludes_other_orgs_notes(self):
        mine = _note(ORG_A, 'Quarterly Plan', is_favorite=True)
        theirs = _note(ORG_B, 'Quarterly Plan', user=BOB, is_favorite=True)  # same title, other org
        ids = _ids(_search({'favorite': 'true'}, org_ids=(ORG_A,)))
        self.assertIn(str(mine.id), ids)
        self.assertNotIn(str(theirs.id), ids, 'org A user must not see org B notes')


class RevokedShareTests(TestCase):
    def test_active_share_appears_then_revoked_disappears(self):
        note = _note(ORG_B, 'Shared doc', user=BOB)
        share = _share(note, user_id=ALICE)  # active share to Alice
        self.assertIn(str(note.id), _ids(_search({'shared_with_me': 'true'})),
                      'active share to caller should be visible')
        share.revoked_at = timezone.now()
        share.save(update_fields=['revoked_at'])
        self.assertNotIn(str(note.id), _ids(_search({'shared_with_me': 'true'})),
                         'revoked share must not appear')


class EmailFallbackShareTests(TestCase):
    def test_email_share_visible_to_matching_email_only(self):
        note = _note(ORG_B, 'Emailed doc', user=BOB)
        _share(note, email=ALICE_EMAIL)  # shared to Alice's email, no user id
        # Alice (matching email, org A — no org access to org B) sees it via email fallback.
        self.assertIn(str(note.id), _ids(_search({'shared_with_me': 'true'}, user_id=ALICE, email=ALICE_EMAIL)))
        # A different user (different email, different org) does NOT.
        self.assertNotIn(str(note.id), _ids(_search({'shared_with_me': 'true'},
                                                user_id=99, email='eve@x.example', org_ids=(ORG_C,))))


class PublicLinkTests(TestCase):
    def test_public_link_not_in_authed_search(self):
        note = _note(ORG_B, 'Public doc', user=BOB, is_favorite=True)
        _share(note, public=True)  # public link: no user, no email
        # Not a share-to-Alice and not org A → absent from her shared_with_me AND her org browse.
        self.assertNotIn(str(note.id), _ids(_search({'shared_with_me': 'true'})))
        self.assertNotIn(str(note.id), _ids(_search({'favorite': 'true'}, org_ids=(ORG_A,))))


class SharedWithMeScopeTests(TestCase):
    def test_shared_with_me_returns_only_callers_active_shares(self):
        to_alice = _note(ORG_B, 'For Alice', user=BOB)
        _share(to_alice, user_id=ALICE)                         # active → in
        to_bob = _note(ORG_B, 'For Bob', user=BOB)
        _share(to_bob, user_id=BOB)                             # other user → out
        revoked = _note(ORG_B, 'Was for Alice', user=BOB)
        _share(revoked, user_id=ALICE, revoked=True)            # revoked → out
        ids = _ids(_search({'shared_with_me': 'true'}, user_id=ALICE, email=ALICE_EMAIL))
        self.assertEqual(ids, {str(to_alice.id)}, 'shared_with_me must be only the caller\'s active shares')


class TriggerFreshnessTests(TestCase):
    """NTS-18 regression: editing a note is IMMEDIATELY findable — the 0006
    search_vector trigger refreshes on UPDATE, no manual reindex. Uses FTS `q=`
    text search, so it exercises the Postgres search_vector path (runs on CI
    Postgres; the notes test DB is Postgres-only)."""

    def test_edited_note_immediately_findable_by_new_title(self):
        note = _note(ORG_A, 'Zephyrtoken original')
        self.assertIn(str(note.id), _ids(_search({'q': 'Zephyrtoken'})),
                      'note should be findable by its original title term')
        note.title = 'Quokkatoken revised'
        note.save()  # DB trigger refreshes search_vector on UPDATE
        self.assertIn(str(note.id), _ids(_search({'q': 'Quokkatoken'})),
                      'edited title must be immediately findable (no manual reindex)')
        self.assertNotIn(str(note.id), _ids(_search({'q': 'Zephyrtoken'})),
                         'the stale title term must no longer match after the edit')
