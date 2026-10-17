import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { Plus, FileText, Grid, List, Filter } from 'lucide-react'
import { useState } from 'react'
import { notesApi } from '../services/api'
import { useWorkspace } from '../contexts/WorkspaceContext'
import LoadingSpinner from '../components/LoadingSpinner'
import NoteCard from '../components/NoteCard'
import { cn } from '../utils/cn'

export default function Notes() {
  const { notebooks, tags } = useWorkspace()
  const [searchParams, setSearchParams] = useSearchParams()
  const [viewMode, setViewMode] = useState('grid')

  const notebookFilter = searchParams.get('notebook')
  const tagFilter = searchParams.get('tag')
  const statusFilter = searchParams.get('status')

  const { data, isLoading } = useQuery({
    queryKey: ['notes', notebookFilter, tagFilter, statusFilter],
    queryFn: async () => {
      const params = {}
      if (notebookFilter) params.notebook = notebookFilter
      if (tagFilter) params.tag = tagFilter
      if (statusFilter) params.status = statusFilter
      const response = await notesApi.list(params)
      return response.data
    },
  })

  const notes = data?.results || data || []

  const updateFilter = (key, value) => {
    const newParams = new URLSearchParams(searchParams)
    if (value) {
      newParams.set(key, value)
    } else {
      newParams.delete(key)
    }
    setSearchParams(newParams)
  }

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
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">All Notes</h1>
        <Link
          to="/notes/new"
          className="flex items-center gap-2 px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700 transition-colors"
        >
          <Plus className="h-5 w-5" />
          New Note
        </Link>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Notebook filter */}
        <select
          value={notebookFilter || ''}
          onChange={(e) => updateFilter('notebook', e.target.value)}
          className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-sm text-gray-700 dark:text-gray-200"
        >
          <option value="">All Notebooks</option>
          {notebooks.map((nb) => (
            <option key={nb.id} value={nb.id}>
              {nb.name}
            </option>
          ))}
        </select>

        {/* Tag filter */}
        <select
          value={tagFilter || ''}
          onChange={(e) => updateFilter('tag', e.target.value)}
          className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-sm text-gray-700 dark:text-gray-200"
        >
          <option value="">All Tags</option>
          {tags.map((tag) => (
            <option key={tag.id} value={tag.id}>
              {tag.name}
            </option>
          ))}
        </select>

        {/* Status filter */}
        <select
          value={statusFilter || ''}
          onChange={(e) => updateFilter('status', e.target.value)}
          className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-sm text-gray-700 dark:text-gray-200"
        >
          <option value="">All Status</option>
          <option value="draft">Draft</option>
          <option value="published">Published</option>
          <option value="archived">Archived</option>
        </select>

        {/* View mode toggle */}
        <div className="ml-auto flex items-center gap-1 p-1 bg-gray-100 dark:bg-gray-800 rounded-lg">
          <button
            onClick={() => setViewMode('grid')}
            className={cn(
              'p-1.5 rounded text-gray-600 dark:text-gray-300',
              viewMode === 'grid'
                ? 'bg-white dark:bg-gray-700 shadow-sm'
                : 'hover:bg-gray-200 dark:hover:bg-gray-600'
            )}
          >
            <Grid className="h-4 w-4" />
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={cn(
              'p-1.5 rounded text-gray-600 dark:text-gray-300',
              viewMode === 'list'
                ? 'bg-white dark:bg-gray-700 shadow-sm'
                : 'hover:bg-gray-200 dark:hover:bg-gray-600'
            )}
          >
            <List className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Notes grid/list */}
      {notes.length > 0 ? (
        <div
          className={cn(
            viewMode === 'grid'
              ? 'grid md:grid-cols-2 lg:grid-cols-3 gap-4'
              : 'space-y-2'
          )}
        >
          {notes.map((note) => (
            <NoteCard key={note.id} note={note} viewMode={viewMode} />
          ))}
        </div>
      ) : (
        <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
          <FileText className="mx-auto h-12 w-12 text-gray-400" />
          <h3 className="mt-4 text-lg font-medium text-gray-900 dark:text-white">No notes found</h3>
          <p className="mt-2 text-gray-500 dark:text-gray-400">
            {notebookFilter || tagFilter
              ? 'Try adjusting your filters.'
              : 'Get started by creating your first note.'}
          </p>
          <Link
            to="/notes/new"
            className="mt-4 inline-flex items-center px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700"
          >
            Create Note
          </Link>
        </div>
      )}
    </div>
  )
}
