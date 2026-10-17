import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import {
  Home, FileText, FolderOpen, Tag, Search, Trash2,
  Settings, LogOut, Plus, Moon, Sun, Menu, X, ChevronDown, Building2
} from 'lucide-react'
import { useState, useRef, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useWorkspace } from '../contexts/WorkspaceContext'
import { useTheme } from '../hooks/useTheme'
import { cn } from '../utils/cn'
import AppSwitcher from './AppSwitcher'
import { useEnabledServices } from '@shizuha/ui'
import NotebookTree from './NotebookTree'
import GlobalSearch from './GlobalSearch'

const navigation = [
  { name: 'Dashboard', href: '/', icon: Home },
  { name: 'All Notes', href: '/notes', icon: FileText },
  { name: 'Notebooks', href: '/notebooks', icon: FolderOpen },
  { name: 'Tags', href: '/tags', icon: Tag },
  { name: 'Search', href: '/search', icon: Search },
  { name: 'Trash', href: '/trash', icon: Trash2 },
]

export default function Layout() {
  const { user, logout, organization, organizations, switchOrganization } = useAuth()
  const { notebooksTree } = useWorkspace()
  const { theme, toggleTheme } = useTheme()
  const navigate = useNavigate()
  const enabledServices = useEnabledServices()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const handleLogout = async () => {
    await logout()
    window.location.href = import.meta.env.VITE_LOGIN_URL || '/login'
  }

  const handleNewNote = () => {
    navigate('/notes/new')
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 transform transition-transform lg:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex flex-col h-full">
          {/* Logo and workspace selector */}
          <div className="p-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <AppSwitcher currentAppId="notes" enabledServices={enabledServices} />
                <h1 className="text-xl font-bold text-shizuha-600 dark:text-shizuha-400">
                  Shizuha Notes
                </h1>
              </div>
              <button
                onClick={() => setSidebarOpen(false)}
                className="lg:hidden p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-300"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Organization switcher */}
            <OrganizationSwitcher
              organization={organization}
              organizations={organizations}
              switchOrganization={switchOrganization}
            />

            {/* Workspace selector removed — org switcher above handles scoping */}
          </div>

          {/* New note button */}
          <div className="p-4">
            <button
              onClick={handleNewNote}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-shizuha-600 hover:bg-shizuha-700 text-white rounded-lg font-medium transition-colors"
            >
              <Plus className="h-5 w-5" />
              New Note
            </button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 px-3 overflow-y-auto">
            <ul className="space-y-1">
              {navigation.map((item) => (
                <li key={item.name}>
                  <NavLink
                    to={item.href}
                    className={({ isActive }) =>
                      cn(
                        'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-shizuha-100 dark:bg-shizuha-900/30 text-shizuha-700 dark:text-shizuha-300'
                          : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                      )
                    }
                  >
                    <item.icon className="h-5 w-5" />
                    {item.name}
                  </NavLink>
                </li>
              ))}
            </ul>

            {/* Notebooks section - hierarchical tree */}
            {notebooksTree.length > 0 && (
              <div className="mt-6">
                <NotebookTree
                  notebooks={notebooksTree}
                  onCreateNotebook={() => navigate('/notebooks?create=true')}
                  onEditNotebook={(notebook) => navigate(`/notebooks?edit=${notebook.id}`)}
                  compact
                />
              </div>
            )}
          </nav>

          {/* Bottom section */}
          <div className="p-3 border-t border-gray-200 dark:border-gray-700 space-y-1">
            <NavLink
              to="/settings"
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors text-gray-700 dark:text-gray-300',
                  isActive
                    ? 'bg-gray-100 dark:bg-gray-700'
                    : 'hover:bg-gray-100 dark:hover:bg-gray-700'
                )
              }
            >
              <Settings className="h-5 w-5" />
              Settings
            </NavLink>

            <button
              onClick={toggleTheme}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors text-gray-700 dark:text-gray-300"
            >
              {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
              {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
            </button>

            <button
              onClick={handleLogout}
              className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
            >
              <LogOut className="h-5 w-5" />
              Sign Out
            </button>

            {/* User info */}
            {user && (
              <div className="px-3 py-2 text-xs text-gray-500 dark:text-gray-400">
                {user.email}
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="lg:pl-64">
        {/* Top bar - mobile */}
        <header className="sticky top-0 z-30 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 lg:hidden">
          <div className="flex items-center justify-between px-4 h-14">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setSidebarOpen(true)}
                className="p-2 -ml-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-300"
              >
                <Menu className="h-5 w-5" />
              </button>
              <AppSwitcher currentAppId="notes" enabledServices={enabledServices} />
            </div>
            <h1 className="text-lg font-semibold text-shizuha-600 dark:text-shizuha-400">
              Shizuha Notes
            </h1>
            <button
              onClick={handleNewNote}
              className="p-2 -mr-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-300"
            >
              <Plus className="h-5 w-5" />
            </button>
          </div>
          {/* Mobile search */}
          <div className="px-3 pb-3">
            <GlobalSearch />
          </div>
        </header>

        {/* Top bar - desktop (search only) */}
        <header className="sticky top-0 z-30 bg-white/80 dark:bg-gray-800/80 backdrop-blur-sm border-b border-gray-200 dark:border-gray-700 hidden lg:block">
          <div className="px-6 py-3">
            <GlobalSearch />
          </div>
        </header>

        {/* Page content */}
        <main className="p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function OrganizationSwitcher({ organization, organizations, switchOrganization }) {
  const [isOpen, setIsOpen] = useState(false)
  const menuRef = useRef(null)

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div className="mt-3 relative" ref={menuRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3 py-2 text-sm bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200"
      >
        <span className="flex items-center gap-2 truncate">
          <Building2 className="h-4 w-4 flex-shrink-0" />
          <span className="truncate">{organization?.name || 'All Organizations'}</span>
        </span>
        <ChevronDown className="h-4 w-4 flex-shrink-0" />
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-20">
          <div className="px-3 py-2 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">
            Switch Organization
          </div>
          {/* All Organizations option */}
          <button
            onClick={() => {
              switchOrganization(null)
              setIsOpen(false)
            }}
            className={cn(
              'w-full flex items-center px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-700',
              organization === null
                ? 'bg-shizuha-50 dark:bg-shizuha-900/20 text-shizuha-700 dark:text-shizuha-300'
                : 'text-gray-700 dark:text-gray-200'
            )}
          >
            <Building2 className="h-4 w-4 mr-2 flex-shrink-0" />
            <span className="truncate">All Organizations</span>
            {organization === null && (
              <span className="ml-auto text-shizuha-600">✓</span>
            )}
          </button>
          {/* Individual orgs */}
          {organizations.map((org) => (
            <button
              key={org.id}
              onClick={() => {
                switchOrganization(org)
                setIsOpen(false)
              }}
              className={cn(
                'w-full flex items-center px-3 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-700 last:rounded-b-lg',
                organization?.id === org.id
                  ? 'bg-shizuha-50 dark:bg-shizuha-900/20 text-shizuha-700 dark:text-shizuha-300'
                  : 'text-gray-700 dark:text-gray-200'
              )}
            >
              <Building2 className="h-4 w-4 mr-2 flex-shrink-0" />
              <span className="truncate">{org.name}</span>
              {organization?.id === org.id && (
                <span className="ml-auto text-shizuha-600">✓</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
