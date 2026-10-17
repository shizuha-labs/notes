import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Search as SearchIcon, FileText, ChevronLeft, PanelLeftClose, PanelLeftOpen, Maximize2, Minimize2, SlidersHorizontal, X, Star, Pin, Users } from 'lucide-react'
import { searchApi, notesApi, notebooksApi, tagsApi } from '../services/api'
import { resolveNoteEditorContent } from '../utils/noteContent'
import RichTextEditor from '../components/RichTextEditor'
import LoadingSpinner from '../components/LoadingSpinner'
import { formatDistanceToNow } from 'date-fns'
import { cn } from '../utils/cn'

/**
 * Evernote-style split-pane search:
 *   LEFT:  search bar + persistent results list
 *   RIGHT: full note preview with highlighted matches
 *
 * The results list stays visible while you click through notes.
 * No navigation away — everything happens in this view.
 */
export default function Search() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [query, setQuery] = useState(searchParams.get('q') || '')
  const [debouncedQuery, setDebouncedQuery] = useState(query)
  const [selectedNoteId, setSelectedNoteId] = useState(null)
  const [showPreviewMobile, setShowPreviewMobile] = useState(false)
  const [panelCollapsed, setPanelCollapsed] = useState(false)
  const [maximized, setMaximized] = useState(false)
  const inputRef = useRef(null)

  // NTS-19: search filters + sort. All additive — query-only search still works.
  const [showFilters, setShowFilters] = useState(false)
  const [sort, setSort] = useState('relevance')
  const [filters, setFilters] = useState({
    notebook: '',
    tag: '',
    favorite: false,
    pinned: false,
    shared_with_me: false,
    updated_after: '',
    updated_before: '',
  })

  const setFilter = useCallback((key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
  }, [])

  const clearFilters = useCallback(() => {
    setSort('relevance')
    setFilters({
      notebook: '', tag: '', favorite: false, pinned: false,
      shared_with_me: false, updated_after: '', updated_before: '',
    })
  }, [])

  const activeFilterCount = useMemo(() => (
    (filters.notebook ? 1 : 0) +
    (filters.tag ? 1 : 0) +
    (filters.favorite ? 1 : 0) +
    (filters.pinned ? 1 : 0) +
    (filters.shared_with_me ? 1 : 0) +
    (filters.updated_after ? 1 : 0) +
    (filters.updated_before ? 1 : 0) +
    (sort !== 'relevance' ? 1 : 0)
  ), [filters, sort])

  const hasActiveFilters = activeFilterCount > 0

  // Notebooks + tags for the filter pickers (cheap, cached).
  const { data: notebooksData } = useQuery({
    queryKey: ['notebooks-for-search'],
    queryFn: async () => (await notebooksApi.list()).data,
    staleTime: 60_000,
  })
  const { data: tagsData } = useQuery({
    queryKey: ['tags-for-search'],
    queryFn: async () => (await tagsApi.list()).data,
    staleTime: 60_000,
  })
  const notebooks = notebooksData?.results || notebooksData || []
  const tags = tagsData?.results || tagsData || []

  // Build the API param set from the active filters + sort (only non-empty keys).
  const searchFilterParams = useMemo(() => {
    const p = { page_size: 50 }
    if (sort && sort !== 'relevance') p.sort = sort
    if (filters.notebook) p.notebook = filters.notebook
    if (filters.tag) p.tag = filters.tag
    if (filters.favorite) p.favorite = 'true'
    if (filters.pinned) p.pinned = 'true'
    if (filters.shared_with_me) p.shared_with_me = 'true'
    if (filters.updated_after) p.updated_after = filters.updated_after
    if (filters.updated_before) p.updated_before = filters.updated_before
    return p
  }, [sort, filters])

  // Sync query from URL params (when navigating from GlobalSearch bar)
  useEffect(() => {
    const urlQuery = searchParams.get('q') || ''
    if (urlQuery && urlQuery !== query) {
      setQuery(urlQuery)
      setDebouncedQuery(urlQuery)
      setSelectedNoteId(null)
    }
  }, [searchParams])

  // Debounce search (only when user types, not on URL sync)
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query)
      if (query) {
        setSearchParams({ q: query }, { replace: true })
      } else {
        setSearchParams({}, { replace: true })
      }
    }, 250)
    return () => clearTimeout(timer)
  }, [query, setSearchParams])

  // Search results. Backend (HLD §6) accepts an empty q when at least one filter
  // is present, so enable on query>=2 chars OR any active filter.
  const queryReady = debouncedQuery.length >= 2
  const { data, isLoading } = useQuery({
    queryKey: ['search-split', debouncedQuery, searchFilterParams],
    queryFn: async () => {
      const response = await searchApi.search(debouncedQuery, searchFilterParams)
      return response.data
    },
    enabled: queryReady || hasActiveFilters,
  })

  const results = data?.results || []
  const totalCount = data?.count || 0

  // Auto-select first result when results change
  useEffect(() => {
    if (results.length > 0 && !selectedNoteId) {
      setSelectedNoteId(results[0].id)
    }
  }, [results, selectedNoteId])

  // Clear selection when query changes
  useEffect(() => {
    setSelectedNoteId(null)
    setShowPreviewMobile(false)
  }, [debouncedQuery])

  // Fetch full note for preview
  const { data: selectedNote, isLoading: noteLoading } = useQuery({
    queryKey: ['note-preview', selectedNoteId],
    queryFn: async () => {
      const response = await notesApi.get(selectedNoteId)
      return response.data
    },
    enabled: !!selectedNoteId,
  })

  // Keyboard navigation
  const handleKeyDown = useCallback((e) => {
    if (!results.length) return
    const currentIdx = results.findIndex(r => r.id === selectedNoteId)

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      const next = Math.min(currentIdx + 1, results.length - 1)
      setSelectedNoteId(results[next].id)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      const prev = Math.max(currentIdx - 1, 0)
      setSelectedNoteId(results[prev].id)
    }
  }, [results, selectedNoteId])

  // Highlight matching text in content
  const highlightMatches = (text, searchTerm) => {
    if (!text || !searchTerm) return text
    const parts = text.split(new RegExp(`(${searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'))
    return parts.map((part, i) =>
      part.toLowerCase() === searchTerm.toLowerCase()
        ? <mark key={i} className="bg-yellow-200 dark:bg-yellow-700/60 px-0.5 rounded">{part}</mark>
        : part
    )
  }

  // NTS-19: render the backend `snippet` (from ts_headline — text wrapped in
  // <mark>…</mark>). We do NOT use dangerouslySetInnerHTML: split on the mark
  // tags and render every text segment as an escaped React string, so any other
  // markup present in the source note becomes literal text and only our own
  // <mark> element is emitted. This sanitizes to "only <mark>" with zero XSS surface.
  const renderSnippet = (snippet) => {
    if (!snippet) return null
    const segments = snippet.split(/(<mark>[\s\S]*?<\/mark>)/g)
    return segments.map((seg, i) => {
      const m = /^<mark>([\s\S]*?)<\/mark>$/.exec(seg)
      if (m) {
        return (
          <mark key={i} className="bg-yellow-200 dark:bg-yellow-700/60 px-0.5 rounded">{m[1]}</mark>
        )
      }
      return seg ? <span key={i}>{seg}</span> : null
    })
  }

  // Render note content from content_json (TipTap) with highlights + images
  const renderContentWithHighlights = (note, searchTerm) => {
    const contentJson = note?.content_json
    if (!contentJson || !contentJson.content || contentJson.content.length === 0) {
      const text = note?.content_text || ''
      if (!text) return <p className="text-gray-400 italic">Empty note</p>
      return text.split('\n').filter(Boolean).map((para, i) => (
        <p key={i} className="mb-2 text-gray-700 dark:text-gray-300 leading-relaxed">
          {highlightMatches(para, searchTerm)}
        </p>
      ))
    }

    // Render TipTap JSON nodes
    return contentJson.content.map((node, i) => {
      // Image node
      if (node.type === 'image') {
        const { src, alt, title } = node.attrs || {}
        return (
          <div key={i} className="my-3">
            <img
              src={src}
              alt={alt || ''}
              title={title || ''}
              className="max-w-full h-auto rounded-lg border border-gray-200 dark:border-gray-600"
              loading="lazy"
            />
            {alt && <p className="text-xs text-gray-400 mt-1">{alt}</p>}
          </div>
        )
      }

      // Heading nodes
      if (node.type === 'heading') {
        const level = node.attrs?.level || 2
        const text = (node.content || []).map(c => c.text || '').join('')
        const Tag = `h${level}`
        return <Tag key={i} className="font-bold text-gray-900 dark:text-white mb-2 mt-4">{highlightMatches(text, searchTerm)}</Tag>
      }

      // Bullet list
      if (node.type === 'bulletList') {
        return (
          <ul key={i} className="list-disc list-inside mb-2 text-gray-700 dark:text-gray-300">
            {(node.content || []).map((item, j) => {
              const text = (item.content || []).flatMap(p => (p.content || []).map(c => c.text || '')).join('')
              return <li key={j}>{highlightMatches(text, searchTerm)}</li>
            })}
          </ul>
        )
      }

      // Task list
      if (node.type === 'taskList') {
        return (
          <ul key={i} className="mb-2 space-y-1">
            {(node.content || []).map((item, j) => {
              const checked = item.attrs?.checked
              const text = (item.content || []).flatMap(p => (p.content || []).map(c => c.text || '')).join('')
              return (
                <li key={j} className="flex items-center gap-2 text-gray-700 dark:text-gray-300">
                  <input type="checkbox" checked={checked} readOnly className="rounded" />
                  <span className={checked ? 'line-through text-gray-400' : ''}>{highlightMatches(text, searchTerm)}</span>
                </li>
              )
            })}
          </ul>
        )
      }

      // Paragraph (default)
      const textParts = (node.content || []).map((part, j) => {
        const text = part.text || ''
        if (!text) return null

        let element = highlightMatches(text, searchTerm)

        // Apply marks (bold, italic, link)
        const marks = part.marks || []
        for (const mark of marks) {
          if (mark.type === 'bold') element = <strong key={j}>{element}</strong>
          if (mark.type === 'italic') element = <em key={j}>{element}</em>
          if (mark.type === 'link') element = <a key={j} href={mark.attrs?.href} className="text-shizuha-600 underline" target="_blank" rel="noopener">{element}</a>
        }
        return <span key={j}>{element}</span>
      }).filter(Boolean)

      if (textParts.length === 0) return <br key={i} />

      return (
        <p key={i} className="mb-2 text-gray-700 dark:text-gray-300 leading-relaxed">
          {textParts}
        </p>
      )
    })
  }

  // Get snippet with context around the match, stripping attachment placeholders
  const getSnippet = (note) => {
    let text = note.content_text || ''
    // Strip attachment/image placeholders from snippets
    text = text.replace(/\[(?:attachment|Image):\s*[^\]]*\]/g, '').trim()
    if (!debouncedQuery || !text) return text.slice(0, 120)
    const idx = text.toLowerCase().indexOf(debouncedQuery.toLowerCase())
    if (idx === -1) return text.slice(0, 120)
    const start = Math.max(0, idx - 40)
    const end = Math.min(text.length, idx + debouncedQuery.length + 80)
    return (start > 0 ? '...' : '') + text.slice(start, end) + (end < text.length ? '...' : '')
  }

  const handleSelectNote = (noteId) => {
    setSelectedNoteId(noteId)
    setShowPreviewMobile(true)
  }

  return (
    <div className={cn(
      'flex flex-col',
      maximized ? 'fixed inset-0 z-50 bg-gray-50 dark:bg-gray-900 p-0' : 'h-[calc(100vh-8rem)] lg:h-[calc(100vh-5rem)]'
    )}>
      {/* Split pane container */}
      <div className={cn(
        'flex-1 flex overflow-hidden bg-white dark:bg-gray-800',
        maximized ? '' : 'rounded-lg border border-gray-200 dark:border-gray-700'
      )}>

        {/* LEFT: Search bar + results list */}
        <div className={cn(
          'flex flex-col border-r border-gray-200 dark:border-gray-700 transition-all duration-200',
          showPreviewMobile ? 'hidden lg:flex' : 'flex',
          panelCollapsed ? 'lg:w-0 lg:min-w-0 lg:overflow-hidden lg:border-r-0' : 'w-full lg:w-[380px] lg:min-w-[320px] lg:max-w-[420px]'
        )}>
          {/* Search input + panel controls */}
          <div className="p-3 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                <input
                  ref={inputRef}
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Search all notes..."
                  className="w-full pl-10 pr-3 py-2.5 text-sm border border-gray-200 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-700 focus:bg-white dark:focus:bg-gray-700 focus:ring-2 focus:ring-shizuha-500 focus:border-transparent text-gray-900 dark:text-gray-100"
                  autoFocus
                />
              </div>
              {/* Filters toggle */}
              <button
                onClick={() => setShowFilters((v) => !v)}
                className={cn(
                  'relative p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 flex-shrink-0',
                  showFilters || hasActiveFilters
                    ? 'text-shizuha-600 dark:text-shizuha-400'
                    : 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'
                )}
                title="Filters & sort"
                aria-label="Toggle filters"
                aria-pressed={showFilters}
              >
                <SlidersHorizontal className="h-4 w-4" />
                {activeFilterCount > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 min-w-[15px] h-[15px] px-1 rounded-full bg-shizuha-500 text-white text-[9px] font-semibold flex items-center justify-center">
                    {activeFilterCount}
                  </span>
                )}
              </button>
              {/* Collapse results panel */}
              <button
                onClick={() => setPanelCollapsed(true)}
                className="hidden lg:block p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 flex-shrink-0"
                title="Hide search results"
              >
                <PanelLeftClose className="h-4 w-4" />
              </button>
            </div>

            {/* Filter panel (NTS-19) */}
            {showFilters && (
              <div className="mt-3 space-y-2.5 text-xs">
                {/* Sort */}
                <div className="flex items-center gap-2">
                  <label className="w-16 text-gray-500 dark:text-gray-400 flex-shrink-0">Sort</label>
                  <select
                    value={sort}
                    onChange={(e) => setSort(e.target.value)}
                    className="flex-1 px-2 py-1.5 rounded-md border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                  >
                    <option value="relevance">Relevance</option>
                    <option value="updated_desc">Updated (newest)</option>
                    <option value="updated_asc">Updated (oldest)</option>
                    <option value="created_desc">Created (newest)</option>
                    <option value="created_asc">Created (oldest)</option>
                    <option value="title_asc">Title (A–Z)</option>
                    <option value="title_desc">Title (Z–A)</option>
                  </select>
                </div>

                {/* Notebook */}
                <div className="flex items-center gap-2">
                  <label className="w-16 text-gray-500 dark:text-gray-400 flex-shrink-0">Notebook</label>
                  <select
                    value={filters.notebook}
                    onChange={(e) => setFilter('notebook', e.target.value)}
                    className="flex-1 px-2 py-1.5 rounded-md border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                  >
                    <option value="">All notebooks</option>
                    {notebooks.map((nb) => (
                      <option key={nb.id} value={nb.id}>{nb.name}</option>
                    ))}
                  </select>
                </div>

                {/* Tag */}
                <div className="flex items-center gap-2">
                  <label className="w-16 text-gray-500 dark:text-gray-400 flex-shrink-0">Tag</label>
                  <select
                    value={filters.tag}
                    onChange={(e) => setFilter('tag', e.target.value)}
                    className="flex-1 px-2 py-1.5 rounded-md border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                  >
                    <option value="">Any tag</option>
                    {tags.map((t) => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                </div>

                {/* Date range (updated) */}
                <div className="flex items-center gap-2">
                  <label className="w-16 text-gray-500 dark:text-gray-400 flex-shrink-0">Updated</label>
                  <input
                    type="date"
                    value={filters.updated_after}
                    onChange={(e) => setFilter('updated_after', e.target.value)}
                    aria-label="Updated after"
                    className="flex-1 min-w-0 px-2 py-1.5 rounded-md border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                  />
                  <span className="text-gray-400">–</span>
                  <input
                    type="date"
                    value={filters.updated_before}
                    onChange={(e) => setFilter('updated_before', e.target.value)}
                    aria-label="Updated before"
                    className="flex-1 min-w-0 px-2 py-1.5 rounded-md border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                  />
                </div>

                {/* Toggles */}
                <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                  {[
                    { key: 'favorite', label: 'Favorites', Icon: Star },
                    { key: 'pinned', label: 'Pinned', Icon: Pin },
                    { key: 'shared_with_me', label: 'Shared with me', Icon: Users },
                  ].map(({ key, label, Icon }) => (
                    <button
                      key={key}
                      onClick={() => setFilter(key, !filters[key])}
                      aria-pressed={filters[key]}
                      className={cn(
                        'inline-flex items-center gap-1 px-2 py-1 rounded-full border transition-colors',
                        filters[key]
                          ? 'bg-shizuha-50 dark:bg-shizuha-900/30 border-shizuha-300 dark:border-shizuha-700 text-shizuha-700 dark:text-shizuha-300'
                          : 'border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700'
                      )}
                    >
                      <Icon className="h-3 w-3" />
                      {label}
                    </button>
                  ))}
                  {hasActiveFilters && (
                    <button
                      onClick={clearFilters}
                      className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
                    >
                      <X className="h-3 w-3" /> Clear
                    </button>
                  )}
                </div>
              </div>
            )}
            {(debouncedQuery || hasActiveFilters) && (
              <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                {totalCount} result{totalCount !== 1 ? 's' : ''}
                {debouncedQuery ? <> for "{debouncedQuery}"</> : hasActiveFilters ? ' (filtered)' : ''}
              </p>
            )}
          </div>

          {/* Results list */}
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center h-32">
                <LoadingSpinner />
              </div>
            ) : results.length > 0 ? (
              results.map((note) => (
                <button
                  key={note.id}
                  onClick={() => handleSelectNote(note.id)}
                  className={cn(
                    'w-full text-left px-4 py-3 border-b border-gray-100 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors',
                    selectedNoteId === note.id && 'bg-shizuha-50 dark:bg-shizuha-900/20 border-l-2 border-l-shizuha-500'
                  )}
                >
                  <h4 className="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {highlightMatches(note.title || 'Untitled', debouncedQuery)}
                  </h4>
                  <p className="text-xs text-gray-500 dark:text-gray-400 line-clamp-2 mt-1">
                    {note.snippet
                      ? renderSnippet(note.snippet)
                      : highlightMatches(getSnippet(note), debouncedQuery)}
                  </p>
                  <div className="flex items-center gap-2 mt-1.5">
                    {note.notebook_name && (
                      <span className="text-[10px] px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-gray-500 dark:text-gray-400 truncate max-w-[150px]">
                        {note.notebook_name}
                      </span>
                    )}
                    <span className="text-[10px] text-gray-400 dark:text-gray-500">
                      {formatDistanceToNow(new Date(note.updated_at), { addSuffix: true })}
                    </span>
                  </div>
                </button>
              ))
            ) : (debouncedQuery || hasActiveFilters) ? (
              <div className="text-center py-12 text-gray-500 dark:text-gray-400">
                <FileText className="mx-auto h-10 w-10 text-gray-300 dark:text-gray-600" />
                <p className="mt-3 text-sm">No notes found</p>
                <p className="text-xs mt-1">Try a different search term or adjust filters</p>
              </div>
            ) : (
              <div className="text-center py-12 text-gray-500 dark:text-gray-400">
                <SearchIcon className="mx-auto h-10 w-10 text-gray-300 dark:text-gray-600" />
                <p className="mt-3 text-sm">Search your notes</p>
                <p className="text-xs mt-1">Results appear as you type</p>
              </div>
            )}
          </div>
        </div>

        {/* RIGHT: Editable note (like Evernote — edit directly from search) */}
        <NotePane
          noteId={selectedNoteId}
          isLoading={noteLoading}
          showPreviewMobile={showPreviewMobile}
          setShowPreviewMobile={setShowPreviewMobile}
          resultsExist={results.length > 0}
          panelCollapsed={panelCollapsed}
          setPanelCollapsed={setPanelCollapsed}
          maximized={maximized}
          setMaximized={setMaximized}
        />
      </div>
    </div>
  )
}

/**
 * Right pane: editable note with TipTap editor + auto-save.
 * Separated as its own component so the editor remounts on note change.
 */
function NotePane({ noteId, isLoading: parentLoading, showPreviewMobile, setShowPreviewMobile, resultsExist, panelCollapsed, setPanelCollapsed, maximized, setMaximized }) {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState('')
  // null = not yet hydrated from the fetched note (do not mount editor yet)
  const [content, setContent] = useState(null)
  const [hasChanges, setHasChanges] = useState(false)
  const [hydratedNoteId, setHydratedNoteId] = useState(null)
  const saveTimerRef = useRef(null)

  // Fetch note
  const { data: note, isLoading, isFetching } = useQuery({
    queryKey: ['note-preview', noteId],
    queryFn: async () => {
      const response = await notesApi.get(noteId)
      return response.data
    },
    enabled: !!noteId,
  })

  // Reset local editor state as soon as the selected note changes so we never
  // paint the previous note's body (or an empty editor) under the new title.
  useEffect(() => {
    setTitle('')
    setContent(null)
    setHasChanges(false)
    setHydratedNoteId(null)
  }, [noteId])

  // Hydrate title/content only when the fetched note matches the selection.
  useEffect(() => {
    if (!note || !noteId || String(note.id) !== String(noteId)) return
    setTitle(note.title || '')
    // NTS-47: empty content_json + non-empty content_text must still render.
    setContent(resolveNoteEditorContent(note))
    setHasChanges(false)
    setHydratedNoteId(String(noteId))
  }, [note, noteId])

  // Auto-save mutation
  const saveMutation = useMutation({
    mutationFn: ({ noteId, data }) => notesApi.update(noteId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['search-split'] })
      setHasChanges(false)
    },
  })

  // Auto-save with debounce
  const triggerSave = useCallback(() => {
    if (!noteId || !hasChanges || hydratedNoteId !== String(noteId)) return
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(() => {
      saveMutation.mutate({
        noteId,
        data: {
          title,
          content_json: content,
          content_text: '', // backend recalculates
        }
      })
    }, 1500)
  }, [noteId, title, content, hasChanges, saveMutation, hydratedNoteId])

  useEffect(() => {
    triggerSave()
    return () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current) }
  }, [title, content])

  const handleContentChange = useCallback((val) => {
    setContent(val.json || val)
    setHasChanges(true)
  }, [])

  // Ready only when the editor state has been hydrated for THIS noteId.
  // Avoids mounting TipTap with null/{} content (stays blank — NTS-47) and
  // avoids flashing the previous note while the next fetch is in flight.
  const hydrated = !!noteId && hydratedNoteId === String(noteId) && content != null
  const loading = !hydrated && (!!noteId) && (parentLoading || isLoading || isFetching || !note)

  return (
    <div className={cn(
      'flex-1 flex flex-col overflow-hidden',
      !showPreviewMobile ? 'hidden lg:flex' : 'flex'
    )}>
      {noteId && (note || loading) ? (
        <>
          {/* Header */}
          <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 flex items-center gap-3">
            {/* Mobile back button */}
            <button
              onClick={() => setShowPreviewMobile(false)}
              className="lg:hidden p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500"
            >
              <ChevronLeft className="h-5 w-5" />
            </button>

            {/* Show results panel button (when collapsed) */}
            {panelCollapsed && (
              <button
                onClick={() => setPanelCollapsed(false)}
                className="hidden lg:block p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-500"
                title="Show search results"
              >
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            )}

            <div className="flex-1 min-w-0">
              <input
                type="text"
                value={title}
                onChange={(e) => { setTitle(e.target.value); setHasChanges(true) }}
                className="w-full text-lg font-semibold text-gray-900 dark:text-white bg-transparent border-none outline-none focus:ring-0 p-0"
                placeholder={loading ? 'Loading…' : 'Untitled'}
                disabled={loading || !hydrated}
              />
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                {note?.notebook_name && <span>{note.notebook_name} · </span>}
                {note ? `${note.word_count} words` : 'Loading note…'}
                {hasChanges && <span className="text-orange-500 ml-2">· Saving...</span>}
                {!hasChanges && saveMutation.isSuccess && hydrated && <span className="text-green-500 ml-2">· Saved</span>}
              </p>
            </div>

            {/* Maximize / minimize */}
            <button
              onClick={() => setMaximized(!maximized)}
              className="hidden lg:block p-1.5 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              title={maximized ? 'Exit full screen' : 'Full screen'}
            >
              {maximized ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </button>
          </div>

          {/* TipTap editor — remount per note so content always loads (NTS-47) */}
          <div className="flex-1 overflow-y-auto">
            {!hydrated ? (
              <div className="flex items-center justify-center h-32">
                <LoadingSpinner />
              </div>
            ) : (
              <RichTextEditor
                key={noteId}
                content={content}
                onChange={handleContentChange}
                noteId={noteId}
                editable={true}
                className="min-h-full"
              />
            )}
          </div>
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center text-gray-400 dark:text-gray-500">
          <div className="text-center">
            <FileText className="mx-auto h-12 w-12 text-gray-300 dark:text-gray-600" />
            <p className="mt-3 text-sm">
              {resultsExist ? 'Select a note to edit' : 'Search to find notes'}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
