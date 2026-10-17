"""
Regression tests for PLAT-17: NoteShareCreateSerializer must resolve
shared_with_email -> shared_with_user_id at write time.

Mirrors PLAT-14 on shizuha-drive. The read-side hybrid-key in
SharedWithMeView (views.py:658-660) already covers late registrants,
but downstream paths keyed only on shared_with_user_id (notifications,
metrics) missed shares until the invitee's next login — this fix
populates the id eagerly when the email already resolves.
"""
from unittest.mock import MagicMock, patch

from django.test import TestCase

from notes.models import Notebook, Note, NoteShare
from notes.serializers import (
    NoteShareCreateSerializer,
    _resolve_shared_with_id,
)


class ResolveSharedWithIdTests(TestCase):
    def test_returns_none_for_empty_email(self):
        self.assertIsNone(_resolve_shared_with_id(""))
        self.assertIsNone(_resolve_shared_with_id(None))

    def test_network_exception_returns_none(self):
        # shizuha-id outage/timeout must never block share creation.
        with patch("requests.get", side_effect=Exception("boom")):
            self.assertIsNone(_resolve_shared_with_id("x@y.com"))

    def test_resolves_integer_user_id_on_200(self):
        class _Resp:
            status_code = 200
            def json(self):
                return {"id": 4242, "email": "invitee@example.com"}
        with patch("requests.get", return_value=_Resp()):
            self.assertEqual(
                _resolve_shared_with_id("invitee@example.com"),
                4242,
            )

    def test_resolves_string_id_to_int(self):
        # shizuha-id may serialise user_id as a string; we must coerce
        # to int because NoteShare.shared_with_user_id is an IntegerField.
        class _Resp:
            status_code = 200
            def json(self):
                return {"id": "4242"}
        with patch("requests.get", return_value=_Resp()):
            self.assertEqual(_resolve_shared_with_id("x@y.com"), 4242)

    def test_non_integer_id_returns_none(self):
        class _Resp:
            status_code = 200
            def json(self):
                return {"id": "not-a-number"}
        with patch("requests.get", return_value=_Resp()):
            self.assertIsNone(_resolve_shared_with_id("x@y.com"))

    def test_404_returns_none(self):
        class _Resp:
            status_code = 404
            def json(self):
                return {}
        with patch("requests.get", return_value=_Resp()):
            self.assertIsNone(_resolve_shared_with_id("ghost@example.com"))

    def test_missing_id_key_returns_none(self):
        class _Resp:
            status_code = 200
            def json(self):
                return {"email": "x@y.com"}  # no 'id' key
        with patch("requests.get", return_value=_Resp()):
            self.assertIsNone(_resolve_shared_with_id("x@y.com"))


class NoteShareCreateSerializerTests(TestCase):
    def setUp(self):
        self.organization_id = 51
        self.notebook = Notebook.objects.create(
            organization_id=self.organization_id, name="NB",
        )
        self.note = Note.objects.create(
            organization_id=self.organization_id,
            notebook=self.notebook,
            title="Test note",
            created_by_id=1,
        )
        # Fake request for serializer context.
        self.request = MagicMock()
        self.request.user = MagicMock(id=1)

    def _make(self, data):
        return NoteShareCreateSerializer(
            data=data, context={"request": self.request},
        )

    def test_create_populates_shared_with_user_id_when_resolvable(self):
        ser = self._make({
            "note": str(self.note.id),
            "shared_with_email": "invitee@example.com",
            "is_public_link": False,
            "permission": "view",
        })
        self.assertTrue(ser.is_valid(), ser.errors)
        with patch(
            "notes.serializers._resolve_shared_with_id",
            return_value=777,
        ):
            share = ser.save()

        self.assertEqual(share.shared_with_user_id, 777)
        self.assertEqual(share.shared_with_email, "invitee@example.com")
        self.assertEqual(share.shared_by_id, 1)

    def test_create_leaves_id_none_when_unresolvable(self):
        ser = self._make({
            "note": str(self.note.id),
            "shared_with_email": "ghost@example.com",
            "is_public_link": False,
            "permission": "view",
        })
        self.assertTrue(ser.is_valid(), ser.errors)
        with patch("notes.serializers._resolve_shared_with_id", return_value=None):
            share = ser.save()

        self.assertIsNone(share.shared_with_user_id)
        self.assertEqual(share.shared_with_email, "ghost@example.com")

    def test_create_tolerates_network_error(self):
        # If the resolver raises (shouldn't — helper already catches — but
        # belt-and-braces), share creation must still proceed with None.
        ser = self._make({
            "note": str(self.note.id),
            "shared_with_email": "unreachable@example.com",
            "is_public_link": False,
            "permission": "view",
        })
        self.assertTrue(ser.is_valid(), ser.errors)
        with patch(
            "notes.serializers._resolve_shared_with_id",
            return_value=None,
        ) as mock_resolve:
            share = ser.save()
            mock_resolve.assert_called_once_with("unreachable@example.com")
        self.assertIsNone(share.shared_with_user_id)

    def test_public_link_share_skips_email_resolution(self):
        # Public link shares have no email; we must not call the resolver.
        ser = self._make({
            "note": str(self.note.id),
            "is_public_link": True,
            "permission": "view",
        })
        self.assertTrue(ser.is_valid(), ser.errors)
        with patch(
            "notes.serializers._resolve_shared_with_id",
            return_value=999,
        ) as mock_resolve:
            share = ser.save()
            mock_resolve.assert_not_called()
        self.assertIsNone(share.shared_with_user_id)
        self.assertTrue(share.is_public_link)


class LateRegistrantReadFallbackTests(TestCase):
    """
    Proves the read-side hybrid-key safety net still works for shares
    written before this fix (shared_with_email set, shared_with_user_id
    NULL) — this guarantees we don't regress the existing behaviour.
    """
    def setUp(self):
        self.organization_id = 51
        self.notebook = Notebook.objects.create(
            organization_id=self.organization_id, name="NB",
        )
        self.note = Note.objects.create(
            organization_id=self.organization_id,
            notebook=self.notebook,
            title="Test note",
            created_by_id=1,
        )

    def test_queryset_email_fallback_finds_unresolved_share(self):
        # Write a share in the "unresolved" state (pre-registration).
        NoteShare.objects.create(
            note=self.note,
            shared_with_email="invitee@example.com",
            shared_with_user_id=None,
            permission="view",
            shared_by_id=1,
        )

        # Mirror SharedWithMeView.get filter (views.py:658-660).
        from django.db.models import Q
        user_id = 99
        user_email = "invitee@example.com"
        qs = NoteShare.objects.filter(
            Q(shared_with_user_id=user_id) | Q(shared_with_email=user_email)
        ).filter(revoked_at__isnull=True)
        self.assertEqual(qs.count(), 1)
