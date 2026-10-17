import { useState, useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus, FolderOpen, Folder, MoreVertical, Pencil, Trash2, Archive,
  ChevronRight, ChevronDown, FolderInput
} from 'lucide-react'
import { notebooksApi } from '../services/api'
import { useWorkspace } from '../contexts/WorkspaceContext'
import LoadingSpinner from '../components/LoadingSpinner'
import { cn } from '../utils/cn'

export default function Notebooks() {
  const { notebooks, notebooksTree, notebooksLoading } = useWorkspace()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingNotebook, setEditingNotebook] = useState(null)
  const [createParentId, setCreateParentId] = useState(null)
  const [menuOpen, setMenuOpen] = useState(null)
  // Auto-expand notebooks that have children
  const [expandedIds, setExpandedIds] = useState(() => {
    const ids = new Set()
    notebooksTree?.forEach(nb => {
      if (nb.children?.length > 0) ids.add(nb.id)
    })
    return ids
  })

  // Handle URL params for create/edit from sidebar
  useEffect(() => {
    const create = searchParams.get('create')
    const edit = searchParams.get('edit')
    const parent = searchParams.get('parent')

    if (create === 'true') {
      setCreateParentId(parent || null)
      setShowCreateModal(true)
      setSearchParams({})
    } else if (edit) {
      const notebook = notebooks.find(n => n.id === edit)
      if (notebook) {
        setEditingNotebook(notebook)
        setSearchParams({})
      }
    }
  }, [searchParams, notebooks, setSearchParams])

  const toggleExpanded = (id) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const createMutation = useMutation({
    mutationFn: async (data) => {
      const response = await notebooksApi.create(data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notebooks'] })
      queryClient.invalidateQueries({ queryKey: ['notebooksTree'] })
      setShowCreateModal(false)
      setCreateParentId(null)
    },
    onError: (error) => {
      console.error('Failed to create notebook:', error)
      alert('Failed to create notebook. Please try again.')
    },
  })

  const moveMutation = useMutation({
    mutationFn: async ({ id, parentId }) => {
      const response = await notebooksApi.move(id, parentId)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notebooks'] })
      queryClient.invalidateQueries({ queryKey: ['notebooksTree'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (id) => {
      await notebooksApi.delete(id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notebooks'] })
      queryClient.invalidateQueries({ queryKey: ['notebooksTree'] })
    },
  })

  const archiveMutation = useMutation({
    mutationFn: async (id) => {
      await notebooksApi.archive(id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notebooks'] })
      queryClient.invalidateQueries({ queryKey: ['notebooksTree'] })
    },
  })

  if (notebooksLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Notebooks</h1>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700 transition-colors"
        >
          <Plus className="h-5 w-5" />
          New Notebook
        </button>
      </div>

      {/* Notebooks tree view */}
      {notebooksTree.length > 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          <div className="p-4 space-y-2">
            {notebooksTree.map((notebook) => (
              <NotebookTreeItem
                key={notebook.id}
                notebook={notebook}
                level={0}
                expandedIds={expandedIds}
                toggleExpanded={toggleExpanded}
                menuOpen={menuOpen}
                setMenuOpen={setMenuOpen}
                onEdit={setEditingNotebook}
                onArchive={(nb) => archiveMutation.mutate(nb.id)}
                onDelete={(nb) => {
                  if (window.confirm(`Delete "${nb.name}"? Notes will be moved to trash.`)) {
                    deleteMutation.mutate(nb.id)
                  }
                }}
                onCreateChild={(nb) => {
                  setCreateParentId(nb.id)
                  setShowCreateModal(true)
                }}
                onMove={(nb, parentId) => moveMutation.mutate({ id: nb.id, parentId })}
              />
            ))}
          </div>
        </div>
      ) : (
        <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          <FolderOpen className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-4 text-lg font-medium text-gray-900 dark:text-white">No notebooks yet</h3>
          <p className="mt-2 text-gray-500 dark:text-gray-400">
            Create a notebook to organize your notes.
          </p>
          <button
            onClick={() => setShowCreateModal(true)}
            className="mt-4 inline-flex items-center px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700"
          >
            Create Notebook
          </button>
        </div>
      )}

      {/* Create/Edit Modal */}
      {(showCreateModal || editingNotebook) && (
        <NotebookModal
          notebook={editingNotebook}
          parentId={createParentId}
          notebooks={notebooks}
          onClose={() => {
            setShowCreateModal(false)
            setEditingNotebook(null)
            setCreateParentId(null)
          }}
          onSave={(data) => {
            if (editingNotebook) {
              // Update existing notebook
              notebooksApi.update(editingNotebook.id, data).then(() => {
                queryClient.invalidateQueries({ queryKey: ['notebooks'] })
                queryClient.invalidateQueries({ queryKey: ['notebooksTree'] })
                setEditingNotebook(null)
              })
            } else {
              createMutation.mutate(data)
            }
          }}
          isLoading={createMutation.isPending}
        />
      )}
    </div>
  )
}

/**
 * Tree item component for displaying notebooks hierarchically
 */
function NotebookTreeItem({
  notebook,
  level = 0,
  expandedIds,
  toggleExpanded,
  menuOpen,
  setMenuOpen,
  onEdit,
  onArchive,
  onDelete,
  onCreateChild,
  onMove,
}) {
  const hasChildren = notebook.children && notebook.children.length > 0
  const isExpanded = expandedIds.has(notebook.id)
  const canAddChild = level < 1 // Max depth of 2 means children at level 0 only

  return (
    <div>
      <div
        className={cn(
          'group flex items-center gap-2 p-3 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors',
          level > 0 && 'ml-6'
        )}
      >
        {/* Expand button */}
        <button
          onClick={() => hasChildren && toggleExpanded(notebook.id)}
          className={cn(
            'p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-600',
            !hasChildren && 'opacity-0 pointer-events-none'
          )}
        >
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-gray-500" />
          ) : (
            <ChevronRight className="h-4 w-4 text-gray-500" />
          )}
        </button>

        {/* Notebook link */}
        <Link
          to={`/notebooks/${notebook.id}`}
          className="flex-1 flex items-center gap-3 min-w-0"
        >
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ backgroundColor: notebook.color + '20' }}
          >
            {hasChildren ? (
              <FolderOpen className="h-5 w-5" style={{ color: notebook.color }} />
            ) : (
              <Folder className="h-5 w-5" style={{ color: notebook.color }} />
            )}
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-medium text-gray-900 dark:text-white truncate">
              {notebook.name}
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {notebook.total_note_count || notebook.note_count || 0} notes
              {notebook.children?.length > 0 && ` · ${notebook.children.length} sub-notebooks`}
            </p>
          </div>
          {notebook.is_default && (
            <span className="px-2 py-0.5 text-xs bg-shizuha-100 dark:bg-shizuha-900/30 text-shizuha-700 dark:text-shizuha-300 rounded flex-shrink-0">
              Default
            </span>
          )}
        </Link>

        {/* Menu button */}
        <div className="relative">
          <button
            onClick={(e) => {
              e.preventDefault()
              setMenuOpen(menuOpen === notebook.id ? null : notebook.id)
            }}
            className="p-2 rounded hover:bg-gray-200 dark:hover:bg-gray-600 opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <MoreVertical className="h-4 w-4 text-gray-500" />
          </button>

          {menuOpen === notebook.id && (
            <>
              <div
                className="fixed inset-0 z-10"
                onClick={() => setMenuOpen(null)}
              />
              <div className="absolute right-0 mt-1 w-48 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1 z-20">
                {canAddChild && (
                  <button
                    onClick={() => {
                      onCreateChild?.(notebook)
                      setMenuOpen(null)
                    }}
                    className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2 text-gray-700 dark:text-gray-200"
                  >
                    <Plus className="h-4 w-4" />
                    Add Notebook Inside
                  </button>
                )}
                <button
                  onClick={() => {
                    onEdit?.(notebook)
                    setMenuOpen(null)
                  }}
                  className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2 text-gray-700 dark:text-gray-200"
                >
                  <Pencil className="h-4 w-4" />
                  Edit
                </button>
                {level > 0 && (
                  <button
                    onClick={() => {
                      onMove?.(notebook, null)
                      setMenuOpen(null)
                    }}
                    className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2 text-gray-700 dark:text-gray-200"
                  >
                    <FolderInput className="h-4 w-4" />
                    Move to Root
                  </button>
                )}
                <button
                  onClick={() => {
                    onArchive?.(notebook)
                    setMenuOpen(null)
                  }}
                  className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2 text-gray-700 dark:text-gray-200"
                >
                  <Archive className="h-4 w-4" />
                  Archive
                </button>
                <button
                  onClick={() => {
                    onDelete?.(notebook)
                    setMenuOpen(null)
                  }}
                  className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-2"
                >
                  <Trash2 className="h-4 w-4" />
                  Delete
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Children */}
      {hasChildren && isExpanded && (
        <div className="mt-1 space-y-1">
          {notebook.children.map((child) => (
            <NotebookTreeItem
              key={child.id}
              notebook={child}
              level={level + 1}
              expandedIds={expandedIds}
              toggleExpanded={toggleExpanded}
              menuOpen={menuOpen}
              setMenuOpen={setMenuOpen}
              onEdit={onEdit}
              onArchive={onArchive}
              onDelete={onDelete}
              onCreateChild={onCreateChild}
              onMove={onMove}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function NotebookModal({ notebook, parentId, notebooks = [], onClose, onSave, isLoading }) {
  const [name, setName] = useState(notebook?.name || '')
  const [description, setDescription] = useState(notebook?.description || '')
  const [color, setColor] = useState(notebook?.color || '#6366f1')
  const [parent, setParent] = useState(parentId || notebook?.parent || '')

  // Get valid parent options (root-level notebooks that aren't the current one)
  const parentOptions = notebooks.filter(nb =>
    !nb.parent && // Only root-level notebooks can be parents
    nb.id !== notebook?.id // Can't be own parent
  )

  const colors = [
    '#ef4444', '#f97316', '#eab308', '#22c55e',
    '#14b8a6', '#0ea5e9', '#6366f1', '#a855f7', '#ec4899'
  ]

  const handleSubmit = (e) => {
    e.preventDefault()
    onSave({ name, description, color, parent: parent || null })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-md mx-4">
        <form onSubmit={handleSubmit}>
          <div className="p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
              {notebook ? 'Edit Notebook' : 'Create Notebook'}
            </h2>

            <div className="mt-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
                  placeholder="My Notebook"
                />
              </div>

              {/* Parent notebook selection */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Parent Notebook (Stack)
                </label>
                <select
                  value={parent}
                  onChange={(e) => setParent(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
                >
                  <option value="">None (Root Level)</option>
                  {parentOptions.map((nb) => (
                    <option key={nb.id} value={nb.id}>
                      {nb.name}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  Organize notebooks into stacks (max 2 levels)
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900 text-gray-900 dark:text-white"
                  placeholder="Optional description..."
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Color
                </label>
                <div className="flex gap-2">
                  {colors.map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setColor(c)}
                      className={cn(
                        'w-8 h-8 rounded-full',
                        color === c && 'ring-2 ring-offset-2 ring-gray-900 dark:ring-white dark:ring-offset-gray-800'
                      )}
                      style={{ backgroundColor: c }}
                    />
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="px-6 py-4 bg-gray-50 dark:bg-gray-900/50 rounded-b-lg flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading || !name}
              className="px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700 disabled:opacity-50"
            >
              {isLoading ? <LoadingSpinner size="sm" /> : notebook ? 'Save' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
