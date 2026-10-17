import { loginRedirect } from '../utils/loginUrl'
import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import api from '../services/api'

const AuthContext = createContext(null)

// Token storage keys
const ACCESS_TOKEN_KEY = 'shizuha_access_token'
const REFRESH_TOKEN_KEY = 'shizuha_refresh_token'
const USER_KEY = 'shizuha_user'
const ORG_ID_KEY = 'shizuha_organization_id'

// Fetch user's organizations from shizuha-admin
async function fetchUserOrganizations(token) {
  try {
    const response = await axios.get('/admin/api/organizations/', {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
      }
    })
    return response.data.results || response.data || []
  } catch (error) {
    console.error('Failed to fetch organizations:', error)
    return []
  }
}

// Get login URL - redirect to unified Shizuha ID login
const getLoginUrl = () => {
  // Standalone (PLAT-352): notes' own /login offers "Sign in with Shizuha ID"
  // (OIDC). VITE_LOGIN_URL overrides for the platform-integrated deployment.
  return loginRedirect(import.meta.env.VITE_LOGIN_URL,
    import.meta.env.VITE_BASE_PATH, window.location.pathname)
}

// "Sign in with Shizuha ID" (PLAT-352): the backend BFF callback delivers
// tokens in the URL fragment. Capture + strip them synchronously on load.
function captureOAuthFragment() {
  if (typeof window === 'undefined' || !window.location.hash) return
  const params = new URLSearchParams(window.location.hash.slice(1))
  const access = params.get('access')
  if (!access) return
  localStorage.setItem(ACCESS_TOKEN_KEY, access)
  const refresh = params.get('refresh')
  if (refresh) localStorage.setItem('shizuha_refresh_token', refresh)
  window.history.replaceState(null, '', window.location.pathname + window.location.search)
}
captureOAuthFragment()

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [organization, setOrganization] = useState(null)
  const [organizations, setOrganizations] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [isAuthenticated, setIsAuthenticated] = useState(false)

  // Initialize auth state from localStorage
  useEffect(() => {
    const initAuth = async () => {
      const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY)
      const storedUser = localStorage.getItem(USER_KEY)
      const storedOrgId = localStorage.getItem(ORG_ID_KEY)

      if (accessToken && storedUser) {
        try {
          // Set the token in axios headers
          api.defaults.headers.common['Authorization'] = `Bearer ${accessToken}`

          // Verify token is still valid by fetching user
          const response = await api.get('/auth/user/')
          setUser(response.data)
          setIsAuthenticated(true)

          // Fetch user's organizations
          const orgs = await fetchUserOrganizations(accessToken)
          setOrganizations(orgs)

          // Set current organization
          if (storedOrgId === '__all__' || !storedOrgId) {
            // "All Organizations" mode (default)
            setOrganization(null)
          } else if (storedOrgId && orgs.some(o => String(o.id) === storedOrgId)) {
            const org = orgs.find(o => String(o.id) === storedOrgId)
            setOrganization(org)
          } else {
            // Saved org not found, fall back to All Organizations
            setOrganization(null)
            localStorage.setItem(ORG_ID_KEY, '__all__')
          }
        } catch (error) {
          console.error('Token validation failed:', error)
          // Try to refresh the token
          const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
          if (refreshToken) {
            try {
              await refreshAccessToken(refreshToken)
            } catch {
              // Clear invalid auth state
              clearAuthState()
            }
          } else {
            clearAuthState()
          }
        }
      }
      setIsLoading(false)
    }

    initAuth()
  }, [])

  // Setup axios interceptor for token refresh
  useEffect(() => {
    const interceptor = api.interceptors.response.use(
      (response) => response,
      async (error) => {
        const originalRequest = error.config

        // If 401 and not already retrying, try to refresh token
        if (error.response?.status === 401 && !originalRequest._retry) {
          originalRequest._retry = true

          const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
          if (refreshToken) {
            try {
              const newAccessToken = await refreshAccessToken(refreshToken)
              originalRequest.headers['Authorization'] = `Bearer ${newAccessToken}`
              return api(originalRequest)
            } catch {
              clearAuthState()
              window.location.href = getLoginUrl()
            }
          } else {
            clearAuthState()
            window.location.href = getLoginUrl()
          }
        }
        return Promise.reject(error)
      }
    )

    return () => api.interceptors.response.eject(interceptor)
  }, [])

  const refreshAccessToken = async (refreshToken) => {
    const response = await api.post('/auth/token/refresh/', { refresh: refreshToken })
    const newAccessToken = response.data.access
    localStorage.setItem(ACCESS_TOKEN_KEY, newAccessToken)
    api.defaults.headers.common['Authorization'] = `Bearer ${newAccessToken}`

    // If new refresh token provided, save it
    if (response.data.refresh) {
      localStorage.setItem(REFRESH_TOKEN_KEY, response.data.refresh)
    }

    return newAccessToken
  }

  const clearAuthState = () => {
    localStorage.removeItem(ACCESS_TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    localStorage.removeItem(ORG_ID_KEY)
    delete api.defaults.headers.common['Authorization']
    setUser(null)
    setOrganization(null)
    setOrganizations([])
    setIsAuthenticated(false)
  }

  const switchOrganization = (org) => {
    setOrganization(org)
    localStorage.setItem(ORG_ID_KEY, org ? String(org.id) : '__all__')
  }

  const login = useCallback(async (username, password) => {
    const response = await api.post('/auth/login/', { username, password })
    const { user: userData, tokens } = response.data

    // Save tokens and user
    localStorage.setItem(ACCESS_TOKEN_KEY, tokens.access)
    localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh)
    localStorage.setItem(USER_KEY, JSON.stringify(userData))

    // Set auth header
    api.defaults.headers.common['Authorization'] = `Bearer ${tokens.access}`

    setUser(userData)
    setIsAuthenticated(true)

    // Fetch organizations after login
    const orgs = await fetchUserOrganizations(tokens.access)
    setOrganizations(orgs)

    if (orgs.length > 0) {
      const defaultOrg = orgs[0]
      setOrganization(defaultOrg)
      localStorage.setItem(ORG_ID_KEY, String(defaultOrg.id))
    }

    return userData
  }, [])

  const logout = useCallback(async () => {
    try {
      const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
      if (refreshToken) {
        await api.post('/auth/logout/', { refresh: refreshToken })
      }
    } catch (error) {
      console.error('Logout error:', error)
    } finally {
      clearAuthState()
      window.location.href = '/id/login?continue=/notes/'
    }
  }, [])

  const value = {
    user,
    isLoading,
    isAuthenticated,
    organization,
    organizations,
    switchOrganization,
    login,
    logout,
    getLoginUrl,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

export default AuthContext
