import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft, Save, Trash2, Pin, Star, Share2, Copy,
  MoreVertical, Clock, Tag as TagIcon, Paperclip, FileText,
  Image as ImageIcon, File, X, Download, ExternalLink
} from 'lucide-react'
import { notesApi, attachmentsApi } from '../services/api'
import { resolveNoteEditorContent } from '../utils/noteContent'
import { useWorkspace } from '../contexts/WorkspaceContext'
import RichTextEditor from '../components/RichTextEditor'
import { AttachmentLink, AttachmentThumbnail } from '../components/AttachmentFile'
import LoadingSpinner from '../components/LoadingSpinner'
import { cn } from '../utils/cn'
import { formatDistanceToNow } from 'date-fns'

export default function NoteEditor() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { notebooks, defaultNotebook, tags } = useWorkspace()
  const isNew = !id

  // Track if we've initialized the notebook for new notes (to avoid resetting on defaultNotebook changes)
  const initializedNotebook = useRef(false)
  const savedNoteIdRef = useRef(null)

  // Get notebook from URL query param (e.g., /notes/new?notebook=<uuid>)
  const notebookFromUrl = searchParams.get('notebook')

  const [title, setTitle] = useState('')
  const [content, setContent] = useState({ json: {}, text: '', html: '' })
  const [notebookId, setNotebookId] = useState('')
  const [selectedTags, setSelectedTags] = useState([])
  const [hasChanges, setHasChanges] = useState(false)
  const [showMenu, setShowMenu] = useState(false)
  const [showTagSelector, setShowTagSelector] = useState(false)

  // Fetch existing note
  const { data: note, isLoading } = useQuery({
    queryKey: ['note', id],
    queryFn: async () => {
      const response = await notesApi.get(id)
      return response.data
    },
    enabled: !!id,
  })

  // Fetch attachments for existing note
  const { data: attachmentsData } = useQuery({
    queryKey: ['attachments', id],
    queryFn: async () => {
      const response = await attachmentsApi.list({ note: id })
      return response.data.results || response.data
    },
    enabled: !!id,
  })
  const attachments = attachmentsData || []

  // Reset state when navigating to a different note
  useEffect(() => {
    // Skip reset if we just navigated to the auto-saved note
    if (id && savedNoteIdRef.current === id) {
      savedNoteIdRef.current = null
      return
    }
    initializedNotebook.current = false
    savedNoteIdRef.current = null
    setTitle('')
    setContent({ json: {}, text: '', html: '' })
    setNotebookId('')
    setSelectedTags([])
    setHasChanges(false)
  }, [id])

  // Initialize form with note data
  useEffect(() => {
    if (note) {
      // Existing note: always update from note data
      setTitle(note.title || '')
      // NTS-47: empty content_json + content_text → synthesize TipTap doc.
      setContent({
        json: resolveNoteEditorContent(note),
        text: note.content_text || '',
        html: note.content_html || '',
      })
      setNotebookId(note.notebook)
      setSelectedTags(note.tags || [])
      initializedNotebook.current = true
    } else if (isNew && !initializedNotebook.current) {
      // New note: only set notebook once (from URL param or default)
      // Priority: URL param > defaultNotebook
      if (notebookFromUrl) {
        // Trust the URL parameter - the backend will validate if the notebook exists
        setNotebookId(notebookFromUrl)
        initializedNotebook.current = true
      } else if (defaultNotebook) {
        setNotebookId(defaultNotebook.id)
        initializedNotebook.current = true
      }
    }
  }, [note, isNew, defaultNotebook, notebookFromUrl, notebooks])

  // Helper to invalidate notebook counts (call after note create/delete/move)
  const invalidateNotebookCounts = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['notebooks'] })
    queryClient.invalidateQueries({ queryKey: ['notebooksTree'] })
  }, [queryClient])

  const getCurrentNoteVersion = useCallback(() => {
    const cachedNote = id ? queryClient.getQueryData(['note', id]) : null
    return cachedNote?.version ?? note?.version ?? null
  }, [id, note, queryClient])

  // Auto-save note when upload is attempted on a new (unsaved) note
  const ensureNoteSaved = useCallback(async () => {
    if (id) return id
    if (savedNoteIdRef.current) return savedNoteIdRef.current

    // NTS-73: never auto-create without a notebook (API requires it, FK non-null).
    if (notebooks.length === 0) {
      window.alert('Create a notebook first — a note must live in a notebook.')
      navigate('/notebooks?create=true')
      return null
    }

    const data = {
      title: title || 'Untitled',
      notebook: notebookId,
      content_json: content.json,
      content_text: content.text,
      content_html: content.html,
      tags: selectedTags,
    }

    const response = await notesApi.create(data)
    const newNote = response.data
    savedNoteIdRef.current = newNote.id

    navigate(`/notes/${newNote.id}`, { replace: true })
    queryClient.invalidateQueries({ queryKey: ['notes'] })
    queryClient.invalidateQueries({ queryKey: ['notebook-notes'] })
    invalidateNotebookCounts()
    setHasChanges(false)

    return newNote.id
  }, [id, title, notebookId, content, selectedTags, navigate, queryClient, invalidateNotebookCounts, notebooks])

  // Create mutation
  const createMutation = useMutation({
    mutationFn: async (data) => {
      const response = await notesApi.create(data)
      return response.data
    },
    onSuccess: (data) => {
      // Invalidate all notes lists
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      queryClient.invalidateQueries({ queryKey: ['notebook-notes'] })
      invalidateNotebookCounts() // Update note counts in sidebar
      navigate(`/notes/${data.id}`, { replace: true })
    },
  })

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: async (data) => {
      const response = await notesApi.update(id, data)
      return response.data
    },
    onSuccess: (data, variables) => {
      // Immediately update the note in cache with the response data
      queryClient.setQueryData(['note', id], data)

      // Update all notes list caches immediately with the new title/data
      // This ensures instant UI updates without waiting for refetch
      queryClient.setQueriesData(
        { queryKey: ['notes'], exact: false },
        (oldData) => {
          if (!oldData) return oldData
          const results = oldData.results || oldData
          if (!Array.isArray(results)) return oldData

          const updatedResults = results.map(note =>
            note.id === id
              ? { ...note, title: data.title, updated_at: data.updated_at, status: data.status, version: data.version }
              : note
          )

          return oldData.results
            ? { ...oldData, results: updatedResults }
            : updatedResults
        }
      )

      // Also update notebook-specific note lists
      queryClient.setQueriesData(
        { queryKey: ['notebook-notes'], exact: false },
        (oldData) => {
          if (!oldData || !Array.isArray(oldData)) return oldData
          return oldData.map(note =>
            note.id === id
              ? { ...note, title: data.title, updated_at: data.updated_at, status: data.status, version: data.version }
              : note
          )
        }
      )

      // Still invalidate to ensure eventual consistency (background refetch)
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      queryClient.invalidateQueries({ queryKey: ['notebook-notes'] })

      // If notebook changed, update counts
      if (note && variables.notebook !== note.notebook) {
        invalidateNotebookCounts()
      }
      setHasChanges(false)
    },
    onError: (error) => {
      const status = error.response?.status
      const detail = error.response?.data?.detail || error.response?.data?.error
      if (status === 409) {
        setHasChanges(true)
        queryClient.invalidateQueries({ queryKey: ['note', id] })
        window.alert(
          'This note changed elsewhere before your save completed. The latest version is being reloaded; review your edit and save again to apply it to the new version.'
        )
        return
      }
      if (status === 400 && String(detail || '').toLowerCase().includes('expected_version')) {
        setHasChanges(true)
        queryClient.invalidateQueries({ queryKey: ['note', id] })
        window.alert(
          'This note needs a fresh concurrency token before saving. Reloading the latest version; please save again after it refreshes.'
        )
      }
    },
  })

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: async () => {
      await notesApi.trash(id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      queryClient.invalidateQueries({ queryKey: ['notebook-notes'] })
      invalidateNotebookCounts() // Update note counts in sidebar
      navigate('/notes')
    },
  })

  // Pin mutation
  const pinMutation = useMutation({
    mutationFn: async () => {
      const response = await notesApi.pin(id)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['note', id] })
    },
  })

  // Favorite mutation
  const favoriteMutation = useMutation({
    mutationFn: async () => {
      const response = await notesApi.favorite(id)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['note', id] })
    },
  })

  // Duplicate mutation
  const duplicateMutation = useMutation({
    mutationFn: async () => {
      const response = await notesApi.duplicate(id)
      return response.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['notes'] })
      queryClient.invalidateQueries({ queryKey: ['notebook-notes'] })
      navigate(`/notes/${data.id}`)
    },
  })

  // Delete attachment mutation
  const deleteAttachmentMutation = useMutation({
    mutationFn: async (attachmentId) => {
      await attachmentsApi.delete(attachmentId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['attachments', id] })
      queryClient.invalidateQueries({ queryKey: ['note', id] })
    },
  })

  const handleSave = useCallback(async () => {
    // NTS-73: notebook is required by the API (FK, non-null). An empty-account
    // user has no notebook to attach, so submitting would emit an invalid
    // `notebook: null` request and fail with a non-actionable 400. Block it and
    // route to the create-notebook flow instead.
    if (isNew && notebooks.length === 0) {
      window.alert('Create a notebook first — a note must live in a notebook.')
      navigate('/notebooks?create=true')
      return
    }
    const data = {
      title: title || 'Untitled',
      notebook: notebookId,
      content_json: content.json,
      content_text: content.text,
      content_html: content.html,
      tags: selectedTags,
    }

    if (isNew) {
      createMutation.mutate(data)
    } else {
      const currentVersion = getCurrentNoteVersion()
      if (currentVersion == null) {
        setHasChanges(true)
        queryClient.invalidateQueries({ queryKey: ['note', id] })
        window.alert('This note needs to refresh before it can be saved safely. Please save again after it reloads.')
        return
      }
      updateMutation.mutate({
        ...data,
        expected_version: currentVersion,
      })
    }
  }, [title, notebookId, content, selectedTags, isNew, createMutation, updateMutation, getCurrentNoteVersion, id, queryClient, navigate, notebooks])

  const handleContentChange = (newContent) => {
    setContent(newContent)
    setHasChanges(true)
  }

  const handleTitleChange = (e) => {
    setTitle(e.target.value)
    setHasChanges(true)
  }

  const toggleTag = (tagId) => {
    setSelectedTags((prev) =>
      prev.includes(tagId)
        ? prev.filter((t) => t !== tagId)
        : [...prev, tagId]
    )
    setHasChanges(true)
  }

  // Auto-save on blur
  const handleBlur = useCallback(() => {
    if (hasChanges && !isNew && title) {
      handleSave()
    }
  }, [hasChanges, isNew, title, handleSave])

  // Keyboard shortcut for save
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault()
        if (hasChanges) {
          handleSave()
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [hasChanges, handleSave])

  if (!isNew && isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  const isSaving = createMutation.isPending || updateMutation.isPending

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={() => navigate(-1)}
          className="flex items-center gap-2 text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white"
        >
          <ArrowLeft className="h-5 w-5" />
          Back
        </button>

        <div className="flex items-center gap-2">
          {!isNew && (
            <>
              <button
                onClick={() => pinMutation.mutate()}
                className={cn(
                  'p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-300',
                  note?.is_pinned && 'text-orange-500'
                )}
                title={note?.is_pinned ? 'Unpin' : 'Pin'}
              >
                <Pin className="h-5 w-5" />
              </button>
              <button
                onClick={() => favoriteMutation.mutate()}
                className={cn(
                  'p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-300',
                  note?.is_favorite && 'text-yellow-500'
                )}
                title={note?.is_favorite ? 'Remove from favorites' : 'Add to favorites'}
              >
                <Star className="h-5 w-5" />
              </button>
            </>
          )}

          <button
            onClick={handleSave}
            disabled={isSaving || !hasChanges}
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors',
              hasChanges
                ? 'bg-shizuha-600 text-white hover:bg-shizuha-700'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-400 cursor-not-allowed'
            )}
          >
            {isSaving ? (
              <LoadingSpinner size="sm" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            {isNew ? 'Create' : 'Save'}
          </button>

          {!isNew && (
            <div className="relative">
              <button
                onClick={() => setShowMenu(!showMenu)}
                className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-300"
                data-testid="note-menu-button"
              >
                <MoreVertical className="h-5 w-5" />
              </button>

              {showMenu && (
                <div className="absolute right-0 mt-2 w-48 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1 z-10">
                  <button
                    onClick={() => {
                      duplicateMutation.mutate()
                      setShowMenu(false)
                    }}
                    className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2 text-gray-700 dark:text-gray-200"
                  >
                    <Copy className="h-4 w-4" />
                    Duplicate
                  </button>
                  <button
                    onClick={() => setShowMenu(false)}
                    className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2 text-gray-700 dark:text-gray-200"
                  >
                    <Share2 className="h-4 w-4" />
                    Share
                  </button>
                  <hr className="my-1 border-gray-200 dark:border-gray-700" />
                  <button
                    onClick={() => {
                      if (window.confirm('Move this note to trash?')) {
                        deleteMutation.mutate()
                      }
                      setShowMenu(false)
                    }}
                    className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-2"
                  >
                    <Trash2 className="h-4 w-4" />
                    Move to Trash
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Metadata */}
      <div className="flex flex-wrap items-center gap-4 mb-4">
        {/* Notebook selector */}
        <select
          value={notebookId}
          onChange={(e) => {
            setNotebookId(e.target.value)
            setHasChanges(true)
          }}
          className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200"
        >
          {notebooks.length === 0 ? (
            <option value="">No notebooks - create one first</option>
          ) : (
            notebooks.map((nb) => (
              <option key={nb.id} value={nb.id}>
                {nb.name}
              </option>
            ))
          )}
        </select>

        {/* Tags */}
        <div className="relative">
          <button
            onClick={() => setShowTagSelector(!showTagSelector)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-200"
          >
            <TagIcon className="h-4 w-4" />
            Tags ({selectedTags.length})
          </button>

          {showTagSelector && (
            <div className="absolute left-0 mt-2 w-56 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-2 z-10">
              {tags.length > 0 ? (
                tags.map((tag) => (
                  <label
                    key={tag.id}
                    className="flex items-center gap-2 px-4 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={selectedTags.includes(tag.id)}
                      onChange={() => toggleTag(tag.id)}
                      className="rounded text-shizuha-600"
                    />
                    <span
                      className="w-3 h-3 rounded-full"
                      style={{ backgroundColor: tag.color }}
                    />
                    <span className="text-sm">{tag.name}</span>
                  </label>
                ))
              ) : (
                <p className="px-4 py-2 text-sm text-gray-500">No tags available</p>
              )}
            </div>
          )}
        </div>

        {/* Last updated */}
        {note?.updated_at && (
          <div className="flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400">
            <Clock className="h-4 w-4" />
            Updated {formatDistanceToNow(new Date(note.updated_at), { addSuffix: true })}
          </div>
        )}
      </div>

      {/* Title */}
      <input
        type="text"
        value={title}
        onChange={handleTitleChange}
        onBlur={handleBlur}
        placeholder="Untitled"
        className="w-full text-3xl font-bold bg-transparent border-none outline-none placeholder-gray-400 dark:placeholder-gray-500 text-gray-900 dark:text-white mb-4"
      />

      {/* Editor */}
      <RichTextEditor
        content={content.json}
        onChange={handleContentChange}
        onBlur={handleBlur}
        placeholder="Start writing..."
        noteId={id}
        onEnsureSaved={isNew ? ensureNoteSaved : undefined}
        onAttachmentUploaded={() => {
          // Use prefix match to invalidate all attachment queries — handles the
          // auto-save race where navigation changes `id` before upload completes
          queryClient.invalidateQueries({ queryKey: ['attachments'] })
          const noteId = savedNoteIdRef.current || id
          if (noteId) {
            queryClient.invalidateQueries({ queryKey: ['note', noteId] })
          }
        }}
      />

      {/* Attachments Section */}
      {attachments.length > 0 && (
        <div className="mt-6 border border-gray-200 dark:border-gray-700 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-2">
            <Paperclip className="h-4 w-4" />
            Attachments ({attachments.length})
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {attachments.map((attachment) => (
              <div
                key={attachment.id}
                className="flex items-center gap-3 p-3 bg-gray-50 dark:bg-gray-800 rounded-lg group"
              >
                {/* Icon based on file type */}
                <div className="flex-shrink-0">
                  {attachment.file_type === 'image' ? (
                    <div className="w-10 h-10 rounded overflow-hidden bg-gray-200 dark:bg-gray-700">
                      <AttachmentThumbnail
                        src={attachment.file_url || attachment.file}
                        alt={attachment.original_filename}
                        className="w-full h-full object-cover"
                      />
                    </div>
                  ) : attachment.file_type === 'document' ? (
                    <div className="w-10 h-10 rounded bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                      <FileText className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                    </div>
                  ) : (
                    <div className="w-10 h-10 rounded bg-gray-200 dark:bg-gray-700 flex items-center justify-center">
                      <File className="h-5 w-5 text-gray-500" />
                    </div>
                  )}
                </div>

                {/* File info */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {attachment.original_filename}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {attachment.file_size ? `${(attachment.file_size / 1024).toFixed(1)} KB` : attachment.file_type}
                  </p>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <AttachmentLink
                    src={attachment.file_url || attachment.file}
                    filename={attachment.original_filename}
                    action="open"
                    className="p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
                    title="Open in new tab"
                  >
                    <ExternalLink className="h-4 w-4" />
                  </AttachmentLink>
                  <AttachmentLink
                    src={attachment.file_url || attachment.file}
                    filename={attachment.original_filename}
                    action="download"
                    className="p-1.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-500 dark:text-gray-400"
                    title="Download"
                  >
                    <Download className="h-4 w-4" />
                  </AttachmentLink>
                  <button
                    onClick={() => {
                      if (window.confirm(`Delete "${attachment.original_filename}"?`)) {
                        deleteAttachmentMutation.mutate(attachment.id)
                      }
                    }}
                    className="p-1.5 rounded hover:bg-red-100 dark:hover:bg-red-900/30 text-gray-500 hover:text-red-600 dark:text-gray-400 dark:hover:text-red-400"
                    title="Delete"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
