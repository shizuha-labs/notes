"""
Tests for Notebook Stacks (hierarchical notebooks) functionality.
"""
import uuid
from django.test import TestCase
from django.core.exceptions import ValidationError
from rest_framework.test import APITestCase
from rest_framework import status

from notes.tests.api_fixtures import configure_membership
from notes.models import Notebook


class NotebookHierarchyModelTests(TestCase):
    """Test the Notebook model hierarchy features."""

    def setUp(self):
        """Set up test data."""
        self.organization_id = 51

    def test_create_root_notebook(self):
        """Test creating a root-level notebook."""
        notebook = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Root Notebook',
            parent=None
        )
        self.assertIsNone(notebook.parent)
        self.assertEqual(notebook._get_depth(), 0)
        self.assertEqual(notebook.get_path(), ['Root Notebook'])

    def test_create_child_notebook(self):
        """Test creating a child notebook."""
        parent = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Parent Stack',
            parent=None
        )
        child = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Child Notebook',
            parent=parent
        )
        self.assertEqual(child.parent, parent)
        self.assertEqual(child._get_depth(), 1)
        self.assertEqual(child.get_path(), ['Parent Stack', 'Child Notebook'])

    def test_max_depth_limit(self):
        """Test that the max depth limit (2 levels) is enforced."""
        root = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Root',
            parent=None
        )
        level1 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Level 1',
            parent=root
        )

        # Creating level 2 should fail (max depth is 2, meaning root + 1 child only)
        # We need to use full_clean() explicitly or create via save()
        notebook = Notebook(
            organization_id=self.organization_id,
            name='Level 2',
            parent=level1
        )
        with self.assertRaises(ValidationError) as context:
            notebook.full_clean()
        self.assertIn('Maximum nesting depth', str(context.exception))

    def test_cannot_be_own_parent(self):
        """Test that a notebook cannot be its own parent."""
        notebook = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Test Notebook',
            parent=None
        )
        notebook.parent = notebook
        with self.assertRaises(ValidationError) as context:
            notebook.full_clean()
        self.assertIn('cannot be its own parent', str(context.exception))

    def test_circular_reference_prevention(self):
        """Test that circular references are prevented."""
        parent = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Parent',
            parent=None
        )
        child = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Child',
            parent=parent
        )

        # Try to set parent's parent to child (circular)
        parent.parent = child
        with self.assertRaises(ValidationError) as context:
            parent.full_clean()
        self.assertIn('Circular reference', str(context.exception))

    def test_parent_must_be_same_organization(self):
        """Test that parent must be in the same organization."""
        other_organization_id = 52
        parent_in_other = Notebook.objects.create(
            organization_id=other_organization_id,
            name='Parent in Other',
            parent=None
        )

        with self.assertRaises(ValidationError) as context:
            Notebook.objects.create(
                organization_id=self.organization_id,
                name='Child',
                parent=parent_in_other
            )
        self.assertIn('same organization', str(context.exception))

    def test_get_ancestors(self):
        """Test getting ancestor notebooks."""
        root = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Root',
            parent=None
        )
        child = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Child',
            parent=root
        )

        self.assertEqual(root.get_ancestors(), [])
        self.assertEqual(child.get_ancestors(), [root])

    def test_get_descendants(self):
        """Test getting descendant notebooks."""
        root = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Root',
            parent=None
        )
        child1 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Child 1',
            parent=root
        )
        child2 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Child 2',
            parent=root
        )

        descendants = root.get_descendants()
        self.assertEqual(len(descendants), 2)
        self.assertIn(child1, descendants)
        self.assertIn(child2, descendants)

    def test_get_path_string(self):
        """Test the path string representation."""
        root = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Projects',
            parent=None
        )
        child = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Work',
            parent=root
        )

        self.assertEqual(root.get_path_string(), 'Projects')
        self.assertEqual(child.get_path_string(), 'Projects / Work')
        self.assertEqual(child.get_path_string(' > '), 'Projects > Work')

    def test_move_to_new_parent(self):
        """Test moving a notebook to a new parent."""
        root1 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Stack 1',
            parent=None
        )
        root2 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Stack 2',
            parent=None
        )
        child = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Child',
            parent=root1
        )

        old_parent = child.move_to(root2)
        self.assertEqual(old_parent, root1)
        self.assertEqual(child.parent, root2)

    def test_move_to_root(self):
        """Test moving a notebook to root level."""
        root = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Stack',
            parent=None
        )
        child = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Child',
            parent=root
        )

        old_parent = child.move_to(None)
        self.assertEqual(old_parent, root)
        self.assertIsNone(child.parent)
        self.assertEqual(child._get_depth(), 0)

    def test_unique_together_constraint(self):
        """Test the unique constraint on organization + name + parent.

        Note: Since we call full_clean() in save(), this raises ValidationError
        rather than IntegrityError at the database level.
        """
        parent = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Parent Stack',
            parent=None
        )
        Notebook.objects.create(
            organization_id=self.organization_id,
            name='My Notebook',
            parent=parent
        )

        # Same name under the same parent should fail
        with self.assertRaises(ValidationError) as context:
            Notebook.objects.create(
                organization_id=self.organization_id,
                name='My Notebook',
                parent=parent
            )
        self.assertIn('already exists', str(context.exception))

    def test_same_name_different_parent_allowed(self):
        """Test that same name under different parents is allowed."""
        root1 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Stack 1',
            parent=None
        )
        root2 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Stack 2',
            parent=None
        )

        # Same name under different parents should work
        child1 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Notes',
            parent=root1
        )
        child2 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Notes',
            parent=root2
        )

        self.assertEqual(child1.name, child2.name)
        self.assertNotEqual(child1.parent, child2.parent)


