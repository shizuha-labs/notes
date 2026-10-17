from django.core.management.base import BaseCommand
from django.contrib.postgres.search import SearchVector
from notes.models import Note


class Command(BaseCommand):
    help = 'Rebuild the full-text search index for all notes'

    def handle(self, *args, **options):
        self.stdout.write('Rebuilding search index...')

        # Update search vectors for all notes
        notes = Note.objects.all()
        total = notes.count()

        for i, note in enumerate(notes.iterator()):
            Note.objects.filter(pk=note.pk).update(
                search_vector=SearchVector('title', weight='A') + SearchVector('content_text', weight='B')
            )
            if (i + 1) % 100 == 0:
                self.stdout.write(f'Processed {i + 1}/{total} notes...')

        self.stdout.write(
            self.style.SUCCESS(f'Successfully rebuilt search index for {total} notes')
        )
