from django.contrib import admin
from .models import Notebook, Tag, Note, NoteVersion, Attachment, NoteShare


@admin.register(Notebook)
class NotebookAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization_id', 'parent', 'is_default', 'is_archived', 'created_at')
    list_filter = ('is_default', 'is_archived', 'organization_id')
    search_fields = ('name', 'description')


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization_id', 'slug', 'color', 'note_count', 'last_used_at')
    list_filter = ('organization_id',)
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('title', 'notebook', 'status', 'is_pinned', 'is_favorite', 'created_by_id', 'updated_at')
    list_filter = ('status', 'is_pinned', 'is_favorite', 'organization_id')
    search_fields = ('title', 'content_text')
    readonly_fields = ('word_count', 'character_count', 'reading_time_minutes')


@admin.register(NoteVersion)
class NoteVersionAdmin(admin.ModelAdmin):
    list_display = ('note', 'version_number', 'created_by_id', 'created_at')
    list_filter = ('note__organization_id',)
    search_fields = ('note__title', 'change_summary')


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ('original_filename', 'note', 'file_type', 'file_size', 'is_processed', 'created_at')
    list_filter = ('file_type', 'is_processed')
    search_fields = ('original_filename', 'note__title')


@admin.register(NoteShare)
class NoteShareAdmin(admin.ModelAdmin):
    list_display = ('note', 'shared_with_email', 'permission', 'is_public_link', 'created_at')
    list_filter = ('permission', 'is_public_link')
    search_fields = ('note__title', 'shared_with_email')
