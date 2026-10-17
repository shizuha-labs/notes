"""
Serializers for Shizuha Notes API.
"""
import logging

from django.conf import settings
from rest_framework import serializers
from .models import (
    Notebook, Tag,
    Note, NoteVersion, NoteDraft, Attachment, NoteShare, NoteComment
)

logger = logging.getLogger(__name__)


class ScopedRelationsMixin:
    """NTS-51 P1 (GAP-REL): constrain relation inputs (`tags`, `notebook`,
    `parent`) to the caller's AUTHORIZED owned set so a note/notebook cannot be
    created or repointed at another user's / another org's tag or notebook.

    DRF PrimaryKeyRelatedField validates the pk against its queryset, so a
    narrowed queryset yields a fail-closed 400 ("object does not exist") for an
    out-of-scope pk instead of the previous silent cross-org injection.
    """
    _scoped_relation_fields = ('tags', 'notebook', 'parent')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is None:
            return
        from .services.access import authorized_owned_filter
        from .models import Notebook, Tag
        model_for = {
            'tags': (Tag, 'tag'),
            'notebook': (Notebook, 'notebook'),
            'parent': (Notebook, 'notebook'),
        }
        for name in self._scoped_relation_fields:
            field = self.fields.get(name)
            if field is None:
                continue
            model, object_type = model_for[name]
            scoped = model.objects.filter(authorized_owned_filter(
                request, object_type=object_type, minimum_role='edit'
            ))
            if hasattr(field, 'child_relation'):      # many=True (tags)
                field.child_relation.queryset = scoped
            elif hasattr(field, 'queryset'):
                field.queryset = scoped


def _validate_notebook_parent(parent, *, instance=None, organization_id=None):
    """API-level parent validation mirroring Notebook.clean().

    Keep these checks in serializers so invalid user input returns a DRF 400
    instead of bubbling a model ValidationError as a 500.
    """
    if not parent:
        return parent
    if organization_id is not None and parent.organization_id != organization_id:
        raise serializers.ValidationError('Parent notebook must be in the same organization.')
    if parent.is_archived:
        raise serializers.ValidationError('Parent notebook cannot be archived.')
    if instance is not None:
        if parent.pk == instance.pk:
            raise serializers.ValidationError('A notebook cannot be its own parent.')
        if parent in instance.get_descendants():
            raise serializers.ValidationError('Circular reference detected.')
        current_depth = instance._get_depth()
        max_child_depth = 0
        for desc in instance.get_descendants():
            max_child_depth = max(max_child_depth, desc._get_depth() - current_depth)
    else:
        max_child_depth = 0
    new_depth = parent._get_depth() + 1
    if new_depth + max_child_depth >= Notebook.MAX_DEPTH:
        raise serializers.ValidationError(f'Maximum nesting depth is {Notebook.MAX_DEPTH} levels.')
    return parent


def _resolve_shared_with_id(email):
    """
    Resolve an email to a Shizuha ID user_id (int) via the shizuha-id
    internal users endpoint. Returns the integer user_id if resolved,
    else None.

    PLAT-17 (parallels the drive-side PLAT-14 fix): write-side resolution
    so shares get `shared_with_user_id` populated immediately when the
    invitee already exists in shizuha-id. The read-side hybrid-key in
    `SharedWithMeView` remains as the safety net for late registrants.

    Network errors and non-200 responses must return None so share
    creation is never blocked by a shizuha-id outage.
    """
    if not email:
        return None

    import requests

    id_api_url = getattr(settings, 'SHIZUHA_ID_API_URL', 'http://shizuha-id:8001/api')
    try:
        resp = requests.get(
            f"{id_api_url}/internal/users/by-email/",
            params={'email': email},
            timeout=5,
        )
    except Exception as e:
        logger.info("shizuha-id resolve_user_info failed for %s: %s", email, e)
        return None

    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except Exception:
        return None

    user_id = data.get('id')
    if user_id is None:
        return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


