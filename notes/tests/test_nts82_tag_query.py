"""NTS-82: GET /notes/?tag=<uuid> must not include untagged notes."""

from notes.tests.api_fixtures import response_items
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from notes.models import Note, Notebook, Tag
from notes.views import NoteViewSet

ORG = 1
USER_ID = 8282


class _User(SimpleNamespace):
    @property
    def is_authenticated(self):
        return True


class TagQueryFilterTests(TestCase):
    def setUp(self):
        notebook = Notebook.objects.create(
            organization_id=ORG, name='nb', created_by_id=USER_ID,
        )
        self.tag = Tag.objects.create(
            organization_id=ORG, name='qa-tag', created_by_id=USER_ID,
        )
        self.tagged = Note.objects.create(
            organization_id=ORG, notebook=notebook, title='tagged',
            content_text='tagged', created_by_id=USER_ID,
        )
        self.tagged.tags.add(self.tag)
        self.untagged = Note.objects.create(
            organization_id=ORG, notebook=notebook, title='untagged',
            content_text='untagged', created_by_id=USER_ID,
        )

    def _list(self, params):
        factory = APIRequestFactory()
        request = factory.get('/api/notes/', params, HTTP_X_ORGANIZATION_ID=str(ORG))
        request.organization_id = ORG
        request._pending_organization_id = ORG
        request._user_organization_ids = [ORG]
        force_authenticate(request, user=_User(id=USER_ID, pk=USER_ID, email='n@example.com'))
        with patch('notes.views.set_organization_context', lambda request: None):
            return NoteViewSet.as_view({'get': 'list'})(request)

    def test_tag_query_excludes_untagged_notes(self):
        response = self._list({'tag': str(self.tag.id)})
        self.assertEqual(response.status_code, 200)
        ids = {row['id'] for row in response_items(response)}
        self.assertEqual(ids, {str(self.tagged.id)})

    def test_invalid_tag_query_returns_empty(self):
        response = self._list({'tag': 'not-a-uuid'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response_items(response)), [])

    def test_unknown_tag_query_returns_empty(self):
        response = self._list({'tag': str(uuid.uuid4())})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response_items(response)), [])
