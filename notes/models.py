"""
Models for Shizuha Notes - Personal note-taking service.
"""
import uuid
import secrets
from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify
from django.contrib.postgres.search import SearchVectorField
from django.contrib.postgres.indexes import GinIndex


class Notebook(models.Model):
    """
    Notebook to organize notes. Each organization has multiple notebooks.
    Supports 2-level hierarchy (stacks) similar to Evernote.
    """
    MAX_DEPTH = 2  # Match Evernote's 2-level stacks

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization_id = models.IntegerField(db_index=True)

    # Identity
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    # Hierarchy support (nested notebooks)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')

    # Appearance
    color = models.CharField(max_length=7, default='#6366f1')  # Hex color
    icon = models.CharField(max_length=50, null=True, blank=True)
    sort_order = models.IntegerField(default=0)

    # Default settings for notes in this notebook
    default_tags = models.JSONField(default=list, blank=True)

    # Status
    is_default = models.BooleanField(default=False, help_text="Default notebook for quick capture")
    is_archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    # Ownership
    created_by_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notes_notebook'
        ordering = ['sort_order', 'name']
        unique_together = [['organization_id', 'name', 'parent']]

    def __str__(self):
        return self.name

    def clean(self):
        """Validate hierarchy - prevent circular refs and depth limit."""
        if self.parent:
            # Cannot be own parent
            if self.pk and self.parent.pk == self.pk:
                raise ValidationError({'parent': 'A notebook cannot be its own parent.'})

            # Check for circular reference (only for existing notebooks)
            if self.pk and self._is_descendant(self.parent):
                raise ValidationError({'parent': 'Circular reference detected.'})

            # Check depth limit - new depth would be parent's depth + 1
            new_depth = self.parent._get_depth() + 1
            if new_depth >= self.MAX_DEPTH:
                raise ValidationError({'parent': f'Maximum nesting depth is {self.MAX_DEPTH} levels.'})

            # Parent must be in the same organization
            if self.parent.organization_id != self.organization_id:
                raise ValidationError({'parent': 'Parent notebook must be in the same organization.'})
            if self.parent.is_archived:
                raise ValidationError({'parent': 'Parent notebook cannot be archived.'})

    def _is_descendant(self, potential_ancestor):
        """Check if potential_ancestor is a descendant of this notebook."""
        children = self.children.all()
        for child in children:
            if child.pk == potential_ancestor.pk:
                return True
            if child._is_descendant(potential_ancestor):
                return True
        return False

    def _get_depth(self):
        """Get the current depth of this notebook in the hierarchy."""
        depth = 0
        current = self
        while current.parent:
            depth += 1
            current = current.parent
            if depth > self.MAX_DEPTH + 1:  # Safety limit
                break
        return depth

    def get_path(self):
        """Return the full path as a list: ['Stack Name', 'Notebook Name']."""
        path = []
        current = self
        while current:
            path.insert(0, current.name)
            current = current.parent
        return path

    def get_path_string(self, separator=' / '):
        """Return the full path as a string."""
        return separator.join(self.get_path())

    def get_ancestors(self):
        """Return list of ancestor notebooks from root to parent."""
        ancestors = []
        current = self.parent
        while current:
            ancestors.insert(0, current)
            current = current.parent
        return ancestors

    def get_descendants(self, include_self=False):
        """Return all descendant notebooks (flattened)."""
        descendants = []
        if include_self:
            descendants.append(self)
        for child in self.children.filter(is_archived=False):
            descendants.append(child)
            descendants.extend(child.get_descendants())
        return descendants

    def move_to(self, new_parent):
        """Move this notebook to a new parent (or to root if new_parent is None)."""
        old_parent = self.parent
        self.parent = new_parent
        self.full_clean()  # Validate
        self.save()
        return old_parent

    def save(self, *args, **kwargs):
        # Validate hierarchy on save
        self.full_clean()

        # If setting as default, unset other defaults belonging to the SAME OWNER
        # in this organization. NTS-51 P1: the previous org-wide clear let one user
        # flip another user's default notebook to false (cross-user mutation with no
        # grant); the default invariant is per-user, so scope it to created_by_id.
        if self.is_default:
            Notebook.objects.filter(
                organization_id=self.organization_id,
                created_by_id=self.created_by_id,
                is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class Tag(models.Model):
    """
    Tags for cross-notebook categorization.

    NTS-51 / NTS-34: tags are PER-USER data, not org-shared taxonomy. Access is
    owner (`created_by_id`) ∪ audited admin break-glass, org-partitioned — the
    same contract as notes and notebooks. `created_by_id` is nullable only to
    carry pre-NTS-51 legacy rows; those are reachable solely by org admins /
    break-glass (fail-closed for ordinary same-org callers) until backfilled.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization_id = models.IntegerField(db_index=True)
    created_by_id = models.IntegerField(null=True, blank=True, db_index=True)

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    color = models.CharField(max_length=7, default='#6b7280')

    # Usage stats
    note_count = models.IntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notes_tag'
        unique_together = [['organization_id', 'slug']]
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Note(models.Model):
    """
    Core note model with rich text content.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('archived', 'Archived'),
        ('trashed', 'Trashed'),
    ]

    SOURCE_CHOICES = [
        ('manual', 'Manual'),
        ('import', 'Import'),
        ('clip', 'Web Clip'),
        ('email', 'Email'),
        ('api', 'API'),
        ('evernote', 'Evernote'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Relations
    organization_id = models.IntegerField(db_index=True)
    notebook = models.ForeignKey(Notebook, on_delete=models.CASCADE, related_name='notes')
    tags = models.ManyToManyField(Tag, blank=True, related_name='notes')

    # Identity
    title = models.CharField(max_length=500, blank=True, default='Untitled')

    # Content (rich text stored as JSON - compatible with TipTap/ProseMirror)
    content_json = models.JSONField(default=dict, blank=True, help_text="Rich text content in JSON format")
    content_text = models.TextField(blank=True, help_text="Plain text extract for search")
    content_html = models.TextField(blank=True, help_text="HTML render for preview")

    # Optimistic-concurrency token (NTS-6). Monotonic per successful update.
    version = models.PositiveIntegerField(default=1)

    # Metadata
    word_count = models.IntegerField(default=0)
    character_count = models.IntegerField(default=0)
    reading_time_minutes = models.IntegerField(default=0)

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    is_pinned = models.BooleanField(default=False)
    is_favorite = models.BooleanField(default=False)

    # Source tracking (for imported notes)
    source = models.CharField(max_length=100, choices=SOURCE_CHOICES, default='manual')
    source_url = models.URLField(null=True, blank=True, max_length=2000)
    external_id = models.CharField(max_length=255, null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    trashed_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    # Ownership
    created_by_id = models.IntegerField()
    created_by_email = models.EmailField(null=True, blank=True)
    last_edited_by_id = models.IntegerField(null=True, blank=True)
    last_edited_by_email = models.EmailField(null=True, blank=True)

    # Full-text search vector (PostgreSQL specific)
    search_vector = SearchVectorField(null=True, blank=True)

    class Meta:
        db_table = 'notes_note'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['organization_id', 'status']),
            models.Index(fields=['notebook', 'status']),
            models.Index(fields=['created_by_id']),
            models.Index(fields=['is_pinned', '-updated_at']),
            models.Index(fields=['status', '-trashed_at']),
            GinIndex(fields=['search_vector']),
        ]

    def __str__(self):
        return f"{self.title} ({self.notebook.name})"

    def save(self, *args, **kwargs):
        # Update metadata from content
        if self.content_text:
            self.word_count = len(self.content_text.split())
            self.character_count = len(self.content_text)
            # Average reading speed: 200 words per minute
            self.reading_time_minutes = max(1, self.word_count // 200)

        # Set trashed_at when moving to trash
        if self.status == 'trashed' and not self.trashed_at:
            self.trashed_at = timezone.now()
        elif self.status != 'trashed':
            self.trashed_at = None

        # Set published_at when publishing
        if self.status == 'published' and not self.published_at:
            self.published_at = timezone.now()

        super().save(*args, **kwargs)

    def trash(self):
        """Move note to trash."""
        self.status = 'trashed'
        self.save()

    def restore(self):
        """Restore note from trash."""
        self.status = 'draft'
        self.trashed_at = None
        self.save()

    def duplicate(self, user_id, *, notebook, tags=(), user_email=None):
        """Create a copy in an explicitly authorized, same-org destination.

        The request layer resolves and authorizes ``notebook``/``tags`` before
        calling this method.  Requiring them here (instead of silently reusing
        the source relations) keeps future call sites from reintroducing the
        NTS-51 copy-path ACL bypass.
        """
        tags = list(tags)
        if notebook.organization_id != self.organization_id or any(
                tag.organization_id != self.organization_id for tag in tags):
            raise ValueError('Copy destinations must match the source note organization.')
        with transaction.atomic():
            new_note = Note.objects.create(
                organization_id=self.organization_id,
                notebook=notebook,
                title=f"{self.title} (Copy)",
                content_json=self.content_json,
                content_text=self.content_text,
                content_html=self.content_html,
                status='draft',
                created_by_id=user_id,
                created_by_email=user_email,
            )
            new_note.tags.set(tags)
        return new_note


class NoteVersion(models.Model):
    """
    Version history for notes (auto-save snapshots).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name='versions')

    # Snapshot content
    title = models.CharField(max_length=500)
    content_json = models.JSONField(default=dict)
    content_text = models.TextField(blank=True)

    # Version metadata
    version_number = models.IntegerField()
    change_summary = models.CharField(max_length=255, blank=True)

    # Who made the change
    created_by_id = models.IntegerField()
    created_by_email = models.EmailField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Diff data (optional, for showing changes)
    diff_data = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'notes_note_version'
        ordering = ['-version_number']
        unique_together = [['note', 'version_number']]

    def __str__(self):
        return f"{self.note.title} v{self.version_number}"


class Attachment(models.Model):
    """
    File attachments for notes.
    """
    TYPE_CHOICES = [
        ('image', 'Image'),
        ('document', 'Document'),
        ('audio', 'Audio'),
        ('video', 'Video'),
        ('other', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name='attachments')

    # File info
    file = models.FileField(upload_to='attachments/%Y/%m/')
    original_filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='other')
    mime_type = models.CharField(max_length=100)
    file_size = models.BigIntegerField()  # bytes

    # Image specific
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    thumbnail = models.ImageField(upload_to='thumbnails/%Y/%m/', null=True, blank=True)

    # Metadata
    caption = models.CharField(max_length=500, blank=True)
    alt_text = models.CharField(max_length=255, blank=True)

    # Processing status
    is_processed = models.BooleanField(default=False)
    processing_error = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    created_by_id = models.IntegerField()

    class Meta:
        db_table = 'notes_attachment'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.original_filename} ({self.note.title})"


class NoteShare(models.Model):
    """
    Sharing notes with specific users or via public links.
    """
    PERMISSION_CHOICES = [
        ('view', 'View Only'),
        ('comment', 'Can Comment'),
        ('edit', 'Can Edit'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name='shares')

    # Share target (either user or authenticated link)
    shared_with_user_id = models.IntegerField(null=True, blank=True)
    shared_with_email = models.EmailField(null=True, blank=True)
    organization_id = models.IntegerField(null=True, blank=True, db_index=True)
    is_public_link = models.BooleanField(default=False)
    public_link_token = models.CharField(max_length=64, unique=True, null=True, blank=True)

    # Permission
    permission = models.CharField(max_length=20, choices=PERMISSION_CHOICES, default='view')
    is_active = models.BooleanField(default=True)

    # Link settings (for public links)
    expires_at = models.DateTimeField(null=True, blank=True)
    password_hash = models.CharField(max_length=128, null=True, blank=True)

    # Stats
    view_count = models.IntegerField(default=0)
    last_viewed_at = models.DateTimeField(null=True, blank=True)

    # Ownership
    shared_by_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'notes_note_share'
        indexes = [
            models.Index(fields=['shared_with_user_id']),
            models.Index(fields=['public_link_token']),
            models.Index(fields=['note', 'shared_with_user_id', 'is_active']),
            models.Index(fields=['note', 'is_active', 'expires_at']),
        ]

    def __str__(self):
        if self.is_public_link:
            return f"Public link for {self.note.title}"
        return f"{self.shared_with_email or self.shared_with_user_id} - {self.note.title}"

    def save(self, *args, **kwargs):
        # Generate public link token if needed
        if self.is_public_link and not self.public_link_token:
            self.public_link_token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def is_valid(self):
        """Check if the share is still valid."""
        if not self.is_active or self.revoked_at:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True


class OwnedObjectShare(models.Model):
    """Durable explicit grant for per-user notebooks and tags (NTS-51).

    Notes retain their richer ``NoteShare`` model.  Notebook/tag authorization
    uses this compact grant so every owned-object path can apply the same
    owner | active share | audited break-glass decision without inventing
    endpoint-local ACLs.
    """

    OBJECT_TYPE_CHOICES = [
        ('notebook', 'Notebook'),
        ('tag', 'Tag'),
    ]
    PERMISSION_CHOICES = NoteShare.PERMISSION_CHOICES

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    object_type = models.CharField(max_length=16, choices=OBJECT_TYPE_CHOICES)
    object_id = models.UUIDField()
    organization_id = models.IntegerField(db_index=True)

    shared_with_user_id = models.IntegerField(null=True, blank=True, db_index=True)
    shared_with_email = models.EmailField(null=True, blank=True, db_index=True)
    permission = models.CharField(max_length=20, choices=PERMISSION_CHOICES, default='view')
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    shared_by_id = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notes_owned_object_share'
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(shared_with_user_id__isnull=False)
                    | models.Q(shared_with_email__isnull=False)
                ),
                name='nts_oos_has_target',
            ),
        ]
        indexes = [
            models.Index(
                fields=['object_type', 'object_id', 'is_active'],
                name='nts_oos_type_obj_active_idx',
            ),
            models.Index(
                fields=['shared_with_user_id', 'organization_id', 'is_active'],
                name='nts_oos_user_org_active_idx',
            ),
            models.Index(
                fields=['shared_with_email', 'organization_id', 'is_active'],
                name='nts_oos_email_org_active_idx',
            ),
        ]

    def is_valid(self):
        if not self.is_active or self.revoked_at:
            return False
        return not self.expires_at or self.expires_at > timezone.now()


class NoteComment(models.Model):
    """
    Comments on shared notes.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name='comments')

    # Author
    author_id = models.IntegerField()
    author_email = models.EmailField()
    author_name = models.CharField(max_length=255, blank=True)

    # Content
    content = models.TextField()

    # Threading
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies')

    # Position in note (for inline comments)
    anchor_json = models.JSONField(null=True, blank=True, help_text="Position reference in note content")

    # Status
    is_resolved = models.BooleanField(default=False)
    resolved_by_id = models.IntegerField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notes_note_comment'
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author_email} on {self.note.title}"