# Notebook Serializers
class NotebookSerializer(serializers.ModelSerializer):
    note_count = serializers.SerializerMethodField()
    children_count = serializers.SerializerMethodField()

    class Meta:
        model = Notebook
        fields = [
            'id', 'organization_id', 'name', 'description', 'parent',
            'color', 'icon', 'sort_order', 'default_tags',
            'is_default', 'is_archived', 'archived_at',
            'created_by_id', 'created_at', 'updated_at',
            'note_count', 'children_count'
        ]
        # NTS-51 P1: ownership is immutable via the update serializer. created_by_id
        # was writable, letting a caller reassign their notebook to another user
        # (or, with is_default, mutate that user's default set). Pin it read-only.
        read_only_fields = ['id', 'organization_id', 'created_by_id',
                            'created_at', 'updated_at', 'archived_at']

    def get_note_count(self, obj):
        """NTS-51 P1: count only notes visible through the canonical note ACL —
        the raw reverse relation leaked the count of a shared notebook's unshared
        notes. Fail closed (0) when the request context is absent."""
        request = self.context.get('request')
        if request is None:
            return 0
        from .services.search import build_authorized_queryset
        return build_authorized_queryset(request).filter(
            notebook=obj
        ).exclude(status='trashed').count()

    def get_children_count(self, obj):
        """NTS-51 P1: count only child notebooks the caller is authorized to see."""
        request = self.context.get('request')
        if request is None:
            return 0
        from .services.access import authorized_owned_filter
        return obj.children.filter(is_archived=False).filter(
            authorized_owned_filter(request, object_type='notebook', minimum_role='view')
        ).count()

    def validate_parent(self, value):
        request = self.context.get('request')
        org_id = getattr(request, 'organization_id', None) if request else None
        value = _validate_notebook_parent(value, instance=self.instance, organization_id=org_id)
        # NTS-51 P1: reparenting UNDER a notebook injects into that notebook's tree,
        # so it requires EDIT authority on the target parent — not merely same-org.
        # The update serializer does not carry ScopedRelationsMixin, so gate it here.
        if value is not None and request is not None:
            from .services.access import can_access_owned
            if not can_access_owned(
                request, value, object_type='notebook', minimum_role='edit'
            ).allowed:
                raise serializers.ValidationError(
                    'You do not have edit access to the target parent notebook.'
                )
        return value


class NotebookCreateSerializer(ScopedRelationsMixin, serializers.ModelSerializer):
    class Meta:
        model = Notebook
        fields = ['id', 'name', 'description', 'parent', 'color', 'icon', 'default_tags']
        read_only_fields = ['id']

    def validate_parent(self, value):
        """Validate parent notebook exists and is in the same organization."""
        request = self.context.get('request')
        org_id = getattr(request, 'organization_id', None) if request else None
        return _validate_notebook_parent(value, organization_id=org_id)

    def create(self, validated_data):
        user = self.context['request'].user
        request = self.context['request']
        org_id = getattr(request, 'organization_id', None)
        if not org_id:
            raise serializers.ValidationError({'organization_id': 'Organization context is required.'})

        # Validate parent is in the same org
        parent = validated_data.get('parent')
        if parent and parent.organization_id != org_id:
            raise serializers.ValidationError({'parent': 'Parent notebook must be in the same organization.'})

        validated_data['created_by_id'] = user.id
        validated_data['organization_id'] = org_id
        return super().create(validated_data)


