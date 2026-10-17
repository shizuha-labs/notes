"""Exercise the real historical rows before organization fields become required."""
import importlib
import json
import os
from unittest import mock
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class LegacyScopeMigrationTests(TransactionTestCase):
    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate([('notes','0001_initial')])
        state = executor.loader.project_state([('notes','0001_initial')])
        self.migration = importlib.import_module('notes.migrations.0002_workspace_to_organization')
        # Match exactly the native RunPython position after its three AddFields.
        for operation in self.migration.Migration.operations[:3]:
            before = state.clone()
            operation.state_forwards('notes',state)
            with connection.schema_editor() as editor:
                operation.database_forwards('notes',editor,before,state)
        self.apps = state.apps
        self.Workspace = self.apps.get_model('notes','Workspace')
        self.Tag = self.apps.get_model('notes','Tag')
        self.Notebook = self.apps.get_model('notes','Notebook')
        self.Note = self.apps.get_model('notes','Note')

    def tearDown(self):
        # The three staged columns are not recorded as an applied migration;
        # dropping initial tables then migrating empty restores the exact final
        # schema for other tests without guessing or fabricating a migration.
        MigrationExecutor(connection).migrate([('notes',None)])
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def populate(self):
        with connection.schema_editor() as editor:
            self.migration.populate_organization_id(self.apps,editor)

    @mock.patch.dict(os.environ, {'NOTES_LEGACY_OWNER_ORGANIZATIONS':''})
    def test_unknown_legacy_owner_fails_before_any_row_write(self):
        workspace = self.Workspace.objects.create(name='Unknown',slug='unknown',owner_id=987)
        tag = self.Tag.objects.create(workspace=workspace,name='Fixture',slug='fixture')
        with self.assertRaises(ValueError):self.populate()
        tag.refresh_from_db()
        self.assertIsNone(tag.organization_id)

    @mock.patch.dict(os.environ, {'NOTES_LEGACY_OWNER_ORGANIZATIONS':json.dumps({'17':51,'18':52})})
    def test_complete_explicit_mapping_preserves_tenant_separation_for_all_three_models(self):
        for owner,organization in ((17,51),(18,52)):
            workspace = self.Workspace.objects.create(name=str(owner),slug=str(owner),owner_id=owner)
            self.Tag.objects.create(workspace=workspace,name='Fixture',slug='fixture')
            notebook=self.Notebook.objects.create(workspace=workspace,name='Fixture')
            self.Note.objects.create(workspace=workspace,notebook=notebook,title='Fixture',created_by_id=owner)
        self.populate()
        for model in (self.Tag,self.Notebook,self.Note):
            self.assertEqual(set(model.objects.values_list('organization_id',flat=True)),{51,52})

    @mock.patch.dict(os.environ, {'NOTES_LEGACY_OWNER_ORGANIZATIONS':''})
    def test_empty_fresh_install_needs_no_private_mapping(self):
        self.populate()
        self.assertEqual(self.Tag.objects.count(),0)

    @mock.patch.dict(os.environ, {'NOTES_LEGACY_OWNER_ORGANIZATIONS':json.dumps({'17':51})})
    def test_incomplete_mapping_does_not_partially_update_an_earlier_known_owner(self):
        for owner,name in ((17,'A-known'),(987,'B-unknown')):
            workspace=self.Workspace.objects.create(name=name,slug=name.lower(),owner_id=owner)
            self.Tag.objects.create(workspace=workspace,name='Fixture',slug='fixture')
        with self.assertRaises(ValueError):self.populate()
        self.assertFalse(self.Tag.objects.exclude(organization_id__isnull=True).exists())

    @mock.patch.dict(os.environ, {'NOTES_LEGACY_OWNER_ORGANIZATIONS':''})
    def test_existing_workspace_organization_is_authoritative(self):
        workspace=self.Workspace.objects.create(name='Explicit',slug='explicit',owner_id=987,organization_id=81)
        tag=self.Tag.objects.create(workspace=workspace,name='Fixture',slug='fixture')
        self.populate()
        tag.refresh_from_db()
        self.assertEqual(tag.organization_id,81)

    @mock.patch.dict(os.environ, {'NOTES_LEGACY_OWNER_ORGANIZATIONS':'{"17":51}'})
    def test_conflicting_authoritative_mapping_is_rejected_before_writes(self):
        workspace=self.Workspace.objects.create(name='Conflict',slug='conflict',owner_id=17,organization_id=81)
        tag=self.Tag.objects.create(workspace=workspace,name='Fixture',slug='fixture')
        with self.assertRaises(ValueError):self.populate()
        tag.refresh_from_db()
        self.assertIsNone(tag.organization_id)

    def test_malformed_mapping_cannot_modify_rows(self):
        for raw in ('[]','{"17":true}','{"17":0}','{"017":51}','{"17":51,"17":52}'):
            with self.subTest(shape=raw), mock.patch.dict(os.environ, {'NOTES_LEGACY_OWNER_ORGANIZATIONS':raw}):
                with self.assertRaises(ValueError):self.populate()

    @mock.patch.dict(os.environ, {'NOTES_LEGACY_OWNER_ORGANIZATIONS':'{"17":51}'})
    def test_conflicting_staged_content_is_not_overwritten(self):
        workspace=self.Workspace.objects.create(name='Staged',slug='staged',owner_id=17)
        tag=self.Tag.objects.create(workspace=workspace,name='Fixture',slug='fixture',organization_id=82)
        with self.assertRaises(ValueError):self.populate()
        tag.refresh_from_db()
        self.assertEqual(tag.organization_id,82)
