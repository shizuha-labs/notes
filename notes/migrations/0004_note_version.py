# Generated for NTS-6 optimistic concurrency.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notes', '0003_rename_notes_note_org_id_status_idx_notes_note_organiz_eac83b_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='note',
            name='version',
            field=models.PositiveIntegerField(default=1),
        ),
    ]