class NotebookTreeAPITests(APITestCase):
    """Test the notebook tree API endpoints."""

    def setUp(self):
        """Set up test data and authentication."""
        # Create a mock user for authentication
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=self.user)

        self.organization_id = 51

        configure_membership(self, self.organization_id)

        # Create some notebooks
        self.stack1 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Stack 1',
            parent=None,
            color='#ef4444',
            created_by_id=self.user.id
        )
        self.stack2 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Stack 2',
            parent=None,
            color='#22c55e',
            created_by_id=self.user.id
        )
        self.child1 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Child 1',
            parent=self.stack1,
            created_by_id=self.user.id
        )
        self.child2 = Notebook.objects.create(
            organization_id=self.organization_id,
            name='Child 2',
            parent=self.stack1,
            created_by_id=self.user.id
        )

    def test_tree_endpoint_returns_hierarchy(self):
        """Test that the tree endpoint returns hierarchical data."""
        response = self.client.get(
            '/api/notebooks/tree/',
            {'organization_id': self.organization_id}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # Should only return root-level notebooks
        self.assertEqual(len(data), 2)
        # Check children are nested
        stack1_data = next(n for n in data if n['name'] == 'Stack 1')
        self.assertEqual(len(stack1_data['children']), 2)

    def test_move_endpoint(self):
        """Test moving a notebook via API."""
        # Move child1 from stack1 to stack2
        response = self.client.post(
            f'/api/notebooks/{self.child1.id}/move/',
            {'parent': str(self.stack2.id)},
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.child1.refresh_from_db()
        self.assertEqual(self.child1.parent, self.stack2)

    def test_move_to_root(self):
        """Test moving a notebook to root level."""
        # Send empty string or omit parent to move to root
        response = self.client.post(
            f'/api/notebooks/{self.child1.id}/move/',
            {},  # Empty body means null parent
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.child1.refresh_from_db()
        self.assertIsNone(self.child1.parent)

    def test_create_with_parent(self):
        """Test creating a notebook with a parent."""
        response = self.client.post(
            '/api/notebooks/',
            {
                'organization_id': self.organization_id,
                'name': 'New Child',
                'parent': str(self.stack1.id),
                'color': '#6366f1'
            },
            format='json'
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data['parent'], str(self.stack1.id))

    def test_tree_serializer_includes_note_count(self):
        """Test that tree serializer includes note counts."""
        from notes.models import Note

        # Create some notes in the child notebook
        for i in range(3):
            Note.objects.create(
                organization_id=self.organization_id,
                notebook=self.child1,
                title=f'Test Note {i}',
                created_by_id=self.user.id
            )

        response = self.client.get(
            '/api/notebooks/tree/',
            {'organization_id': self.organization_id}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        stack1_data = next(n for n in data if n['name'] == 'Stack 1')
        child1_data = next(c for c in stack1_data['children'] if c['name'] == 'Child 1')
        self.assertEqual(child1_data['note_count'], 3)


class NotebookTreeSerializerTests(TestCase):
    """Test the NotebookTreeSerializer."""

    def setUp(self):
        """Set up test data."""
        self.organization_id = 51
        from types import SimpleNamespace
        self.request = SimpleNamespace(user=SimpleNamespace(id=71,pk=71,email='fixture@example.test',is_authenticated=True), organization_id=51, _user_organization_ids=[51])

    def test_serializer_includes_path(self):
        """Test that the serializer includes the path."""
        from notes.serializers import NotebookTreeSerializer

        root = Notebook.objects.create(
            organization_id=self.organization_id,
            created_by_id=71,
            name='Root',
            parent=None
        )
        child = Notebook.objects.create(
            organization_id=self.organization_id,
            created_by_id=71,
            name='Child',
            parent=root
        )

        serializer = NotebookTreeSerializer(child, context={"request":self.request})
        data = serializer.data

        self.assertEqual(data['path'], ['Root', 'Child'])
        self.assertEqual(data['depth'], 1)

    def test_serializer_nested_children(self):
        """Test that children are properly nested."""
        from notes.serializers import NotebookTreeSerializer

        root = Notebook.objects.create(
            organization_id=self.organization_id,
            created_by_id=71,
            name='Root',
            parent=None
        )
        child1 = Notebook.objects.create(
            organization_id=self.organization_id,
            created_by_id=71,
            name='Child 1',
            parent=root
        )
        child2 = Notebook.objects.create(
            organization_id=self.organization_id,
            created_by_id=71,
            name='Child 2',
            parent=root
        )

        serializer = NotebookTreeSerializer(root, context={"request":self.request})
        data = serializer.data

        self.assertEqual(len(data['children']), 2)
        child_names = [c['name'] for c in data['children']]
        self.assertIn('Child 1', child_names)
        self.assertIn('Child 2', child_names)