class NotebookTreeSerializer(serializers.ModelSerializer):
    """Hierarchical serializer for notebook tree view."""
    children = serializers.SerializerMethodField()
    note_count = serializers.SerializerMethodField()
    total_note_count = serializers.SerializerMethodField()
    path = serializers.SerializerMethodField()
    depth = serializers.SerializerMethodField()

    class Meta:
        model = Notebook
        fields = [
            'id', 'organization_id', 'name', 'description', 'parent',
            'color', 'icon', 'sort_order', 'default_tags',
            'is_default', 'is_archived', 'archived_at',
            'created_by_id', 'created_at', 'updated_at',
            'children', 'note_count', 'total_note_count', 'path', 'depth'
        ]

    def _authorized_children(self, obj):
        request = self.context.get('request')
        children = obj.children.filter(is_archived=False)
        if request is None:
            return children.none()
        from .services.access import authorized_owned_filter
        return children.filter(authorized_owned_filter(
            request, object_type='notebook', minimum_role='view'
        )).order_by('sort_order', 'name', 'id')

    def get_children(self, obj):
        """Get child notebooks recursively."""
        return NotebookTreeSerializer(
            self._authorized_children(obj), many=True, context=self.context
        ).data

    def get_note_count(self, obj):
        """Count only notes visible through the canonical note ACL."""
        request = self.context.get('request')
        if request is None:
            return 0
        from .services.search import build_authorized_queryset
        return build_authorized_queryset(request).filter(
            notebook=obj
        ).exclude(status='trashed').count()

    def get_total_note_count(self, obj):
        """Count visible notes in this notebook and authorized descendants."""
        count = self.get_note_count(obj)
        for child in self._authorized_children(obj):
            count += self.get_note_count(child)
            for grandchild in self._authorized_children(child):
                count += self.get_note_count(grandchild)
        return count

    def get_path(self, obj):
        """Get the full path as a list."""
        return obj.get_path()

    def get_depth(self, obj):
        """Get the depth in the hierarchy."""
        return obj._get_depth()


class NotebookMoveSerializer(ScopedRelationsMixin, serializers.Serializer):
    """Serializer for moving notebooks."""
    parent = serializers.PrimaryKeyRelatedField(
        queryset=Notebook.objects.all(),
        required=False,
        allow_null=True,
        help_text='New parent notebook ID, or null to move to root level'
    )
    sort_order = serializers.IntegerField(required=False)


