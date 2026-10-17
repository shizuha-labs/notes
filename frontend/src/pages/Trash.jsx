import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Trash2, RotateCcw, AlertTriangle } from 'lucide-react'
import { trashApi, notesApi } from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'
import { formatDistanceToNow } from 'date-fns'

export default function Trash() {
  const queryClient = useQueryClient()

  const { data: trashedNotes = [], isLoading } = useQuery({
    queryKey: ['trash'],
    queryFn: async () => {
      const response = await trashApi.list()
      return response.data.results || response.data
    },
  })

  const restoreMutation = useMutation({
    mutationFn: async (id) => {
      await notesApi.restore(id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trash'] })
      queryClient.invalidateQueries({ queryKey: ['notes'] })
    },
  })

  const emptyTrashMutation = useMutation({
    mutationFn: async () => {
      await trashApi.empty()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trash'] })
    },
  })

  const deletePermanentlyMutation = useMutation({
    mutationFn: async (id) => {
      await notesApi.delete(id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['trash'] })
    },
  })

  if (isLoading) {
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
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Trash</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Items in trash are automatically deleted after 30 days
          </p>
        </div>
        {trashedNotes.length > 0 && (
          <button
            onClick={() => {
              if (window.confirm('Permanently delete all items in trash? This cannot be undone.')) {
                emptyTrashMutation.mutate()
              }
            }}
            disabled={emptyTrashMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
          >
            <Trash2 className="h-5 w-5" />
            Empty Trash
          </button>
        )}
      </div>

      {/* Trashed notes */}
      {trashedNotes.length > 0 ? (
        <div className="space-y-2">
          {trashedNotes.map((note) => (
            <div
              key={note.id}
              className="flex items-center gap-4 p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700"
            >
              <div className="flex-1 min-w-0">
                <h3 className="font-medium text-gray-900 dark:text-white truncate">
                  {note.title || 'Untitled'}
                </h3>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {note.trashed_at
                    ? `Deleted ${formatDistanceToNow(new Date(note.trashed_at), { addSuffix: true })}`
                    : 'Recently deleted'}
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => restoreMutation.mutate(note.id)}
                  disabled={restoreMutation.isPending}
                  className="flex items-center gap-1 px-3 py-1.5 text-sm text-shizuha-600 hover:bg-shizuha-50 dark:hover:bg-shizuha-900/20 rounded-lg transition-colors"
                >
                  <RotateCcw className="h-4 w-4" />
                  Restore
                </button>
                <button
                  onClick={() => {
                    if (window.confirm('Permanently delete this note? This cannot be undone.')) {
                      deletePermanentlyMutation.mutate(note.id)
                    }
                  }}
                  disabled={deletePermanentlyMutation.isPending}
                  className="flex items-center gap-1 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                >
                  <Trash2 className="h-4 w-4" />
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          <Trash2 className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-4 text-lg font-medium text-gray-900 dark:text-white">Trash is empty</h3>
          <p className="mt-2 text-gray-500 dark:text-gray-400">
            Deleted notes will appear here.
          </p>
        </div>
      )}
    </div>
  )
}
