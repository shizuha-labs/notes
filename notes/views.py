"""
Views for Shizuha Notes API.
"""
import logging
from datetime import datetime
from django.db import models as db_models, transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.db.models import Q, Exists, OuterRef, FloatField, TextField, Value, Count, Case, When, IntegerField, Subquery
from django.contrib.postgres.search import (
    SearchQuery, SearchRank, SearchVector, SearchHeadline, TrigramSimilarity,
)
from rest_framework import viewsets, views, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.exceptions import APIException, ValidationError, NotFound, PermissionDenied

from .models import (
    Notebook, Tag,
    Note, NoteVersion, NoteDraft, Attachment, NoteShare, NoteComment
)
from .serializers import (
    NotebookSerializer, NotebookCreateSerializer, NotebookTreeSerializer, NotebookMoveSerializer,
    TagSerializer, TagCreateSerializer,
    NoteSerializer, NoteListSerializer, NoteCreateSerializer, NoteUpdateSerializer,
    NoteVersionSerializer,
    NoteDraftSerializer, NoteDraftSaveSerializer,
    AttachmentSerializer, AttachmentUploadSerializer,
    NoteShareSerializer, NoteShareCreateSerializer,
    NoteCommentSerializer, NoteCommentCreateSerializer,
    SearchResultSerializer,
)
from .permissions import IsNoteOwnerOrOrgMember, OwnedObjectGetMixin
from .middleware import set_organization_context
from .services.version_retention import safe_prune_note_versions
from .services.search import build_authorized_queryset
from .services.access import (
    can_access, has_role, record_audit, active_share_filter,
    authorized_owned_filter, can_access_owned,
)

logger = logging.getLogger(__name__)


class Conflict(APIException):
    """HTTP 409 for stale optimistic-concurrency note updates (NTS-6)."""
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Note changed since it was read; re-pull and retry.'
    default_code = 'conflict'


def _expected_version_from_request(request):
    value = request.data.get('expected_version')
    if value is None:
        value = request.data.get('base_version')
    if value is None:
        value = request.headers.get('If-Match')
    if isinstance(value, str):
        value = value.strip().strip('W/').strip('"')
    return value


def get_user_id(request):
    """Get user ID from request user (works with both regular and federated users).
    Always returns int — JWT tokens store user_id as string but DB fields are int."""
    user = request.user
    uid = getattr(user, 'id', None) or getattr(user, 'pk', None)
    try:
        return int(uid) if uid is not None else None
    except (ValueError, TypeError):
        return uid


def _raise_not_found():
    raise NotFound({'detail': 'Not found.'})


def _require_note_owner(request, note):
    decision = can_access(request.user, note, request=request)
    if not decision.allowed or decision.source != 'owner':
        _raise_not_found()


def _require_note_role(request, note, role):
    decision = can_access(request.user, note, request=request)
    if not decision.allowed:
        _raise_not_found()
    if not has_role(decision, role):
        raise PermissionDenied({'detail': f'{role} role required.'})
    return decision


def _resolve_copy_destination(request, note, *, copy_tags):
    """Resolve every copy endpoint's implicit destination through one ACL gate.

    Copy endpoints historically reused the source notebook/tags after checking
    only the source note share.  A note edit grant is not an edit grant on those
    owned objects.  Require owner/edit-share/audited-break-glass authority for
    each destination object, and refuse to propagate inconsistent cross-org
    relations.  Denials are existence-hiding 404s like other object ACLs.
    """
    notebook = note.notebook
    if notebook.organization_id != note.organization_id or not can_access_owned(
            request, notebook, object_type='notebook', minimum_role='edit').allowed:
        _raise_not_found()

    tags = list(note.tags.all()) if copy_tags else []
    for tag in tags:
        if tag.organization_id != note.organization_id or not can_access_owned(
                request, tag, object_type='tag', minimum_role='edit').allowed:
            _raise_not_found()
    return notebook, tags