# Tag Serializers
class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = [
            'id', 'organization_id', 'name', 'slug', 'color',
            'note_count', 'last_used_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'organization_id', 'slug', 'note_count', 'last_used_at', 'created_at', 'updated_at']


class TagCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['name', 'color']

    def create(self, validated_data):
        request = self.context['request']
        org_id = getattr(request, 'organization_id', None)
        if not org_id:
            raise serializers.ValidationError({'organization_id': 'Organization context is required.'})
        validated_data['organization_id'] = org_id
        # NTS-51: stamp the per-user owner so tags are owner-scoped, not org-shared.
        from .services.access import normalize_user_id
        validated_data['created_by_id'] = normalize_user_id(getattr(request, 'user', None))
        return super().create(validated_data)


# Note Serializers
class NoteListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    notebook_name = serializers.CharField(source='notebook.name', read_only=True)
    tag_names = serializers.SerializerMethodField()
    attachment_count = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = [
            'id', 'title', 'content_text', 'notebook', 'notebook_name', 'status',
            'version', 'is_pinned', 'is_favorite', 'word_count', 'reading_time_minutes',
            'created_at', 'updated_at', 'trashed_at', 'created_by_id',
            'tag_names', 'attachment_count'
        ]

    def get_tag_names(self, obj):
        return list(obj.tags.values_list('name', flat=True))

    def get_attachment_count(self, obj):
        return obj.attachments.count()


class SearchResultSerializer(NoteListSerializer):
    """Additive serializer for search results — extends NoteListSerializer with
    snippet, relevance score, match_reason, and shared_with_me fields derived
    from queryset annotations produced by SearchView."""

    snippet = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    match_reason = serializers.SerializerMethodField()
    shared_with_me = serializers.SerializerMethodField()

    class Meta(NoteListSerializer.Meta):
        fields = NoteListSerializer.Meta.fields + ['snippet', 'score', 'match_reason', 'shared_with_me']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if self.context.get('include_snippets') is False:
            data.pop('snippet', None)
        return data

    def get_snippet(self, obj):
        return getattr(obj, 'snippet', '') or getattr(obj, 'title_snippet', '') or ''

    def get_score(self, obj):
        rank = getattr(obj, 'search_rank', None)
        if rank is None:
            return None
        try:
            return round(float(rank), 4)
        except (TypeError, ValueError):
            return None

    def get_match_reason(self, obj):
        reasons = []
        if (getattr(obj, 'body_rank', 0) or 0) > 0:
            reasons.append('body')
        if (getattr(obj, 'title_similarity', 0) or 0) > 0.3:
            reasons.append('title')
        return reasons

    def get_shared_with_me(self, obj):
        return bool(getattr(obj, 'is_shared_with_me', False))


class NoteSerializer(serializers.ModelSerializer):
    """Full serializer for detail views."""
    notebook_name = serializers.CharField(source='notebook.name', read_only=True)
    tags_detail = TagSerializer(source='tags', many=True, read_only=True)
    tag_names = serializers.SerializerMethodField()
    attachment_count = serializers.SerializerMethodField()
    version_count = serializers.SerializerMethodField()
    share_count = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = [
            'id', 'organization_id', 'notebook', 'notebook_name',
            'title', 'content_json', 'content_text', 'content_html',
            'version', 'word_count', 'character_count', 'reading_time_minutes',
            'status', 'is_pinned', 'is_favorite',
            'source', 'source_url', 'external_id',
            'created_at', 'updated_at', 'trashed_at', 'published_at',
            'created_by_id', 'created_by_email',
            'last_edited_by_id', 'last_edited_by_email',
            'tags', 'tags_detail', 'tag_names',
            'attachment_count', 'version_count', 'share_count'
        ]
        read_only_fields = [
            'id', 'organization_id', 'version', 'word_count', 'character_count', 'reading_time_minutes',
            'created_at', 'updated_at', 'trashed_at', 'published_at',
            'created_by_id', 'created_by_email'
        ]

    def get_tag_names(self, obj):
        return list(obj.tags.values_list('name', flat=True))

    def get_attachment_count(self, obj):
        return obj.attachments.count()

    def get_version_count(self, obj):
        return obj.versions.count()

    def get_share_count(self, obj):
        return obj.shares.filter(revoked_at__isnull=True).count()


class NoteCreateSerializer(ScopedRelationsMixin, serializers.ModelSerializer):
    tags = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Tag.objects.all(), required=False
    )

    class Meta:
        model = Note
        fields = [
            'notebook', 'title', 'content_json', 'content_text', 'content_html',
            'status', 'is_pinned', 'is_favorite', 'source', 'source_url', 'tags'
        ]

    def validate(self, attrs):
        """A note and all of its owned-object relations share one org."""
        notebook = attrs.get('notebook')
        tags = attrs.get('tags', [])
        if notebook is not None and any(
                tag.organization_id != notebook.organization_id for tag in tags):
            raise serializers.ValidationError({
                'tags': 'Tags must be in the same organization as the notebook.'
            })
        return attrs

    def create(self, validated_data):
        user = self.context['request'].user
        request = self.context['request']
        tags = validated_data.pop('tags', [])

        # Set organization_id from notebook
        notebook = validated_data['notebook']
        validated_data['organization_id'] = notebook.organization_id
        validated_data['created_by_id'] = user.id
        validated_data['created_by_email'] = getattr(user, 'email', None)

        note = super().create(validated_data)
        note.tags.set(tags)
        return note


