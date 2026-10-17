import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FileText, FolderOpen, Clock, Star, Pin } from 'lucide-react'
import { notesApi, searchApi } from '../services/api'
import { useWorkspace } from '../contexts/WorkspaceContext'
import { useAuth } from '../contexts/AuthContext'
import LoadingSpinner from '../components/LoadingSpinner'
import { formatDistanceToNow } from 'date-fns'
import { dashboardNotes } from '../utils/dashboardData'

const emptyPage = { results: [], count: null }

export default function Dashboard() {
  const { notebooks, notebookCount } = useWorkspace()
  const { organization } = useAuth()

  const { data: recentPage = emptyPage, isLoading: notesLoading } = useQuery({
    queryKey: ['notes', 'recent', organization?.id],
    queryFn: () => dashboardNotes(notesApi, searchApi, 'recent'),
  })
  const { data: pinnedPage = emptyPage } = useQuery({
    queryKey: ['notes', 'pinned', organization?.id],
    queryFn: () => dashboardNotes(notesApi, searchApi, 'pinned'),
  })
  const { data: favoritePage = emptyPage } = useQuery({
    queryKey: ['notes', 'favorites', organization?.id],
    queryFn: () => dashboardNotes(notesApi, searchApi, 'favorite'),
  })
  const recentNotes = recentPage.results.slice(0, 10)
  const pinnedNotes = pinnedPage.results

  if (notesLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Welcome header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Welcome back
        </h1>
        <p className="mt-1 text-gray-600 dark:text-gray-400">
          {organization?.name || 'Notes'}
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={FileText}
          label="Total Notes"
          value={recentPage.count ?? '—'}
          color="bg-blue-500"
        />
        <StatCard
          icon={FolderOpen}
          label="Notebooks"
          value={notebookCount ?? '—'}
          color="bg-green-500"
        />
        <StatCard
          icon={Pin}
          label="Pinned"
          value={pinnedPage.count ?? '—'}
          color="bg-orange-500"
        />
        <StatCard
          icon={Star}
          label="Favorites"
          value={favoritePage.count ?? '—'}
          color="bg-yellow-500"
        />
      </div>

      {/* Pinned notes */}
      {pinnedNotes.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
            <Pin className="h-5 w-5 text-orange-500" />
            Pinned Notes
          </h2>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {pinnedNotes.map((note) => (
              <NoteCard key={note.id} note={note} />
            ))}
          </div>
        </section>
      )}

      {/* Recent notes */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Clock className="h-5 w-5 text-gray-500" />
            Recent Notes
          </h2>
          <Link
            to="/notes"
            className="text-sm text-shizuha-600 hover:text-shizuha-700 dark:text-shizuha-400"
          >
            View all
          </Link>
        </div>
        {recentNotes.length > 0 ? (
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {recentNotes.map((note) => (
              <NoteCard key={note.id} note={note} />
            ))}
          </div>
        ) : (
          <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            <FileText className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-4 text-lg font-medium text-gray-900 dark:text-white">No notes yet</h3>
            <p className="mt-2 text-gray-500 dark:text-gray-400">
              Get started by creating your first note.
            </p>
            <Link
              to="/notes/new"
              className="mt-4 inline-flex items-center px-4 py-2 bg-shizuha-600 text-white rounded-lg hover:bg-shizuha-700"
            >
              Create Note
            </Link>
          </div>
        )}
      </section>

      {/* Notebooks quick access */}
      {notebooks.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <FolderOpen className="h-5 w-5 text-gray-500" />
              Notebooks
            </h2>
            <Link
              to="/notebooks"
              className="text-sm text-shizuha-600 hover:text-shizuha-700 dark:text-shizuha-400"
            >
              View all
            </Link>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {notebooks.slice(0, 8).map((notebook) => (
              <Link
                key={notebook.id}
                to={`/notebooks/${notebook.id}`}
                className="flex items-center gap-3 p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-shizuha-300 dark:hover:border-shizuha-600 transition-colors"
              >
                <span
                  className="w-4 h-4 rounded-full flex-shrink-0"
                  style={{ backgroundColor: notebook.color }}
                />
                <div className="min-w-0">
                  <p className="font-medium text-gray-900 dark:text-white truncate">
                    {notebook.name}
                  </p>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    {notebook.note_count} notes
                  </p>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function StatCard({ icon: Icon, label, value, color }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
      <div className="flex items-center gap-3">
        <div className={`${color} p-2 rounded-lg`}>
          <Icon className="h-5 w-5 text-white" />
        </div>
        <div>
          <p className="text-sm text-gray-500 dark:text-gray-400">{label}</p>
          <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
        </div>
      </div>
    </div>
  )
}

function NoteCard({ note }) {
  return (
    <Link
      to={`/notes/${note.id}`}
      className="block p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-shizuha-300 dark:hover:border-shizuha-600 transition-colors"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-medium text-gray-900 dark:text-white line-clamp-1">
          {note.title || 'Untitled'}
        </h3>
        <div className="flex items-center gap-1">
          {note.is_pinned && <Pin className="h-4 w-4 text-orange-500" />}
          {note.is_favorite && <Star className="h-4 w-4 text-yellow-500" />}
        </div>
      </div>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{note.notebook_name}</p>
      <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
        {formatDistanceToNow(new Date(note.updated_at), { addSuffix: true })}
      </p>
      {note.tag_names?.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {note.tag_names.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="px-2 py-0.5 text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded"
            >
              {tag}
            </span>
          ))}
        </div>
      )}
    </Link>
  )
}
