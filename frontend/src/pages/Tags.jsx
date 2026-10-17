import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Tag as TagIcon, MoreVertical, Pencil, Trash2 } from 'lucide-react'
import { tagsApi } from '../services/api'
import { useWorkspace } from '../contexts/WorkspaceContext'
import LoadingSpinner from '../components/LoadingSpinner'
import { cn } from '../utils/cn'

export default function Tags() {
  const { tags, tagsLoading } = useWorkspace()
  const queryClient = useQueryClient()
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingTag, setEditingTag] = useState(null)
  const [menuOpen, setMenuOpen] = useState(null)

  const createMutation = useMutation({
    mutationFn: async (data) => {
      const response = await tagsApi.create(data)
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] })
      setShowCreateModal(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: async (id) => {
      await tagsApi.delete(id)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] })
    },
  })

  if (tagsLoading) {
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
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Tags</h1>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700 transition-colors"
        >
          <Plus className="h-5 w-5" />
          New Tag
        </button>
      </div>

      {/* Tags grid */}
      {tags.length > 0 ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {tags.map((tag) => (
            <div
              key={tag.id}
              className="relative group bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4 hover:border-shizuha-300 dark:hover:border-shizuha-600 transition-colors"
            >
              <Link to={`/notes?tag=${tag.id}`} className="block">
                <div className="flex items-center gap-3">
                  <span
                    className="w-4 h-4 rounded-full flex-shrink-0"
                    style={{ backgroundColor: tag.color }}
                  />
                  <div className="min-w-0 flex-1">
                    <h3 className="font-medium text-gray-900 dark:text-white truncate">
                      {tag.name}
                    </h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {tag.note_count || 0} notes
                    </p>
                  </div>
                </div>
              </Link>

              {/* Menu button */}
              <div className="absolute top-4 right-4">
                <button
                  onClick={(e) => {
                    e.preventDefault()
                    setMenuOpen(menuOpen === tag.id ? null : tag.id)
                  }}
                  className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <MoreVertical className="h-4 w-4" />
                </button>

                {menuOpen === tag.id && (
                  <div className="absolute right-0 mt-1 w-32 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1 z-10">
                    <button
                      onClick={() => {
                        setEditingTag(tag)
                        setMenuOpen(null)
                      }}
                      className="w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2"
                    >
                      <Pencil className="h-4 w-4" />
                      Edit
                    </button>
                    <button
                      onClick={() => {
                        if (window.confirm('Delete this tag?')) {
                          deleteMutation.mutate(tag.id)
                        }
                        setMenuOpen(null)
                      }}
                      className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-2"
                    >
                      <Trash2 className="h-4 w-4" />
                      Delete
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          <TagIcon className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-4 text-lg font-medium text-gray-900 dark:text-white">No tags yet</h3>
          <p className="mt-2 text-gray-500 dark:text-gray-400">
            Create tags to organize your notes.
          </p>
          <button
            onClick={() => setShowCreateModal(true)}
            className="mt-4 inline-flex items-center px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700"
          >
            Create Tag
          </button>
        </div>
      )}

      {/* Create/Edit Modal */}
      {(showCreateModal || editingTag) && (
        <TagModal
          tag={editingTag}
          onClose={() => {
            setShowCreateModal(false)
            setEditingTag(null)
          }}
          onSave={(data) => {
            if (editingTag) {
              tagsApi.update(editingTag.id, data).then(() => {
                queryClient.invalidateQueries({ queryKey: ['tags'] })
                setEditingTag(null)
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

function TagModal({ tag, onClose, onSave, isLoading }) {
  const [name, setName] = useState(tag?.name || '')
  const [color, setColor] = useState(tag?.color || '#6b7280')

  const colors = [
    '#ef4444', '#f97316', '#eab308', '#22c55e',
    '#14b8a6', '#0ea5e9', '#6366f1', '#a855f7', '#ec4899', '#6b7280'
  ]

  const handleSubmit = (e) => {
    e.preventDefault()
    onSave({ name, color })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-sm mx-4">
        <form onSubmit={handleSubmit}>
          <div className="p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
              {tag ? 'Edit Tag' : 'Create Tag'}
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
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-900"
                  placeholder="My Tag"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Color
                </label>
                <div className="flex flex-wrap gap-2">
                  {colors.map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => setColor(c)}
                      className={cn(
                        'w-8 h-8 rounded-full',
                        color === c && 'ring-2 ring-offset-2 ring-gray-900 dark:ring-white'
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
              {isLoading ? <LoadingSpinner size="sm" /> : tag ? 'Save' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
