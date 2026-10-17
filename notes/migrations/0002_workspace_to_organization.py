"""
Migration: Replace workspace-based scoping with organization-based scoping.

This migration:
1. Adds organization_id (nullable) to Notebook, Note, Tag
2. Populates organization_id from explicit workspace or managed restoration mapping
3. Makes organization_id non-nullable
4. Removes workspace FK from Notebook, Note, Tag
5. Updates unique_together and indexes
6. Deletes Workspace and WorkspaceMembership tables
"""
from django.db import migrations, models


def _legacy_owner_organizations():
    """Installation-owned restoration data; never infer an organization."""
    import json
    import os
    raw = os.environ.get('NOTES_LEGACY_OWNER_ORGANIZATIONS', '')
    if not raw:
        return {}
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate legacy owner mapping')
            result[key] = value
        return result
    try:
        data = json.loads(raw, object_pairs_hook=unique_pairs)
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid legacy owner organization mapping') from exc
    if not isinstance(data, dict):
        raise ValueError('Legacy owner mapping must be an object')
    mapping = {}
    for owner, organization in data.items():
        if (not owner.isdecimal() or str(int(owner)) != owner or int(owner) <= 0
                or type(organization) is not int or organization <= 0):
            raise ValueError('Legacy owner mapping requires positive integer identities')
        mapping[int(owner)] = organization
    return mapping


def populate_organization_id(apps, schema_editor):
    """Preflight every historical tenant before modifying any content row."""
    alias = schema_editor.connection.alias
    Workspace = apps.get_model('notes', 'Workspace')
    models_to_update = [apps.get_model('notes', name) for name in ('Notebook', 'Note', 'Tag')]
    owner_organizations = _legacy_owner_organizations()
    workspace_organizations = {}
    for workspace in Workspace.objects.using(alias).all():
        organization = workspace.organization_id
        configured = owner_organizations.get(workspace.owner_id)
        if organization is not None:
            if type(organization) is not int or organization <= 0:
                raise ValueError('Invalid authoritative workspace organization')
            if configured is not None and configured != organization:
                raise ValueError('Legacy mapping conflicts with authoritative workspace organization')
        else:
            organization = configured
        if organization is None:
            raise ValueError('Complete NOTES_LEGACY_OWNER_ORGANIZATIONS is required for historical workspaces')
        workspace_organizations[workspace.pk] = organization

    # Check orphans and conflicting staged values before the first UPDATE.
    for model in models_to_update:
        for workspace_id, organization_id in model.objects.using(alias).values_list('workspace_id', 'organization_id'):
            if workspace_id not in workspace_organizations:
                raise ValueError('Historical content has no authoritative workspace organization')
            if organization_id is not None and organization_id != workspace_organizations[workspace_id]:
                raise ValueError('Historical content organization conflicts with workspace')
    for model in models_to_update:
        for workspace_id, organization_id in workspace_organizations.items():
            model.objects.using(alias).filter(workspace_id=workspace_id).update(organization_id=organization_id)


def reverse_populate(apps, schema_editor):
    """Reverse: we can't perfectly reverse this, but it's a no-op since we'll drop workspace anyway."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0001_initial'),
    ]

    operations = [
        # Step 1: Add organization_id (nullable) to all three models
        migrations.AddField(
            model_name='notebook',
            name='organization_id',
            field=models.IntegerField(null=True, blank=True, db_index=True),
        ),
        migrations.AddField(
            model_name='note',
            name='organization_id',
            field=models.IntegerField(null=True, blank=True, db_index=True),
        ),
        migrations.AddField(
            model_name='tag',
            name='organization_id',
            field=models.IntegerField(null=True, blank=True, db_index=True),
        ),

        # Step 2: Populate organization_id from workspace
        migrations.RunPython(populate_organization_id, reverse_populate),

        # Step 3: Make organization_id non-nullable
        migrations.AlterField(
            model_name='notebook',
            name='organization_id',
            field=models.IntegerField(db_index=True),
        ),
        migrations.AlterField(
            model_name='note',
            name='organization_id',
            field=models.IntegerField(db_index=True),
        ),
        migrations.AlterField(
            model_name='tag',
            name='organization_id',
            field=models.IntegerField(db_index=True),
        ),

        # Step 4: Update unique_together constraints BEFORE removing workspace FK
        # First remove old unique_together that reference workspace
        migrations.AlterUniqueTogether(
            name='notebook',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='tag',
            unique_together=set(),
        ),

        # Step 5: Remove old indexes that reference workspace
        migrations.RemoveIndex(
            model_name='note',
            name='notes_note_workspa_260cba_idx',
        ),

        # Step 6: Remove workspace FK from all models
        migrations.RemoveField(
            model_name='notebook',
            name='workspace',
        ),
        migrations.RemoveField(
            model_name='note',
            name='workspace',
        ),
        migrations.RemoveField(
            model_name='tag',
            name='workspace',
        ),

        # Step 7: Add new unique_together with organization_id
        migrations.AlterUniqueTogether(
            name='notebook',
            unique_together={('organization_id', 'name', 'parent')},
        ),
        migrations.AlterUniqueTogether(
            name='tag',
            unique_together={('organization_id', 'slug')},
        ),

        # Step 8: Add new index for note organization_id + status
        migrations.AddIndex(
            model_name='note',
            index=models.Index(fields=['organization_id', 'status'], name='notes_note_org_id_status_idx'),
        ),

        # Step 9: Add 'evernote' to source choices (just alters the field definition)
        migrations.AlterField(
            model_name='note',
            name='source',
            field=models.CharField(
                choices=[
                    ('manual', 'Manual'),
                    ('import', 'Import'),
                    ('clip', 'Web Clip'),
                    ('email', 'Email'),
                    ('api', 'API'),
                    ('evernote', 'Evernote'),
                ],
                default='manual',
                max_length=100,
            ),
        ),

        # Step 10: Delete WorkspaceMembership first (has FK to Workspace)
        migrations.DeleteModel(
            name='WorkspaceMembership',
        ),

        # Step 11: Delete Workspace
        migrations.DeleteModel(
            name='Workspace',
        ),
    ]
