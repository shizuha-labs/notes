import axios from 'axios'

// API base URL - uses VITE_API_BASE for deployment flexibility
// When accessed via /notes/ prefix, this should be /notes/api
// When accessed directly (standalone), this should be /api
const API_BASE = import.meta.env.VITE_API_BASE || '/api'

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor - add auth and organization headers
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('shizuha_access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }

    const orgId = localStorage.getItem('shizuha_organization_id')
    if (orgId) {
      config.headers['X-Organization-ID'] = orgId
    }

    console.debug(`[API] ${config.method?.toUpperCase()} ${config.url}`)
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('[API Error]', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

// Notes API
export const notesApi = {
  list: (params = {}) => api.get('/notes/', { params }),
  get: (id) => api.get(`/notes/${id}/`),
  create: (data) => api.post('/notes/', data),
  update: (id, data) => api.patch(`/notes/${id}/`, data),
  delete: (id) => api.delete(`/notes/${id}/`),

  // Actions
  trash: (id) => api.post(`/notes/${id}/trash/`),
  restore: (id) => api.post(`/notes/${id}/restore/`),
  pin: (id) => api.post(`/notes/${id}/pin/`),
  favorite: (id) => api.post(`/notes/${id}/favorite/`),
  duplicate: (id) => api.post(`/notes/${id}/duplicate/`),

  // Versions
  getVersions: (id) => api.get(`/notes/${id}/versions/`),
  restoreVersion: (id, version) => api.post(`/notes/${id}/restore-version/${version}/`),

  // Sharing
  getShares: (id) => api.get(`/notes/${id}/shares/`),
  createShare: (id, data) => api.post(`/notes/${id}/shares/`, data),

  // Comments
  getComments: (id) => api.get(`/notes/${id}/comments/`),
  createComment: (id, data) => api.post(`/notes/${id}/comments/`, data),

  // Bulk operations
  bulkDelete: (ids) => api.post('/notes/bulk-delete/', { note_ids: ids }),
  bulkMove: (ids, notebookId) => api.post('/notes/bulk-move/', { note_ids: ids, notebook_id: notebookId }),
  bulkTag: (ids, tagIds) => api.post('/notes/bulk-tag/', { note_ids: ids, tag_ids: tagIds }),
}

// Notebooks API
export const notebooksApi = {
  list: (params = {}) => api.get('/notebooks/', { params }),
  get: (id) => api.get(`/notebooks/${id}/`),
  create: (data) => api.post('/notebooks/', data),
  update: (id, data) => api.patch(`/notebooks/${id}/`, data),
  delete: (id) => api.delete(`/notebooks/${id}/`),
  getNotes: (id, params = {}) => api.get(`/notebooks/${id}/notes/`, { params }),
  archive: (id) => api.post(`/notebooks/${id}/archive/`),
  unarchive: (id) => api.post(`/notebooks/${id}/unarchive/`),
  // Hierarchy/Stack endpoints
  tree: (params = {}) => api.get('/notebooks/tree/', { params }),
  move: (id, parentId) => api.post(`/notebooks/${id}/move/`, { parent: parentId }),
}

// Tags API
export const tagsApi = {
  list: (params = {}) => api.get('/tags/', { params }),
  get: (id) => api.get(`/tags/${id}/`),
  create: (data) => api.post('/tags/', data),
  update: (id, data) => api.patch(`/tags/${id}/`, data),
  delete: (id) => api.delete(`/tags/${id}/`),
  getNotes: (id, params = {}) => api.get(`/tags/${id}/notes/`, { params }),
}

// Workspaces API removed — org scoping handled by X-Organization-ID header

// Attachments API
export const attachmentsApi = {
  list: (params = {}) => api.get('/attachments/', { params }),
  upload: (noteId, file, options = {}) => {
    const formData = new FormData()
    formData.append('note', noteId)
    formData.append('file', file)
    if (options.caption) formData.append('caption', options.caption)
    if (options.alt_text) formData.append('alt_text', options.alt_text)
    return api.post('/attachments/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  delete: (id) => api.delete(`/attachments/${id}/`),
}

// Search API
export const searchApi = {
  search: (query, params = {}) => api.get('/search/', { params: { q: query, ...params } }),
}

// Trash API
export const trashApi = {
  list: () => api.get('/trash/'),
  empty: () => api.delete('/trash/'),
  restore: (id) => api.post(`/notes/${id}/restore/`),
}

// Shared API
export const sharedApi = {
  list: () => api.get('/shared/'),
  getPublic: (token) => api.get(`/public/${token}/`),
}

// Auth API
export const authApi = {
  login: (data) => api.post('/auth/login/', data),
  logout: (data) => api.post('/auth/logout/', data),
  register: (data) => api.post('/auth/register/', data),
  refresh: (data) => api.post('/auth/token/refresh/', data),
  getUser: () => api.get('/auth/user/'),
  updateUser: (data) => api.patch('/auth/user/', data),
}

export default api