class NoteUpdateSerializer(ScopedRelationsMixin, serializers.ModelSerializer):
    tags = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Tag.objects.all(), required=False
    )
    expected_version = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = Note
        fields = [
            'notebook', 'title', 'content_json', 'content_text', 'content_html',
            'status', 'is_pinned', 'is_favorite', 'tags', 'expected_version'
        ]

    def validate(self, attrs):
        """Keep the note's immutable org consistent with notebook and tags.

        A note may be edit-shared across organizations.  Relation querysets are
        scoped to the request's selected org, so without this object-org check a
        cross-org sharee could attach selected-org relations to a note that stays
        in its original org.
        """
        note_org = self.instance.organization_id
        notebook = attrs.get('notebook')
        if notebook is not None and notebook.organization_id != note_org:
            raise serializers.ValidationError({
                'notebook': 'Notebook must be in the same organization as the note.'
            })
        tags = attrs.get('tags')
        if tags is not None and any(tag.organization_id != note_org for tag in tags):
            raise serializers.ValidationError({
                'tags': 'Tags must be in the same organization as the note.'
            })
        return attrs

    def update(self, instance, validated_data):
        user = self.context['request'].user
        tags = validated_data.pop('tags', None)
        validated_data.pop('expected_version', None)

        # Track editor
        validated_data['last_edited_by_id'] = user.id
        validated_data['last_edited_by_email'] = getattr(user, 'email', None)

        note = super().update(instance, validated_data)

        if tags is not None:
            note.tags.set(tags)

        return note


# Version Serializers
class NoteVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = NoteVersion
        fields = [
            'id', 'note', 'title', 'content_json', 'content_text',
            'version_number', 'change_summary',
            'created_by_id', 'created_by_email', 'created_at',
            'diff_data'
        ]
        read_only_fields = ['id', 'note', 'version_number', 'created_at']


# Attachment Serializers
class AttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = [
            'id', 'note', 'file', 'file_url', 'original_filename',
            'file_type', 'mime_type', 'file_size',
            'width', 'height', 'thumbnail', 'thumbnail_url',
            'caption', 'alt_text',
            'is_processed', 'processing_error',
            'created_at', 'created_by_id'
        ]
        read_only_fields = [
            'id', 'file_type', 'mime_type', 'file_size',
            'width', 'height', 'thumbnail',
            'is_processed', 'processing_error', 'created_at'
        ]

    def get_file_url(self, obj):
        if obj.file:
            request = self.context.get('request')
            # NTS-83: serve the note-scoped edge route, not raw storage. The
            # presigned storage URL names the in-cluster MinIO host and embeds
            # the storage credential identity in the query — the browser can
            # see it and it outlives the session. The edge route authenticates
            # the caller against the same predicate as note reads (serve_file)
            # and keeps the storage credential server-side.
            from django.urls import reverse
            path = reverse('attachment-file', args=[obj.pk])
            if request:
                return request.build_absolute_uri(path)
            return path
        return None

    def get_thumbnail_url(self, obj):
        if obj.thumbnail:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.thumbnail.url)
            return obj.thumbnail.url
        return None

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        # NTS-83 cure (post-merge probe FAIL, cmt 1039007): the legacy
        # `file`/`thumbnail` keys still rendered the raw MinIO presigned
        # URL (in-cluster host + minioadmin credential) even after
        # `file_url` was fixed — "structurally eliminated" held for
        # `file_url` only. Alias both keys to the credential-safe values:
        # the note-scoped edge route for `file`, and the same server-safe
        # route for `thumbnail`. Representation-only — the multipart
        # upload path (AttachmentUploadSerializer) and attachment update
        # writes are untouched; the raw presigned URL no longer reaches
        # the browser in any field.
        rep['file'] = self.get_file_url(instance)
        rep['thumbnail'] = self.get_thumbnail_url(instance)
        return rep


class AttachmentUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ['note', 'file', 'caption', 'alt_text']

    def create(self, validated_data):
        user = self.context['request'].user
        file = validated_data['file']

        # Determine file type from mime type
        mime_type = file.content_type
        if mime_type.startswith('image/'):
            file_type = 'image'
        elif mime_type.startswith('audio/'):
            file_type = 'audio'
        elif mime_type.startswith('video/'):
            file_type = 'video'
        elif mime_type in ['application/pdf', 'application/msword', 'text/plain']:
            file_type = 'document'
        else:
            file_type = 'other'

        validated_data['original_filename'] = file.name
        validated_data['file_type'] = file_type
        validated_data['mime_type'] = mime_type
        validated_data['file_size'] = file.size
        validated_data['created_by_id'] = user.id

        return super().create(validated_data)