class NotebookViewSet(OwnedObjectGetMixin, viewsets.ModelViewSet):
    """
    ViewSet for notebook management.
    """
    serializer_class = NotebookSerializer
    # NTS-51: notebooks are per-user data — owner ∪ audited admin break-glass.
    # OwnedObjectGetMixin is the single object-ACL entry point (prefer-404).
    permission_classes = [permissions.IsAuthenticated]
    owned_object_type = 'notebook'

    def get_queryset(self):
        queryset = Notebook.objects.filter(authorized_owned_filter(
            self.request, object_type='notebook', minimum_role='view'
        )).distinct()

        # Filter archived
        show_archived = self.request.query_params.get('archived', 'false').lower() == 'true'
        if not show_archived:
            queryset = queryset.filter(is_archived=False)

        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return NotebookCreateSerializer
        return NotebookSerializer

    def perform_destroy(self, instance):
        """NTS-51 P1: a notebook DELETE cascades — via ``Notebook.parent`` and
        ``Note.notebook`` ``on_delete=CASCADE`` — to EVERY descendant notebook and
        note. An edit-share on the root must NOT let the caller destroy descendant
        notebooks OR notes they lack edit authority for (the empty-trash data-loss
        class). Authorize every cascaded object before deleting:

        * every DESCENDANT notebook must be owner/edit-authorized (revi: an unshared
          empty child notebook must not be cascade-deleted via a share on the root);
        * every note in the whole subtree must be owner/edit-authorized.

        Crucially the enumeration includes ARCHIVED descendants: ``get_descendants``
        filters ``is_archived=False``, but the DB FK cascade does not, so an archived
        child (and its private notes) would otherwise be deleted unchecked (revi P1).
        """
        from rest_framework.exceptions import PermissionDenied
        from .models import Note, Notebook
        from .services.access import can_access, can_access_owned, has_role
        user = getattr(self.request, 'user', None)

        # revi round-4 P1: authorize + delete must be ONE explicit transaction that
        # LOCKS the whole subtree top-down BEFORE enumerating it. Otherwise it is a
        # check-then-delete TOCTOU: a concurrent request can insert Carol's private
        # note (or a child notebook) into the subtree AFTER the authorization queryset
        # was evaluated but BEFORE the FK cascade fires, and the cascade then deletes
        # a row can_access() never saw. ATOMIC_REQUESTS is NOT set on this service, so
        # the explicit atomic() is required (the prior "already in the request
        # transaction" comment was unsupported).
        #
        # A notebook row held FOR UPDATE blocks any concurrent FK insert that
        # references it (the insert needs FOR KEY SHARE on the parent, which conflicts
        # with FOR UPDATE). So locking each notebook BEFORE querying its children/notes
        # freezes the subtree: a racing insert into an already-locked notebook either
        # blocks until this txn commits the delete, or — if it committed first — is now
        # visible to the enumeration below and authorized (and rejected if unauthorized).
        with transaction.atomic():
            # EVERY descendant notebook the FK cascade will delete, INCLUDING archived
            # ones (unlike get_descendants, which the DB cascade ignores). Each row is
            # locked FOR UPDATE before its children are enumerated.
            def _locked_descendant_ids(root_pk):
                # Lock THIS notebook row first, so an FK insert referencing it cannot
                # slip a new child/note in beneath our enumeration.
                list(Notebook.objects.select_for_update().filter(pk=root_pk))
                ids = [root_pk]
                for child_pk in list(Notebook.objects.select_for_update().filter(
                        parent_id=root_pk).values_list('pk', flat=True)):
                    ids.extend(_locked_descendant_ids(child_pk))
                return ids
            notebook_ids = _locked_descendant_ids(instance.pk)

            # Authorize every cascaded object through the CANONICAL predicate — owner ∪
            # active edit-share ∪ audited admin break-glass (revi round 3: the round-2
            # guard used authorized_owned_filter / NoteShare-only, which exclude the
            # break-glass leg and so wrongly blocked an audited admin's cascade-delete).
            # can_access_owned / can_access record the mandatory per-object break-glass
            # audit and fail CLOSED if that audit cannot persist; any raised denial rolls
            # back every audit + the delete within this atomic block.

            # 1) each DESCENDANT notebook (the root itself was already authorized+audited
            #    by OwnedObjectGetMixin.get_object).
            for nb in Notebook.objects.filter(
                    pk__in=[pk for pk in notebook_ids if pk != instance.pk]):
                if not can_access_owned(
                        self.request, nb, object_type='notebook', minimum_role='edit').allowed:
                    raise PermissionDenied(
                        'Cannot delete a notebook whose descendants include notebooks you '
                        'do not have edit access to. Remove or reassign them first.'
                    )

            # 2) each note in the whole (now frozen) subtree (incl. archived descendants).
            for note in Note.objects.filter(notebook_id__in=notebook_ids):
                decision = can_access(user, note, request=self.request)
                if not has_role(decision, 'edit'):
                    raise PermissionDenied(
                        'Cannot delete a notebook that contains notes you do not have edit '
                        'access to. Remove or reassign those notes first.'
                    )
            super().perform_destroy(instance)

    def perform_update(self, serializer):
        """NTS-51 P1 (revi): ``is_default`` is an OWNER-ONLY per-user preference.
        The model-side clear is scoped to the owner, but the field is still writable
        via the update serializer, so an edit-share (or break-glass) editor could set
        the shared notebook default and thereby REWRITE the OWNER's default set. Reject
        a non-owner's attempt to CHANGE is_default; the owner's own update, and a no-op
        that leaves the current value, are unaffected.
        """
        from .services.access import normalize_user_id
        instance = serializer.instance
        user_id = normalize_user_id(getattr(self.request, 'user', None))
        if (instance is not None
                and 'is_default' in getattr(serializer, 'validated_data', {})
                and instance.created_by_id != user_id
                and bool(serializer.validated_data.get('is_default')) != bool(instance.is_default)):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                'is_default is an owner-only preference and cannot be changed through '
                'a share or break-glass grant.'
            )
        serializer.save()

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        set_organization_context(request)

    @action(detail=True, methods=['get'])
    def notes(self, request, pk=None):
        """List notes in this notebook."""
        # Container and note content are independently authorization-gated.
        notebook = self.container_for_notes(pk)
        notes = build_authorized_queryset(request).filter(notebook=notebook)

        # Apply filters
        status_filter = request.query_params.get('status')
        if status_filter:
            notes = notes.filter(status=status_filter)
        else:
            notes = notes.exclude(status='trashed')

        serializer = NoteListSerializer(notes, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive the notebook."""
        notebook = self.get_object()
        notebook.is_archived = True
        notebook.archived_at = timezone.now()
        notebook.save()
        return Response({'status': 'archived'})

    @action(detail=True, methods=['post'])
    def unarchive(self, request, pk=None):
        """Unarchive the notebook."""
        notebook = self.get_object()
        notebook.is_archived = False
        notebook.archived_at = None
        notebook.save()
        return Response({'status': 'unarchived'})

    @action(detail=False, methods=['get'])
    def tree(self, request):
        """
        Return hierarchical notebook structure.
        Only returns root-level notebooks with children nested.
        """
        queryset = Notebook.objects.filter(
            parent__isnull=True,  # Only root-level notebooks
            is_archived=False
        ).filter(authorized_owned_filter(
            request, object_type='notebook', minimum_role='view'
        )).distinct()

        queryset = queryset.order_by('sort_order', 'name', 'id')
        serializer = NotebookTreeSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def move(self, request, pk=None):
        """
        Move notebook to a new parent.
        Pass { "parent": <notebook_id> } to move into another notebook,
        or { "parent": null } to move to root level.
        """
        notebook = self.get_object()
        # ScopedRelationsMixin requires owner/edit-share authorization on parent.
        serializer = NotebookMoveSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        new_parent = serializer.validated_data.get('parent')
        sort_order = serializer.validated_data.get('sort_order')

        # Validate the move
        if new_parent:
            # Can't move to self
            if new_parent.pk == notebook.pk:
                return Response(
                    {'error': 'Cannot move notebook into itself'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Can't move to own descendant
            if new_parent in notebook.get_descendants():
                return Response(
                    {'error': 'Cannot move notebook into its own descendant'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Must be same organization
            if new_parent.organization_id != notebook.organization_id:
                return Response(
                    {'error': 'Cannot move notebook to different organization'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if new_parent.is_archived:
                return Response(
                    {'error': 'Cannot move notebook under an archived parent'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Check depth limit
            new_depth = new_parent._get_depth() + 1
            max_child_depth = 0
            for desc in notebook.get_descendants():
                child_depth = desc._get_depth() - notebook._get_depth()
                max_child_depth = max(max_child_depth, child_depth)
            if new_depth + max_child_depth >= Notebook.MAX_DEPTH:
                return Response(
                    {'error': f'Move would exceed maximum nesting depth of {Notebook.MAX_DEPTH}'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        old_parent = notebook.parent
        notebook.parent = new_parent
        if sort_order is not None:
            notebook.sort_order = sort_order
        try:
            notebook.save()
        except DjangoValidationError as exc:
            return Response(
                {'error': exc.message_dict if hasattr(exc, 'message_dict') else exc.messages},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            'status': 'moved',
            'old_parent': str(old_parent.pk) if old_parent else None,
            'new_parent': str(new_parent.pk) if new_parent else None,
            'notebook': NotebookSerializer(notebook).data
        })


class TagViewSet(OwnedObjectGetMixin, viewsets.ModelViewSet):
    """
    ViewSet for tag management.
    """
    serializer_class = TagSerializer
    # NTS-51: tags are per-user data — owner ∪ audited admin break-glass.
    permission_classes = [permissions.IsAuthenticated]
    owned_object_type = 'tag'

    def get_queryset(self):
        return Tag.objects.filter(authorized_owned_filter(
            self.request, object_type='tag', minimum_role='view'
        )).distinct()

    def get_serializer_class(self):
        if self.action == 'create':
            return TagCreateSerializer
        return TagSerializer

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        set_organization_context(request)

    @action(detail=True, methods=['get'])
    def notes(self, request, pk=None):
        """List notes with this tag."""
        # Container and note content are independently authorization-gated.
        tag = self.container_for_notes(pk)
        # NTS-38 #1: scope to the caller's authorized notes (owner ∪ share),
        # mirroring the Notebook `notes` action. `tag.notes` alone leaks other
        # org-members' private tagged notes via NoteListSerializer.
        notes = build_authorized_queryset(request).filter(tags=tag).exclude(status='trashed')
        serializer = NoteListSerializer(notes, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def autocomplete(self, request):
        """Tag autocomplete for search UI — org-scoped prefix/fuzzy matching.

        GET /api/tags/autocomplete/?q=<prefix>&limit=10&notebook=<uuid>
        """
        q = request.query_params.get('q', '').strip()
        try:
            limit = min(int(request.query_params.get('limit', 10)), 25)
        except (ValueError, TypeError):
            limit = 10
        notebook_id = request.query_params.get('notebook')

        if not q:
            return Response({'results': []})

        tags = Tag.objects.filter(authorized_owned_filter(
            request, object_type='tag', minimum_role='view'
        )).distinct()
        if notebook_id:
            tags = tags.filter(notes__notebook_id=notebook_id).distinct()

        # NTS-51 P1: the note count (exposed AND used for ranking) must count only
        # notes the caller is authorized to see through the canonical note ACL — the
        # raw Count('notes') leaked/ranked on other members' unshared tagged notes.
        _authorized_note_ids = build_authorized_queryset(request).values('id')
        tags = tags.annotate(
            similarity=TrigramSimilarity('name', q),
            live_note_count=Count(
                'notes', filter=Q(notes__id__in=Subquery(_authorized_note_ids)),
                distinct=True,
            ),
            # NTS-16: rank exact prefix matches above similar-but-non-prefix
            # results (acceptance: "Tags with q prefix ranked above ...").
            is_prefix=Case(
                When(name__istartswith=q, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
        ).filter(
            Q(name__icontains=q) | Q(name__trigram_similar=q)
        ).order_by('-is_prefix', '-similarity', '-live_note_count')[:limit]

        results = [
            {
                'id': str(tag.id),
                'name': tag.name,
                'slug': tag.slug,
                'color': tag.color,
                'note_count': tag.live_note_count,
                'score': round(float(tag.similarity), 4),
            }
            for tag in tags
        ]
        return Response({'results': results})


class NoteViewSet(viewsets.ModelViewSet):
    """
    ViewSet for note management.
    """
    serializer_class = NoteSerializer
    permission_classes = [permissions.IsAuthenticated, IsNoteOwnerOrOrgMember]

    def get_queryset(self):
        queryset = build_authorized_queryset(self.request)
        params = self.request.query_params
        # NoteViewSet exposes only its own scoped params (status, notebook).
        # Full search filter/sort params (tag_ids, sort, shared_with_me, dates)
        # belong on SearchView only — exposing them here would be an undocumented
        # CRUD API expansion with no permission re-check (reviewer P1-1).
        status_param = params.get('status')
        # PLAT-11915: the SPA and QA call GET /notes/?trash=true. Ignoring the
        # flag listed active notes and then excluded the trashed ones.
        trash_flag = (params.get('trash') or '').strip().lower()
        if trash_flag in ('1', 'true', 'yes'):
            queryset = queryset.filter(status='trashed')
        elif status_param:
            queryset = queryset.filter(status=status_param)
        else:
            queryset = queryset.exclude(status='trashed')
        notebook = params.get('notebook')
        if notebook:
            queryset = queryset.filter(notebook_id=notebook)
        # NTS-82: the SPA tag page calls GET /notes/?tag=<uuid>. Ignoring it
        # listed every note, including untagged ones.
        tag = (params.get('tag') or '').strip()
        if tag:
            import uuid
            try:
                uuid.UUID(tag)
            except ValueError:
                queryset = queryset.none()
            else:
                queryset = queryset.filter(tags__id=tag).distinct()
        return queryset.order_by('-is_pinned', '-updated_at')

    def get_serializer_class(self):
        if self.action == 'create':
            return NoteCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return NoteUpdateSerializer
        elif self.action == 'list':
            return NoteListSerializer
        return NoteSerializer

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        set_organization_context(request)

    def create(self, request, *args, **kwargs):
        """Override create to return full serializer with id."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.save()
        # Create initial version
        NoteVersion.objects.create(
            note=note,
            title=note.title,
            content_json=note.content_json,
            content_text=note.content_text,
            version_number=1,
            change_summary='Initial version',
            created_by_id=get_user_id(self.request),
            created_by_email=getattr(self.request.user, 'email', None)
        )
        # Return with full serializer to include id
        response_serializer = NoteSerializer(note, context={'request': request})
        headers = self.get_success_headers(response_serializer.data)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        # This is kept for compatibility but create() handles it now
        return serializer.save()

    def update(self, request, *args, **kwargs):
        """Return the full note representation after guarded updates.

        DRF would otherwise serialize the response with NoteUpdateSerializer,
        hiding the new NTS-6 `version` token that callers need for their next
        edit.
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        instance.refresh_from_db()
        return Response(NoteSerializer(instance, context={'request': request}).data)

    def perform_update(self, serializer):
        expected_version = _expected_version_from_request(self.request)
        if expected_version is None:
            raise ValidationError({
                'expected_version': (
                    'This field is required for note updates. Read the note, pass its current '
                    '`version` as `expected_version`, and retry on 409 by re-reading latest content.'
                )
            })
        try:
            expected_int = int(expected_version)
        except (TypeError, ValueError):
            raise ValidationError({'expected_version': 'Must be an integer note version.'})

        with transaction.atomic():
            current = Note.objects.select_for_update().get(pk=serializer.instance.pk)
            if current.version != expected_int:
                raise Conflict({
                    'error': 'version_conflict',
                    'detail': (
                        f'Note has changed since you read it (you based your edit on '
                        f'v{expected_int}, but it is now v{current.version}). Re-pull the note, '
                        're-apply your intended edit, and retry with the current version.'
                    ),
                    'expected_version': expected_int,
                    'current_version': current.version,
                })

            serializer.instance = current
            note = serializer.save(version=current.version + 1)

            # Create new forward history version only after the guarded write lands.
            latest_version = note.versions.order_by('-version_number').first()
            new_version_number = (latest_version.version_number + 1) if latest_version else 1

            NoteVersion.objects.create(
                note=note,
                title=note.title,
                content_json=note.content_json,
                content_text=note.content_text,
                version_number=new_version_number,
                change_summary='Auto-saved',
                created_by_id=get_user_id(self.request),
                created_by_email=getattr(self.request.user, 'email', None)
            )

            # NTS-7: bound version-history growth. Prune AFTER the guarded write
            # commits so a pruning failure can never roll back the user's save.
            # The newest-N retention keeps the just-written head version.
            note_id = note.id
            transaction.on_commit(lambda: safe_prune_note_versions(note_id))

    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        """List note versions."""
        note = self.get_object()
        versions = note.versions.all()
        serializer = NoteVersionSerializer(versions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='versions/(?P<version_number>[0-9]+)')
    def version_detail(self, request, pk=None, version_number=None):
        """NTS-8: preview a single historical version's content WITHOUT mutating the
        live note, so a client can inspect before deciding to restore. Authorization
        is the same owner/org scope as the note itself (via get_object)."""
        note = self.get_object()
        try:
            version = note.versions.get(version_number=version_number)
        except NoteVersion.DoesNotExist:
            return Response({'error': 'Version not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(NoteVersionSerializer(version).data)

    @action(detail=True, methods=['post'], url_path='restore-version/(?P<version_number>[0-9]+)')
    def restore_version(self, request, pk=None, version_number=None):
        """NTS-8: FORWARD-ONLY restore. Applies historical version <version_number>'s
        content as a NEW canonical save (head version + 1) — restoring v3 onto v10
        creates v11 with v3's content; history is never mutated in place.

        Guarded by the current-head ``expected_version`` (the NTS-6 optimistic-
        concurrency token): a stale restore returns 409 and writes no content/version
        row, so it can never silently clobber a concurrent edit."""
        note = self.get_object()

        expected_version = _expected_version_from_request(request)
        if expected_version is None:
            raise ValidationError({'expected_version': (
                'Required for restore. Read the note, pass its current `version` as '
                '`expected_version`, and retry on 409 by re-reading the latest content.'
            )})
        try:
            expected_int = int(expected_version)
        except (TypeError, ValueError):
            raise ValidationError({'expected_version': 'Must be an integer note version.'})

        try:
            restored_number = int(version_number)
        except (TypeError, ValueError):
            return Response({'error': 'Invalid version number'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            current = Note.objects.select_for_update().get(pk=note.pk)
            try:
                version = current.versions.get(version_number=restored_number)
            except NoteVersion.DoesNotExist:
                return Response({'error': 'Version not found'}, status=status.HTTP_404_NOT_FOUND)

            if current.version != expected_int:
                raise Conflict({
                    'error': 'version_conflict',
                    'detail': (
                        f'Note has changed since you read it (you based your restore on '
                        f'v{expected_int}, but it is now v{current.version}). Re-pull the note '
                        f'and retry with the current version.'
                    ),
                    'expected_version': expected_int,
                    'current_version': current.version,
                })

            current.title = version.title
            current.content_json = version.content_json
            current.content_text = version.content_text
            current.version = current.version + 1
            current.last_edited_by_id = get_user_id(request)
            current.last_edited_by_email = getattr(request.user, 'email', None)
            current.save()

            latest_version = current.versions.order_by('-version_number').first()
            new_version_number = (latest_version.version_number + 1) if latest_version else 1
            NoteVersion.objects.create(
                note=current,
                title=current.title,
                content_json=current.content_json,
                content_text=current.content_text,
                version_number=new_version_number,
                change_summary=f'Restored from v{restored_number}',
                created_by_id=get_user_id(request),
                created_by_email=getattr(request.user, 'email', None)
            )

            # NTS-7: prune AFTER the guarded write commits (on_commit) so a pruning
            # failure can never roll back the restore. Protect the restored-from
            # version so it isn't pruned in the same request.
            note_id = current.id
            transaction.on_commit(lambda: safe_prune_note_versions(note_id, protect=[restored_number]))

        note.refresh_from_db()
        return Response(NoteSerializer(note, context={'request': request}).data)

    @action(detail=True, methods=['post'], url_path='restore-version/(?P<version_number>[0-9]+)/as-copy')
    def restore_version_as_copy(self, request, pk=None, version_number=None):
        """NTS-8: recover a historical version's content into a NEW note, leaving the
        live note untouched. No ``expected_version`` needed — the live note is never
        modified, so there is no concurrency hazard against it."""
        note = self.get_object()
        try:
            version = note.versions.get(version_number=version_number)
        except NoteVersion.DoesNotExist:
            return Response({'error': 'Version not found'}, status=status.HTTP_404_NOT_FOUND)

        uid = get_user_id(request)
        email = getattr(request.user, 'email', None)
        destination_notebook, destination_tags = _resolve_copy_destination(
            request, note, copy_tags=True
        )
        with transaction.atomic():
            copy = Note.objects.create(
                organization_id=note.organization_id,
                notebook=destination_notebook,
                title=f'{version.title} (restored copy)',
                content_json=version.content_json,
                content_text=version.content_text,
                status='draft',
                source=note.source,
                created_by_id=uid,
                created_by_email=email,
                last_edited_by_id=uid,
                last_edited_by_email=email,
            )
            copy.tags.set(destination_tags)
            # Seed the copy's initial version (mirrors create()), recording provenance
            # without logging note content.
            NoteVersion.objects.create(
                note=copy,
                title=copy.title,
                content_json=copy.content_json,
                content_text=copy.content_text,
                version_number=1,
                change_summary=f'Restored as copy from note {note.id} v{version_number}',
                created_by_id=uid,
                created_by_email=email,
            )

        return Response(
            NoteSerializer(copy, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    def _authorized_note(self, request, pk):
        """Lookup that includes trashed notes. get_queryset hides them."""
        try:
            note = build_authorized_queryset(request).get(pk=pk)
        except Note.DoesNotExist:
            raise NotFound({'detail': 'No Note matches the given query.'})
        self.check_object_permissions(request, note)
        return note

    @action(detail=True, methods=['post'])
    def trash(self, request, pk=None):
        """Move note to trash."""
        note = self._authorized_note(request, pk)
        note.trash()
        return Response({'status': 'trashed'})

    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        """Restore note from trash."""
        note = self._authorized_note(request, pk)
        note.restore()
        return Response({'status': 'restored'})

    def retrieve(self, request, *args, **kwargs):
        # A trashed note must stay readable by id so Trash can restore it.
        note = self._authorized_note(request, kwargs.get('pk'))
        return Response(self.get_serializer(note).data)

    @action(detail=True, methods=['post'])
    def pin(self, request, pk=None):
        """Toggle pin status."""
        note = self.get_object()
        note.is_pinned = not note.is_pinned
        note.save()
        return Response({'is_pinned': note.is_pinned})

    @action(detail=True, methods=['post'])
    def favorite(self, request, pk=None):
        """Toggle favorite status."""
        note = self.get_object()
        note.is_favorite = not note.is_favorite
        note.save()
        return Response({'is_favorite': note.is_favorite})

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        """Duplicate the note."""
        note = self.get_object()
        user = request.user
        destination_notebook, destination_tags = _resolve_copy_destination(
            request, note, copy_tags=True
        )
        new_note = note.duplicate(
            user_id=get_user_id(request),
            user_email=getattr(user, 'email', None),
            notebook=destination_notebook,
            tags=destination_tags,
        )
        return Response(
            NoteSerializer(new_note, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get', 'post'])
    def shares(self, request, pk=None):
        """List or create note shares (owner only, NTS-3)."""
        note = self.get_object()
        _require_note_owner(request, note)

        if request.method == 'GET':
            shares = note.shares.filter(is_active=True, revoked_at__isnull=True)
            serializer = NoteShareSerializer(shares, many=True, context={'request': request})
            return Response(serializer.data)

        serializer = NoteShareCreateSerializer(data={**request.data, 'note': note.id}, context={'request': request})
        if serializer.is_valid():
            share = serializer.save()
            record_audit(
                note, get_user_id(request), 'share_created',
                share=share, target_user_id=share.shared_with_user_id, role=share.permission,
            )
            return Response(
                NoteShareSerializer(share, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['delete'], url_path='shares/(?P<share_id>[0-9a-f-]+)')
    def revoke_share(self, request, pk=None, share_id=None):
        """Synchronously revoke a share; next request fails closed."""
        note = self.get_object()
        _require_note_owner(request, note)
        try:
            share = note.shares.get(id=share_id, is_active=True, revoked_at__isnull=True)
        except NoteShare.DoesNotExist:
            _raise_not_found()
        share.is_active = False
        share.revoked_at = timezone.now()
        share.revoked_by_id = get_user_id(request)
        share.save(update_fields=['is_active', 'revoked_at', 'revoked_by_id', 'updated_at'])
        record_audit(
            note, get_user_id(request), 'share_revoked',
            share=share, target_user_id=share.shared_with_user_id, role=share.permission,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get', 'post'])
    def comments(self, request, pk=None):
        """List or create note comments using the shared predicate."""
        note = self.get_object()

        if request.method == 'GET':
            _require_note_role(request, note, 'view')
            comments = note.comments.filter(parent__isnull=True)
            serializer = NoteCommentSerializer(comments, many=True)
            return Response(serializer.data)

        _require_note_role(request, note, 'comment')
        serializer = NoteCommentCreateSerializer(
            data={**request.data, 'note': note.id},
            context={'request': request}
        )
        if serializer.is_valid():
            comment = serializer.save()
            record_audit(note, get_user_id(request), 'comment_added', metadata={'comment_id': str(comment.id)})
            return Response(
                NoteCommentSerializer(comment).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ── NTS-9: Autosave draft recovery ─────────────────────────────────────────

    @action(detail=True, methods=['get', 'post'], url_path='drafts')
    def drafts(self, request, pk=None):
        """
        GET: list recoverable autosave drafts for this note (current user only).
        POST: save/upsert a draft.  Body: {session_key, title, content_json, base_version}.
        Drafts are stored separate from canonical note content and never create NoteVersion
        records — the recovery path re-enters the normal expected_version update flow.
        """
        note = self.get_object()
        user_id = get_user_id(request)

        if request.method == 'GET':
            qs = note.drafts.filter(user_id=user_id)
            return Response(NoteDraftSerializer(qs, many=True).data)

        # POST — save/upsert
        save_serializer = NoteDraftSaveSerializer(data=request.data)
        save_serializer.is_valid(raise_exception=True)
        data = save_serializer.validated_data

        draft, created = NoteDraft.objects.update_or_create(
            note=note,
            user_id=user_id,
            session_key=data['session_key'],
            defaults={
                'title': data.get('title', ''),
                'content_json': data['content_json'],
                'base_version': data['base_version'],
            },
        )

        # Bounded retention: prune oldest drafts for this (note, user) pair beyond the cap.
        draft_ids = list(
            NoteDraft.objects.filter(note=note, user_id=user_id)
            .order_by('-updated_at')
            .values_list('id', flat=True)
        )
        if len(draft_ids) > NoteDraft.MAX_DRAFTS_PER_USER:
            NoteDraft.objects.filter(id__in=draft_ids[NoteDraft.MAX_DRAFTS_PER_USER:]).delete()

        http_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(NoteDraftSerializer(draft).data, status=http_status)

    @action(detail=True, methods=['get', 'delete'],
            url_path='drafts/(?P<draft_id>[0-9a-f-]+)')
    def draft_detail(self, request, pk=None, draft_id=None):
        """
        GET: read a single draft.
        DELETE: discard the draft.
        Only the draft owner (current user) may access their draft.
        """
        note = self.get_object()
        user_id = get_user_id(request)
        try:
            draft = note.drafts.get(id=draft_id, user_id=user_id)
        except NoteDraft.DoesNotExist:
            return Response({'error': 'Draft not found'}, status=status.HTTP_404_NOT_FOUND)

        if request.method == 'DELETE':
            draft.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(NoteDraftSerializer(draft).data)

    @action(detail=True, methods=['post'],
            url_path='drafts/(?P<draft_id>[0-9a-f-]+)/copy')
    def draft_copy(self, request, pk=None, draft_id=None):
        """
        Copy draft content into a new note (live note untouched).
        The new note is returned; caller may then discard the draft.
        """
        note = self.get_object()
        user_id = get_user_id(request)
        try:
            draft = note.drafts.get(id=draft_id, user_id=user_id)
        except NoteDraft.DoesNotExist:
            return Response({'error': 'Draft not found'}, status=status.HTTP_404_NOT_FOUND)

        destination_notebook, _ = _resolve_copy_destination(
            request, note, copy_tags=False
        )
        with transaction.atomic():
            new_note = Note.objects.create(
                organization_id=note.organization_id,
                notebook=destination_notebook,
                title=draft.title or f'{note.title} (draft copy)',
                content_json=draft.content_json,
                status='draft',
                created_by_id=user_id,
                created_by_email=getattr(request.user, 'email', None),
            )
            NoteVersion.objects.create(
                note=new_note,
                title=new_note.title,
                content_json=new_note.content_json,
                content_text=new_note.content_text,
                version_number=1,
                change_summary=f'Copied from draft of note {note.id}',
                created_by_id=user_id,
                created_by_email=getattr(request.user, 'email', None),
            )

        return Response(
            NoteSerializer(new_note, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class AttachmentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for attachment management.
    """
    serializer_class = AttachmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        queryset = Attachment.objects.filter(
            note__in=build_authorized_queryset(self.request)
        ).distinct()

        # Filter by note ID
        note_id = self.request.query_params.get('note')
        if note_id:
            queryset = queryset.filter(note_id=note_id)

        return queryset

    def get_serializer_class(self):
        if self.action == 'create':
            return AttachmentUploadSerializer
        return AttachmentSerializer

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        set_organization_context(request)

    @action(detail=True, methods=['get'], url_path='file', url_name='file')
    def serve_file(self, request, pk=None):
        """Stream the attachment file from storage (MinIO/S3).

        Attachments are note content. Use the same owner/share predicate as note
        reads and return 404 for callers without access instead of exposing
        private files by UUID.
        """
        from django.http import StreamingHttpResponse, Http404
        try:
            attachment = self.get_object()
        except Exception:
            raise Http404
        try:
            f = attachment.file.open('rb')
            response = StreamingHttpResponse(f, content_type=attachment.mime_type)
            response['Content-Disposition'] = f'inline; filename="{attachment.original_filename}"'
            response['Cache-Control'] = 'private, no-store'
            return response
        except Exception:
            raise Http404

    def create(self, request, *args, **kwargs):
        """Override create to return full serializer with file_url."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _require_note_role(request, serializer.validated_data['note'], 'edit')

        # Check storage quota before upload
        from shizuha_storage.mixins import get_quota_client
        from rest_framework.exceptions import ValidationError
        file = request.FILES.get('file')
        client = get_quota_client()
        if client and file and not client.can_upload_from_request(request, file.size):
            raise ValidationError({'file': ['Storage quota exceeded. Please free up space or upgrade your plan.']})

        attachment = serializer.save()

        # Report updated usage to Drive
        if client:
            usage = Attachment.objects.aggregate(
                total_bytes=db_models.Sum('file_size'),
                total_count=db_models.Count('id'),
            )
            client.report_usage_from_request(
                request,
                used_bytes=usage['total_bytes'] or 0,
                file_count=usage['total_count'] or 0,
            )

        # Return with full serializer including file_url
        return Response(
            AttachmentSerializer(attachment, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )

    def perform_update(self, serializer):
        _require_note_role(self.request, serializer.instance.note, 'edit')
        serializer.save()

    def perform_destroy(self, instance):
        _require_note_role(self.request, instance.note, 'edit')
        instance.delete()

        # Report updated usage to Drive after deletion
        from shizuha_storage.mixins import get_quota_client
        client = get_quota_client()
        if client:
            usage = Attachment.objects.aggregate(
                total_bytes=db_models.Sum('file_size'),
                total_count=db_models.Count('id'),
            )
            client.report_usage_from_request(
                self.request,
                used_bytes=usage['total_bytes'] or 0,
                file_count=usage['total_count'] or 0,
            )


_SORT_MAP = {
    'relevance':    ['-search_rank', '-title_similarity', '-updated_at'],
    'updated_desc': ['-updated_at'],
    'updated_asc':  ['updated_at'],
    'created_desc': ['-created_at'],
    'created_asc':  ['created_at'],
    'title_asc':    ['title'],
    'title_desc':   ['-title'],
}


class SearchView(views.APIView):
    """
    Full-text search + filtered browse across notes.

    All params are optional if at least one filter is present when q is absent.
    GET /api/search/?q=&notebook=&tag=&tag_mode=all|any&favorite=&pinned=
                    &shared_with_me=&created_after=&created_before=
                    &updated_after=&updated_before=&status=&sort=relevance
                    &page=1&page_size=20&include_snippets=true
    """
    permission_classes = [permissions.IsAuthenticated]

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _bool(value, default=None):
        if value is None:
            return default
        return str(value).lower() in ('true', '1', 'yes')

    # ------------------------------------------------------------------ #
    # GET                                                                  #
    # ------------------------------------------------------------------ #
    def get(self, request):
        p = request.query_params

        query = p.get('q', '').strip()
        notebook_id = p.get('notebook')
        tag_ids = p.getlist('tag') or [t.strip() for t in p.get('tag_ids', '').split(',') if t.strip()]
        tag_mode = p.get('tag_mode', 'all')
        favorite = self._bool(p.get('favorite'))
        pinned = self._bool(p.get('pinned'))
        shared_with_me = self._bool(p.get('shared_with_me'), default=False)
        def _parse_dt(raw):
            """Parse ISO date string; return None and flag error on failure."""
            if not raw:
                return None, False
            try:
                return datetime.fromisoformat(raw), False
            except (ValueError, TypeError):
                return None, True

        created_after_raw = p.get('created_after')
        created_before_raw = p.get('created_before')
        updated_after_raw = p.get('updated_after')
        updated_before_raw = p.get('updated_before')
        created_after, bad_ca = _parse_dt(created_after_raw)
        created_before, bad_cb = _parse_dt(created_before_raw)
        updated_after, bad_ua = _parse_dt(updated_after_raw)
        updated_before, bad_ub = _parse_dt(updated_before_raw)
        if bad_ca or bad_cb or bad_ua or bad_ub:
            return Response(
                {'detail': 'Invalid date format. Use ISO 8601 (e.g. 2026-06-28T00:00:00).'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        status_param = p.get('status')
        requested_sort = p.get('sort')
        sort = requested_sort or ('relevance' if query else 'updated_desc')
        include_snippets = self._bool(p.get('include_snippets'), default=True)
        try:
            page_size = min(max(int(p.get('page_size', 20)), 1), 50)
        except (ValueError, TypeError):
            page_size = 20
        try:
            page = max(int(p.get('page', 1)), 1)
        except (ValueError, TypeError):
            page = 1

        has_filters = any([
            notebook_id, tag_ids, favorite is not None, pinned is not None,
            shared_with_me, created_after, created_before, updated_after, updated_before,
            status_param,
        ])

        if not query and not has_filters:
            return Response(
                {'error': 'q is required unless at least one filter is provided.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if query and len(query) < 2:
            return Response(
                {'detail': 'q must be at least 2 characters.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if sort not in _SORT_MAP:
            sort = 'relevance' if query else 'updated_desc'

        set_organization_context(request)
        user_id = get_user_id(request)
        user_email = getattr(request.user, 'email', None)

        # ---- Base authorized queryset --------------------------------- #
        qs = build_authorized_queryset(request)

        # Status (default: exclude trashed)
        if status_param:
            qs = qs.filter(status=status_param)
        else:
            qs = qs.exclude(status='trashed')

        # Optional filters
        if notebook_id:
            qs = qs.filter(notebook_id=notebook_id)
        _MAX_TAG_IDS = 10
        if tag_ids:
            if tag_mode == 'any':
                qs = qs.filter(tags__id__in=tag_ids[:_MAX_TAG_IDS])
            else:
                for tid in tag_ids[:_MAX_TAG_IDS]:
                    qs = qs.filter(tags__id=tid)
        if favorite is not None:
            qs = qs.filter(is_favorite=favorite)
        if pinned is not None:
            qs = qs.filter(is_pinned=pinned)
        if shared_with_me:
            qs = qs.filter(active_share_filter(user_id, user_email=user_email, request=request))
        if created_after:
            qs = qs.filter(created_at__gte=created_after)
        if created_before:
            qs = qs.filter(created_at__lt=created_before)
        if updated_after:
            qs = qs.filter(updated_at__gte=updated_after)
        if updated_before:
            qs = qs.filter(updated_at__lt=updated_before)

        # ---- FTS / ranking ------------------------------------------- #
        if query:
            search_query = SearchQuery(query, search_type='websearch', config='english')
            qs = qs.annotate(
                search_rank=SearchRank('search_vector', search_query),
                body_rank=SearchRank(SearchVector('content_text', config='english'), search_query),
                title_similarity=TrigramSimilarity('title', query),
            ).filter(
                # NTS-15: use trigram_word_similar (%> ) not trigram_similar (%).
                # Whole-string similarity misses a verbatim short word inside a long
                # title ("budget" vs "Annual Budget Planning Q4 2024" ≈ 0.23 < 0.3
                # threshold — review P2). Word-similarity scores the query against the
                # closest word in the title, restoring substring recall, and still
                # rides the same GIN gin_trgm_ops index (verified: Bitmap Index Scan).
                Q(search_vector=search_query) | Q(title__trigram_word_similar=query)
            )
            if include_snippets:
                qs = qs.annotate(
                    snippet=SearchHeadline(
                        'content_text',
                        search_query,
                        config='english',
                        start_sel='<mark>',
                        stop_sel='</mark>',
                        max_words=24,
                        min_words=8,
                        short_word=3,
                        highlight_all=False,
                    ),
                    title_snippet=SearchHeadline(
                        'title',
                        search_query,
                        config='english',
                        start_sel='<mark>',
                        stop_sel='</mark>',
                        max_words=12,
                        min_words=1,
                        short_word=3,
                        highlight_all=False,
                    ),
                )
        else:
            # Filter-only browse
            qs = qs.annotate(
                search_rank=Value(0.0, output_field=FloatField()),
                body_rank=Value(0.0, output_field=FloatField()),
                title_similarity=Value(0.0, output_field=FloatField()),
            )
            if include_snippets:
                qs = qs.annotate(snippet=Value('', output_field=TextField()))

        # is_shared_with_me as a SQL Exists annotation (avoids N+1)
        qs = qs.annotate(
            is_shared_with_me=Exists(
                NoteShare.objects.filter(
                    active_share_filter(user_id, user_email=user_email, request=request, related_prefix=''),
                    note=OuterRef('pk'),
                )
            )
        )

        # ---- Sort ---------------------------------------------------- #
        qs = qs.order_by(*_SORT_MAP[sort])

        # ---- Paginate ------------------------------------------------- #
        start = (page - 1) * page_size
        total = qs.count()
        notes = list(qs[start:start + page_size])

        serializer = SearchResultSerializer(
            notes,
            many=True,
            context={'include_snippets': include_snippets},
        )
        return Response({
            'results': serializer.data,
            'count': total,
            'page': page,
            'page_size': page_size,
            'total_pages': (total + page_size - 1) // page_size,
            'sort': sort,
        })


class TrashView(views.APIView):
    """
    Manage trashed notes.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """List trashed notes."""
        notes = build_authorized_queryset(request).filter(status='trashed').order_by('-trashed_at')

        serializer = NoteListSerializer(notes, many=True)
        return Response(serializer.data)

    def delete(self, request):
        """Empty trash (permanently delete all trashed notes)."""
        # Empty-trash is destructive and therefore OWNER-only. Intersecting the
        # canonical owner|share queryset with the owner principal preserves the
        # selected-org boundary without letting a view/comment/edit share delete
        # another user's trashed note.
        authorized_ids = list(
            build_authorized_queryset(request).filter(
                status='trashed', created_by_id=get_user_id(request)
            ).values_list('pk', flat=True)
        )
        # Re-filter by pk to drop the .distinct() (Django forbids delete() after distinct()).
        deleted, _ = Note.objects.filter(pk__in=authorized_ids).delete()
        return Response({'deleted': len(authorized_ids)})


class SharedWithMeView(views.APIView):
    """
    List notes shared with the current user.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user_id = get_user_id(request)
        user_email = getattr(request.user, 'email', None)

        shares = NoteShare.objects.filter(
            active_share_filter(user_id, user_email=user_email, request=request, related_prefix='')
        ).select_related('note')

        # Filter valid shares
        valid_shares = [s for s in shares if s.is_valid()]

        notes = [s.note for s in valid_shares if s.note.status != 'trashed']
        serializer = NoteListSerializer(notes, many=True)
        return Response(serializer.data)


class PublicNoteView(views.APIView):
    """
    View tokenized shared notes. NTS-3 v1 requires authenticated link access.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, token):
        try:
            share = NoteShare.objects.select_related('note').get(
                public_link_token=token,
                is_public_link=True,
                is_active=True,
                revoked_at__isnull=True,
            )
        except NoteShare.DoesNotExist:
            return Response({'error': 'Invalid or expired link'}, status=status.HTTP_404_NOT_FOUND)

        decision = can_access(request.user, share.note, request=request, link_token=token)
        if not decision.allowed or not share.is_valid():
            record_audit(share.note, get_user_id(request), 'share_expired_deny', share=share)
            return Response({'error': 'Invalid or expired link'}, status=status.HTTP_404_NOT_FOUND)

        share.view_count += 1
        share.last_viewed_at = timezone.now()
        share.save(update_fields=['view_count', 'last_viewed_at', 'updated_at'])
        record_audit(share.note, get_user_id(request), 'link_accessed', share=share, role=share.permission)

        note = share.note
        serializer = NoteSerializer(note, context={'request': request})
        return Response({
            'note': serializer.data,
            'permission': share.permission
        })


