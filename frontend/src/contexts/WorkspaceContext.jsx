import { createContext, useContext } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { notebooksApi, tagsApi } from '../services/api'
import { useAuth } from './AuthContext'
import { collectionPage } from '../utils/dashboardData'

const WorkspaceContext = createContext(null)

export function WorkspaceProvider({ children }) {
  const { isAuthenticated, organization } = useAuth()
  const queryClient = useQueryClient()

  // Fetch notebooks (flat list) — backend scopes by org via JWT
  const { data: notebookPage, isLoading: notebooksLoading } = useQuery({
    queryKey: ['notebooks', organization?.id],
    queryFn: async () => {
      const response = await notebooksApi.list()
      return collectionPage(response.data)
    },
    enabled: isAuthenticated,
  })

  const notebooks = notebookPage?.results || []
  const notebookCount = notebookPage?.count ?? null

  // Fetch notebooks tree (hierarchical)
  const { data: notebooksTree = [], isLoading: notebooksTreeLoading } = useQuery({
    queryKey: ['notebooksTree'],
    queryFn: async () => {
      const response = await notebooksApi.tree()
      return response.data.results || response.data
    },
    enabled: isAuthenticated,
  })

  // Fetch tags
  const { data: tags = [], isLoading: tagsLoading } = useQuery({
    queryKey: ['tags'],
    queryFn: async () => {
      const response = await tagsApi.list()
      return response.data.results || response.data
    },
    enabled: isAuthenticated,
  })

  // Get default notebook
  const defaultNotebook = notebooks.find(n => n.is_default) || notebooks[0]

  const value = {
    // Backwards compat — pages that reference currentWorkspace
    currentWorkspace: { name: 'Notes', slug: 'notes', id: 'notes' },
    workspaces: [],
    switchWorkspace: () => {},
    workspacesLoading: false,

    // Notebooks
    notebooks,
    notebookCount,
    notebooksTree,
    defaultNotebook,
    notebooksLoading,
    notebooksTreeLoading,

    // Tags
    tags,
    tagsLoading,

    // Loading state
    isLoading: notebooksLoading || tagsLoading,
  }

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext)
  if (!context) {
    throw new Error('useWorkspace must be used within a WorkspaceProvider')
  }
  return context
}

export default WorkspaceContext