class NoteShareAudit(models.Model):
    """Durable audit trail for NTS-3 share/access/comment lifecycle events."""

    EVENT_CHOICES = [
        ('share_created', 'Share created'),
        ('share_revoked', 'Share revoked'),
        ('share_expired_deny', 'Share expired deny'),
        ('note_accessed', 'Note accessed'),
        ('link_accessed', 'Link accessed'),
        ('comment_added', 'Comment added'),
        ('comment_edited', 'Comment edited'),
        ('comment_deleted', 'Comment deleted'),
        ('comment_resolved', 'Comment resolved'),
        ('comment_unresolved', 'Comment unresolved'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name='share_audit_events')
    actor_id = models.IntegerField(null=True, blank=True)
    event_type = models.CharField(max_length=40, choices=EVENT_CHOICES)
    share = models.ForeignKey(NoteShare, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_events')
    target_user_id = models.IntegerField(null=True, blank=True)
    role = models.CharField(max_length=20, choices=NoteShare.PERMISSION_CHOICES, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'notes_note_share_audit'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['note', '-timestamp']),
            models.Index(fields=['share', '-timestamp']),
            models.Index(fields=['actor_id', '-timestamp']),
            models.Index(fields=['event_type', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.event_type} on {self.note_id} by {self.actor_id}"

class NoteDraft(models.Model):
    """
    Autosave draft — stored separately from canonical note content so interrupted
    edits are recoverable without bypassing the expected_version concurrency guard
    (NTS-9).  Key: (note, user_id, session_key) — one live draft per user per
    session.  Recovery path: list → review base_version vs current note version →
    discard, copy to a new note, or apply via the normal expected_version update.
    """
    MAX_DRAFTS_PER_USER = 10

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name='drafts')

    user_id = models.IntegerField(db_index=True)
    session_key = models.CharField(max_length=255)

    title = models.CharField(max_length=500, blank=True)
    content_json = models.JSONField(default=dict, blank=True)
    base_version = models.PositiveIntegerField(
        help_text='Note version this draft was based on.'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notes_note_draft'
        unique_together = [['note', 'user_id', 'session_key']]
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['note', 'user_id', '-updated_at']),
        ]

    def __str__(self):
        return f'Draft of "{self.note.title}" by user {self.user_id} (session {self.session_key[:8]})'


class AccessAudit(models.Model):
    """NTS-51: durable authorization-decision audit for the single ACL entry
    point — in particular admin **break-glass** grants over owner∪share.

    Break-glass is fail-closed: if this row cannot be persisted the access
    decision is DENIED (see notes.services.access.record_break_glass). Unlike
    the note-scoped NoteShareAudit, this covers any object (note/notebook/tag)
    and never requires a Note FK.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor_id = models.IntegerField(db_index=True)
    actor_email = models.EmailField(null=True, blank=True)
    object_type = models.CharField(max_length=32, db_index=True)   # note|notebook|tag
    object_id = models.CharField(max_length=64, db_index=True)
    organization_id = models.IntegerField(null=True, blank=True, db_index=True)
    event_type = models.CharField(max_length=48)                   # break_glass|deny|...
    decision = models.CharField(max_length=16)                     # allow|deny
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notes_access_audit'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['object_type', 'object_id']),
            models.Index(fields=['actor_id', '-created_at']),
        ]

    def __str__(self):
        return f'{self.event_type}:{self.decision} {self.object_type}:{self.object_id} by {self.actor_id}'
