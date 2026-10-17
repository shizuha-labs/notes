import { useState, useCallback } from 'react'
import { NavLink } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ChevronRight, ChevronDown, FolderOpen, Folder, Plus,
  MoreVertical, Pencil, Trash2, Archive, FolderInput
} from 'lucide-react'
import { notebooksApi } from '../services/api'
import { cn } from '../utils/cn'

/**
 * Recursive tree item component for notebooks
 */
function NotebookTreeItem({
  notebook,
  level = 0,
  expandedIds,
  toggleExpanded,
  onCreateChild,
  onEdit,
  onArchive,
  onDelete,
  onMove,
  maxDepth = 2,
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const hasChildren = notebook.children && notebook.children.length > 0
  const isExpanded = expandedIds.has(notebook.id)
  const canAddChild = level < maxDepth - 1

  return (
    <li>
      <div
        className={cn(
          'group flex items-center gap-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors relative',
          level > 0 && 'ml-4'
        )}
      >
        {/* Expand/collapse button */}
        <button
          onClick={() => hasChildren && toggleExpanded(notebook.id)}
          className={cn(
            'p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-600',
            !hasChildren && 'invisible'
          )}
          disabled={!hasChildren}
        >
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-gray-500" />
          ) : (
            <ChevronRight className="h-4 w-4 text-gray-500" />
          )}
        </button>

        {/* Notebook link */}
        <NavLink
          to={`/notebooks/${notebook.id}`}
          className={({ isActive }) =>
            cn(
              'flex-1 flex items-center gap-2 py-1.5 pr-2 rounded-lg text-sm transition-colors min-w-0',
              isActive
                ? 'text-gray-900 dark:text-white font-medium'
                : 'text-gray-600 dark:text-gray-400'
            )
          }
        >
          {hasChildren ? (
            <FolderOpen className="h-4 w-4 flex-shrink-0" style={{ color: notebook.color }} />
          ) : (
            <Folder className="h-4 w-4 flex-shrink-0" style={{ color: notebook.color }} />
          )}
          <span className="truncate">{notebook.name}</span>
          {notebook.note_count > 0 && (
            <span className="ml-auto text-xs text-gray-400 dark:text-gray-500 flex-shrink-0">
              {notebook.note_count}
            </span>
          )}
        </NavLink>

        {/* Menu button */}
        <div className="relative">
          <button
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              setMenuOpen(!menuOpen)
            }}
            className="p-1 rounded hover:bg-gray-200 dark:hover:bg-gray-600 opacity-0 group-hover:opacity-100 transition-opacity"
          >
            <MoreVertical className="h-4 w-4 text-gray-500" />
          </button>

          {menuOpen && (
            <>
              {/* Backdrop to close menu */}
              <div
                className="fixed inset-0 z-10"
                onClick={() => setMenuOpen(false)}
              />
              <div className="absolute right-0 top-full mt-1 w-44 bg-white dark:bg-gray-800 rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 py-1 z-20">
                {canAddChild && (
                  <button
                    onClick={() => {
                      onCreateChild?.(notebook)
                      setMenuOpen(false)
                    }}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2 text-gray-700 dark:text-gray-200"
                  >
                    <Plus className="h-4 w-4" />
                    Add Notebook Inside
                  </button>
                )}
                <button
                  onClick={() => {
                    onEdit?.(notebook)
                    setMenuOpen(false)
                  }}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2 text-gray-700 dark:text-gray-200"
                >
                  <Pencil className="h-4 w-4" />
                  Edit
                </button>
                {level > 0 && (
                  <button
                    onClick={() => {
                      onMove?.(notebook, null) // Move to root
                      setMenuOpen(false)
                    }}
                    className="w-full px-3 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2 text-gray-700 dark:text-gray-200"
                  >
                    <FolderInput className="h-4 w-4" />
                    Move to Root
                  </button>
                )}
                <button
                  onClick={() => {
                    onArchive?.(notebook)
                    setMenuOpen(false)
                  }}
                  className="w-full px-3 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center gap-2 text-gray-700 dark:text-gray-200"
                >
                  <Archive className="h-4 w-4" />
                  Archive
                </button>
                <button
                  onClick={() => {
                    if (window.confirm(`Delete "${notebook.name}"? Notes will be moved to trash.`)) {
                      onDelete?.(notebook)
                    }
                    setMenuOpen(false)
                  }}
                  className="w-full px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-2"
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
        <ul className="mt-0.5 space-y-0.5">
          {notebook.children.map((child) => (
            <NotebookTreeItem
              key={child.id}
              notebook={child}
              level={level + 1}
              expandedIds={expandedIds}
              toggleExpanded={toggleExpanded}
              onCreateChild={onCreateChild}
              onEdit={onEdit}
              onArchive={onArchive}
              onDelete={onDelete}
              onMove={onMove}
              maxDepth={maxDepth}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

/**
 * NotebookTree - Displays notebooks in a hierarchical tree structure
 */
export default function NotebookTree({
  notebooks = [],
  onCreateNotebook,
  onEditNotebook,
  showHeader = true,
  compact = false,
  className,
}) {
  const queryClient = useQueryClient()
  const [expandedIds, setExpandedIds] = useState(() => new Set())

  const toggleExpanded = useCallback((id) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  // Archive mutation
  const archiveMutation = useMutation({
    mutationFn: (id) => notebooksApi.archive(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notebooks'] })
      queryClient.invalidateQueries({ queryKey: ['notebooksTree'] })
    },
  })

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (id) => notebooksApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notebooks'] })
      queryClient.invalidateQueries({ queryKey: ['notebooksTree'] })
    },
  })

  // Move mutation
  const moveMutation = useMutation({
    mutationFn: ({ id, parentId }) => notebooksApi.move(id, parentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notebooks'] })
      queryClient.invalidateQueries({ queryKey: ['notebooksTree'] })
    },
  })

  const handleArchive = (notebook) => {
    archiveMutation.mutate(notebook.id)
  }

  const handleDelete = (notebook) => {
    deleteMutation.mutate(notebook.id)
  }

  const handleMove = (notebook, newParent) => {
    moveMutation.mutate({ id: notebook.id, parentId: newParent?.id || null })
  }

  const handleCreateChild = (parentNotebook) => {
    // Pass parent info to create modal
    onCreateNotebook?.({ parent: parentNotebook.id })
  }

  if (notebooks.length === 0) {
    return (
      <div className={cn('text-center py-4', className)}>
        <Folder className="mx-auto h-8 w-8 text-gray-400" />
        <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">No notebooks</p>
        {onCreateNotebook && (
          <button
            onClick={() => onCreateNotebook()}
            className="mt-2 text-sm text-shizuha-600 hover:text-shizuha-700 dark:text-shizuha-400"
          >
            Create one
          </button>
        )}
      </div>
    )
  }

  return (
    <div className={className}>
      {showHeader && (
        <div className="flex items-center justify-between px-3 mb-2">
          <h3 className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">
            Notebooks
          </h3>
          {onCreateNotebook && (
            <button
              onClick={() => onCreateNotebook()}
              className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
              title="New Notebook"
            >
              <Plus className="h-4 w-4 text-gray-500" />
            </button>
          )}
        </div>
      )}

      <ul className={cn('space-y-0.5', compact ? 'px-1' : 'px-2')}>
        {notebooks.map((notebook) => (
          <NotebookTreeItem
            key={notebook.id}
            notebook={notebook}
            level={0}
            expandedIds={expandedIds}
            toggleExpanded={toggleExpanded}
            onCreateChild={handleCreateChild}
            onEdit={onEditNotebook}
            onArchive={handleArchive}
            onDelete={handleDelete}
            onMove={handleMove}
          />
        ))}
      </ul>
    </div>
  )
}
