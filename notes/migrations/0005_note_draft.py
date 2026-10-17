# Generated for NTS-9 autosave draft recovery.
import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0004_note_version'),
    ]

    operations = [
        migrations.CreateModel(
            name='NoteDraft',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('user_id', models.IntegerField(db_index=True)),
                ('session_key', models.CharField(max_length=255)),
                ('title', models.CharField(blank=True, max_length=500)),
                ('content_json', models.JSONField(blank=True, default=dict)),
                ('base_version', models.PositiveIntegerField(
                    help_text='Note version this draft was based on.'
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('note', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='drafts',
                    to='notes.note',
                )),
            ],
            options={
                'db_table': 'notes_note_draft',
                'ordering': ['-updated_at'],
            },
        ),
        migrations.AddIndex(
            model_name='notedraft',
            index=models.Index(
                fields=['note', 'user_id', '-updated_at'],
                name='notes_draft_note_user_upd_idx',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='notedraft',
            unique_together={('note', 'user_id', 'session_key')},
        ),
    ]