class BulkNoteView(views.APIView):
    """
    Bulk operations on notes.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, action):
        note_ids = request.data.get('note_ids', [])
        if not note_ids:
            return Response({'error': 'No notes specified'}, status=status.HTTP_400_BAD_REQUEST)

        notes = list(build_authorized_queryset(request).filter(id__in=note_ids).distinct())
        notes = [note for note in notes if has_role(can_access(request.user, note, request=request), 'edit')]

        if action == 'delete':
            for note in notes:
                note.trash()
            return Response({'trashed': len(notes)})

        elif action == 'move':
            notebook_id = request.data.get('notebook_id')
            if not notebook_id:
                return Response({'error': 'No notebook specified'}, status=status.HTTP_400_BAD_REQUEST)
            # Target requires owner/edit-share authorization; org membership
            # alone is not a grant (NTS-51 GAP-NB).
            try:
                notebook = Notebook.objects.filter(authorized_owned_filter(
                    request, object_type='notebook', minimum_role='edit'
                )).get(id=notebook_id)
            except (Notebook.DoesNotExist, DjangoValidationError, ValueError, TypeError):
                return Response({'error': 'Notebook not found'}, status=status.HTTP_404_NOT_FOUND)
            movable = [note.id for note in notes if note.organization_id == notebook.organization_id]
            Note.objects.filter(id__in=movable).update(notebook_id=notebook.id)
            return Response({'moved': len(movable)})

        elif action == 'tag':
            tag_ids = request.data.get('tag_ids', [])
            # Targets require owner/edit-share authorization; same-org IDs owned
            # by somebody else remain fail-closed (NTS-51 GAP-TAG).
            try:
                authorized_tags = list(Tag.objects.filter(
                    authorized_owned_filter(request, object_type='tag', minimum_role='edit'),
                    id__in=tag_ids,
                ))
            except (DjangoValidationError, ValueError, TypeError):
                return Response({'error': 'Tag not found'}, status=status.HTTP_404_NOT_FOUND)
            requested_tag_ids = {str(value) for value in tag_ids}
            if {str(tag.id) for tag in authorized_tags} != requested_tag_ids:
                return Response({'error': 'Tag not found'}, status=status.HTTP_404_NOT_FOUND)
            tagged = 0
            for note in notes:
                note_tag_ids = [t.id for t in authorized_tags if t.organization_id == note.organization_id]
                if note_tag_ids:
                    note.tags.add(*note_tag_ids)
                    tagged += 1
            return Response({'tagged': tagged})

        return Response({'error': 'Unknown action'}, status=status.HTTP_400_BAD_REQUEST)