# Share Serializers
class NoteShareSerializer(serializers.ModelSerializer):
    note_title = serializers.CharField(source='note.title', read_only=True)
    public_link = serializers.SerializerMethodField()

    class Meta:
        model = NoteShare
        fields = [
            'id', 'note', 'note_title',
            'shared_with_user_id', 'shared_with_email', 'organization_id',
            'is_public_link', 'public_link_token', 'public_link',
            'permission', 'is_active', 'expires_at',
            'view_count', 'last_viewed_at',
            'shared_by_id', 'created_at', 'updated_at', 'revoked_at', 'revoked_by_id'
        ]
        read_only_fields = [
            'id', 'public_link_token', 'is_active', 'view_count', 'last_viewed_at',
            'shared_by_id', 'created_at', 'updated_at', 'revoked_at', 'revoked_by_id'
        ]

    def get_public_link(self, obj):
        if obj.is_public_link and obj.public_link_token:
            request = self.context.get('request')
            if request:
                return f"{request.scheme}://{request.get_host()}/notes/shared/{obj.public_link_token}"
        return None


class NoteShareCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = NoteShare
        fields = [
            'note', 'shared_with_user_id', 'shared_with_email', 'organization_id',
            'is_public_link', 'permission', 'expires_at'
        ]

    def validate(self, attrs):
        if not attrs.get('is_public_link') and not attrs.get('shared_with_user_id') and not attrs.get('shared_with_email'):
            raise serializers.ValidationError('Provide shared_with_user_id/shared_with_email or set is_public_link=true.')
        return attrs

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['shared_by_id'] = user.id

        # PLAT-17: resolve invitee email to a shizuha-id user_id eagerly
        # so any downstream path keyed on shared_with_user_id (notifications,
        # metrics, signals) sees the share immediately. Falls back to None
        # on any failure; SharedWithMeView's existing hybrid-key email
        # fallback (views.py:658-660) covers late registrants.
        email = validated_data.get('shared_with_email')
        if email and not validated_data.get('shared_with_user_id'):
            validated_data['shared_with_user_id'] = _resolve_shared_with_id(email)

        return super().create(validated_data)


# Comment Serializers
class NoteCommentSerializer(serializers.ModelSerializer):
    replies = serializers.SerializerMethodField()

    class Meta:
        model = NoteComment
        fields = [
            'id', 'note', 'author_id', 'author_email', 'author_name',
            'content', 'parent', 'anchor_json',
            'is_resolved', 'resolved_by_id', 'resolved_at',
            'created_at', 'updated_at', 'replies'
        ]
        read_only_fields = ['id', 'author_id', 'author_email', 'created_at', 'updated_at']

    def get_replies(self, obj):
        if obj.replies.exists():
            return NoteCommentSerializer(obj.replies.all(), many=True).data
        return []


class NoteCommentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = NoteComment
        fields = ['note', 'content', 'parent', 'anchor_json']

    def create(self, validated_data):
        user = self.context['request'].user
        validated_data['author_id'] = user.id
        validated_data['author_email'] = getattr(user, 'email', '')
        validated_data['author_name'] = getattr(user, 'username', '')
        return super().create(validated_data)

class NoteDraftSerializer(serializers.ModelSerializer):
    """Read serializer for autosave drafts (NTS-9). is_stale = True when the note
    has moved past the version the draft was based on."""
    is_stale = serializers.SerializerMethodField()

    class Meta:
        model = NoteDraft
        fields = [
            'id', 'note', 'session_key',
            'title', 'content_json',
            'base_version', 'is_stale',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'note', 'created_at', 'updated_at', 'is_stale']

    def get_is_stale(self, obj):
        return obj.base_version < obj.note.version


class NoteDraftSaveSerializer(serializers.Serializer):
    """Write serializer for saving an autosave draft (NTS-9)."""
    session_key = serializers.CharField(max_length=255)
    title = serializers.CharField(max_length=500, allow_blank=True, default='')
    content_json = serializers.JSONField(default=dict)
    base_version = serializers.IntegerField(min_value=1)
