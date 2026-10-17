"""NTS-33 P1: notebook tree determinism and safe move validation."""
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from notes.models import Notebook, Note
from notes.views import NotebookViewSet


class _User(SimpleNamespace):
    @property
    def is_authenticated(self):
        return True


def _request(request, user_id=1, org_id=1):
    request.organization_id = org_id
    request.organization_role = 'admin'
    request._user_organization_ids = [org_id]
    force_authenticate(
        request,
        user=_User(id=user_id, pk=user_id, email=f'u{user_id}@example.com'),
    )
    return request


class NotebookOrganizationP1Tests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user_id = 1

    def test_tree_orders_roots_and_children_deterministically(self):
        root_b = Notebook.objects.create(
            organization_id=1, name='Beta', sort_order=10, created_by_id=self.user_id)
        root_a = Notebook.objects.create(
            organization_id=1, name='Alpha', sort_order=10, created_by_id=self.user_id)
        root_c = Notebook.objects.create(
            organization_id=1, name='First', sort_order=0, created_by_id=self.user_id)
        Notebook.objects.create(
            organization_id=1, name='Zulu', parent=root_b, sort_order=2, created_by_id=self.user_id)
        Notebook.objects.create(
            organization_id=1, name='Able', parent=root_b, sort_order=2, created_by_id=self.user_id)
        Note.objects.create(
            organization_id=1, notebook=root_b, title='Visible', created_by_id=self.user_id)
        Note.objects.create(
            organization_id=1, notebook=root_b, title='Trashed',
            created_by_id=self.user_id, status='trashed')

        view = NotebookViewSet.as_view({'get': 'tree'})
        response = view(_request(self.factory.get('/notebooks/tree/')))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([node['name'] for node in response.data], ['First', 'Alpha', 'Beta'])
        beta = response.data[2]
        self.assertEqual([node['name'] for node in beta['children']], ['Able', 'Zulu'])
        self.assertEqual(beta['note_count'], 1)

    def test_move_rejects_depth_overflow_and_archived_parent(self):
        root = Notebook.objects.create(
            organization_id=1, name='Root', created_by_id=self.user_id)
        child = Notebook.objects.create(
            organization_id=1, name='Child', parent=root, created_by_id=self.user_id)
        other_root = Notebook.objects.create(
            organization_id=1, name='Other', created_by_id=self.user_id)
        archived_root = Notebook.objects.create(
            organization_id=1, name='Archived', is_archived=True, archived_at=timezone.now(),
            created_by_id=self.user_id)
        view = NotebookViewSet.as_view({'post': 'move'})

        response = view(
            _request(self.factory.post(
                f'/notebooks/{root.id}/move/',
                {'parent': str(other_root.id)},
                format='json',
            )),
            pk=str(root.id),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('depth', str(response.data).lower())
        root.refresh_from_db()
        self.assertIsNone(root.parent)
        child.refresh_from_db()
        self.assertEqual(child.parent, root)

        response = view(
            _request(self.factory.post(
                f'/notebooks/{child.id}/move/',
                {'parent': str(archived_root.id)},
                format='json',
            )),
            pk=str(child.id),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('archived', str(response.data).lower())

    def test_move_updates_parent_and_sort_order_atomically(self):
        root = Notebook.objects.create(
            organization_id=1, name='Root', created_by_id=self.user_id)
        target = Notebook.objects.create(
            organization_id=1, name='Target', created_by_id=self.user_id)
        child = Notebook.objects.create(
            organization_id=1, name='Child', parent=root, sort_order=1, created_by_id=self.user_id)
        view = NotebookViewSet.as_view({'post': 'move'})

        response = view(
            _request(self.factory.post(
                f'/notebooks/{child.id}/move/',
                {'parent': str(target.id), 'sort_order': 42},
                format='json',
            )),
            pk=str(child.id),
        )

        self.assertEqual(response.status_code, 200)
        child.refresh_from_db()
        self.assertEqual(child.parent, target)
        self.assertEqual(child.sort_order, 42)

    def test_create_rejects_archived_parent_with_api_400(self):
        archived_root = Notebook.objects.create(
            organization_id=1,
            name='Archived',
            is_archived=True,
            archived_at=timezone.now(),
            created_by_id=self.user_id,
        )
        view = NotebookViewSet.as_view({'post': 'create'})

        response = view(_request(self.factory.post(
            '/notebooks/',
            {'name': 'Child', 'parent': str(archived_root.id)},
            format='json',
        )))

        self.assertEqual(response.status_code, 400)
        self.assertIn('archived', str(response.data).lower())
        self.assertFalse(Notebook.objects.filter(name='Child').exists())

    def test_create_rejects_depth_overflow_with_api_400(self):
        root = Notebook.objects.create(
            organization_id=1, name='Root', created_by_id=self.user_id)
        child = Notebook.objects.create(
            organization_id=1, name='Child', parent=root, created_by_id=self.user_id)
        view = NotebookViewSet.as_view({'post': 'create'})

        response = view(_request(self.factory.post(
            '/notebooks/',
            {'name': 'Grandchild', 'parent': str(child.id)},
            format='json',
        )))

        self.assertEqual(response.status_code, 400)
        self.assertIn('depth', str(response.data).lower())
        self.assertFalse(Notebook.objects.filter(name='Grandchild').exists())

    def test_update_rejects_archived_parent_with_api_400(self):
        child = Notebook.objects.create(
            organization_id=1, name='Child', created_by_id=self.user_id)
        archived_root = Notebook.objects.create(
            organization_id=1,
            name='Archived',
            is_archived=True,
            archived_at=timezone.now(),
            created_by_id=self.user_id,
        )
        view = NotebookViewSet.as_view({'patch': 'partial_update'})

        response = view(
            _request(self.factory.patch(
                f'/notebooks/{child.id}/',
                {'parent': str(archived_root.id)},
                format='json',
            )),
            pk=str(child.id),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('archived', str(response.data).lower())
        child.refresh_from_db()
        self.assertIsNone(child.parent)

    def test_update_rejects_depth_overflow_with_api_400(self):
        root = Notebook.objects.create(
            organization_id=1, name='Root', created_by_id=self.user_id)
        child = Notebook.objects.create(
            organization_id=1, name='Child', parent=root, created_by_id=self.user_id)
        other_root = Notebook.objects.create(
            organization_id=1, name='Other', created_by_id=self.user_id)
        view = NotebookViewSet.as_view({'patch': 'partial_update'})

        response = view(
            _request(self.factory.patch(
                f'/notebooks/{root.id}/',
                {'parent': str(other_root.id)},
                format='json',
            )),
            pk=str(root.id),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('depth', str(response.data).lower())
        root.refresh_from_db()
        child.refresh_from_db()
        self.assertIsNone(root.parent)
        self.assertEqual(child.parent, root)
