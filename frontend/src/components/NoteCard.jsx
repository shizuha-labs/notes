import { Link } from 'react-router-dom'
import { Pin, Star, FileText } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { cn } from '../utils/cn'

export default function NoteCard({ note, viewMode = 'grid' }) {
  if (viewMode === 'list') {
    return (
      <Link
        to={`/notes/${note.id}`}
        className="flex items-center gap-4 p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-shizuha-300 dark:hover:border-shizuha-600 transition-colors"
      >
        <FileText className="h-5 w-5 text-gray-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-gray-900 dark:text-white truncate">
              {note.title || 'Untitled'}
            </h3>
            {note.is_pinned && <Pin className="h-4 w-4 text-orange-500 flex-shrink-0" />}
            {note.is_favorite && <Star className="h-4 w-4 text-yellow-500 flex-shrink-0" />}
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            {note.notebook_name}
          </p>
        </div>
        <div className="text-sm text-gray-400 dark:text-gray-500">
          {formatDistanceToNow(new Date(note.updated_at), { addSuffix: true })}
        </div>
        {note.tag_names?.length > 0 && (
          <div className="hidden lg:flex items-center gap-1">
            {note.tag_names.slice(0, 2).map((tag) => (
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

  return (
    <Link
      to={`/notes/${note.id}`}
      className="block p-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-shizuha-300 dark:hover:border-shizuha-600 transition-colors"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-medium text-gray-900 dark:text-white line-clamp-2">
          {note.title || 'Untitled'}
        </h3>
        <div className="flex items-center gap-1 flex-shrink-0">
          {note.is_pinned && <Pin className="h-4 w-4 text-orange-500" />}
          {note.is_favorite && <Star className="h-4 w-4 text-yellow-500" />}
        </div>
      </div>
      <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{note.notebook_name}</p>
      <p className="mt-3 text-xs text-gray-400 dark:text-gray-500">
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
