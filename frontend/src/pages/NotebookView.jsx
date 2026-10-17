import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Plus, FileText, Folder, FolderOpen } from 'lucide-react'
import { notebooksApi } from '../services/api'
import { useWorkspace } from '../contexts/WorkspaceContext'
import LoadingSpinner from '../components/LoadingSpinner'
import NoteCard from '../components/NoteCard'
import { formatDistanceToNow } from 'date-fns'

export default function NotebookView() {
  const { id } = useParams()
  const { notebooksTree } = useWorkspace()

  const { data: notebook, isLoading: notebookLoading } = useQuery({
    queryKey: ['notebook', id],
    queryFn: async () => {
      const response = await notebooksApi.get(id)
      return response.data
    },
  })

  const { data: notes = [], isLoading: notesLoading } = useQuery({
    queryKey: ['notebook-notes', id],
    queryFn: async () => {
      const response = await notebooksApi.getNotes(id)
      return response.data.results || response.data
    },
    enabled: !!id,
  })

  // Find this notebook in the tree to get children
  const findInTree = (nodes, targetId) => {
    for (const node of nodes || []) {
      if (node.id === targetId) return node
      const found = findInTree(node.children, targetId)
      if (found) return found
    }
    return null
  }
  const treeNode = findInTree(notebooksTree, id)
  const children = treeNode?.children || []

  if (notebookLoading || notesLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  const hasChildren = children.length > 0
  const hasNotes = notes.length > 0

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            to="/notebooks"
            className="p-2 -ml-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: (notebook?.color || '#6366f1') + '20' }}
            >
              {hasChildren ? (
                <FolderOpen className="h-5 w-5" style={{ color: notebook?.color || '#6366f1' }} />
              ) : (
                <FileText className="h-5 w-5" style={{ color: notebook?.color || '#6366f1' }} />
              )}
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                {notebook?.name}
              </h1>
              {notebook?.description && (
                <p className="text-gray-500 dark:text-gray-400">{notebook.description}</p>
              )}
              {hasChildren && (
                <p className="text-sm text-gray-400 dark:text-gray-500">
                  {children.length} sub-notebooks · {treeNode?.total_note_count || 0} total notes
                </p>
              )}
            </div>
          </div>
        </div>

        <Link
          to={`/notes/new?notebook=${id}`}
          className="flex items-center gap-2 px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700 transition-colors"
        >
          <Plus className="h-5 w-5" />
          New Note
        </Link>
      </div>

      {/* Sub-notebooks grid (if this is a parent notebook) */}
      {hasChildren && (
        <div>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">
            Sub-notebooks
          </h2>
          <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {children.map((child) => (
              <Link
                key={child.id}
                to={`/notebooks/${child.id}`}
                className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-shizuha-300 dark:hover:border-shizuha-600 transition-colors"
              >
                <div
                  className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                  style={{ backgroundColor: (child.color || '#6366f1') + '20' }}
                >
                  <Folder className="h-4 w-4" style={{ color: child.color || '#6366f1' }} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {child.name}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {child.note_count || child.total_note_count || 0} notes
                  </p>
                </div>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Direct notes in this notebook */}
      {hasNotes && (
        <div>
          {hasChildren && (
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-3">
              Notes in this notebook
            </h2>
          )}
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {notes.map((note) => (
              <NoteCard key={note.id} note={note} />
            ))}
          </div>
        </div>
      )}

      {/* Empty state — only if no children AND no notes */}
      {!hasChildren && !hasNotes && (
        <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          <FileText className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-4 text-lg font-medium text-gray-900 dark:text-white">
            No notes in this notebook
          </h3>
          <p className="mt-2 text-gray-500 dark:text-gray-400">
            Create your first note in this notebook.
          </p>
          <Link
            to={`/notes/new?notebook=${id}`}
            className="mt-4 inline-flex items-center px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700"
          >
            Create Note
          </Link>
        </div>
      )}
    </div>
  )
}
