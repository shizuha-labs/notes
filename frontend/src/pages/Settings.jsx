import { useAuth } from '../contexts/AuthContext'
import { useWorkspace } from '../contexts/WorkspaceContext'
import { User, Folder, Tag, Moon, Sun } from 'lucide-react'
import { useTheme } from '../hooks/useTheme'

export default function Settings() {
  const { user } = useAuth()
  const { notebooks, tags } = useWorkspace()
  const { theme, toggleTheme } = useTheme()

  return (
    <div className="max-w-2xl space-y-8">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Settings</h1>

      {/* Account section */}
      <section className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <User className="h-5 w-5" />
            Account
          </h2>
        </div>
        <div className="p-4 space-y-4">
          <div>
            <label className="text-sm text-gray-500 dark:text-gray-400">Email</label>
            <p className="text-gray-900 dark:text-white">{user?.email || 'Not available'}</p>
          </div>
          <div>
            <label className="text-sm text-gray-500 dark:text-gray-400">Username</label>
            <p className="text-gray-900 dark:text-white">{user?.username || 'Not available'}</p>
          </div>
          <a
            href="/id/settings"
            className="inline-block px-4 py-2 text-sm bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
          >
            Manage Account
          </a>
        </div>
      </section>

      {/* Appearance section */}
      <section className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            {theme === 'dark' ? <Moon className="h-5 w-5" /> : <Sun className="h-5 w-5" />}
            Appearance
          </h2>
        </div>
        <div className="p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="font-medium text-gray-900 dark:text-white">Theme</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Switch between light and dark mode
              </p>
            </div>
            <button
              onClick={toggleTheme}
              className="px-4 py-2 bg-gray-100 dark:bg-gray-700 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
            >
              {theme === 'dark' ? 'Light Mode' : 'Dark Mode'}
            </button>
          </div>
        </div>
      </section>

      {/* Workspace section */}
      <section className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Folder className="h-5 w-5" />
            Workspace
          </h2>
        </div>
        <div className="p-4 space-y-4">
          <div>
            <label className="text-sm text-gray-500 dark:text-gray-400">Current Workspace</label>
            <p className="text-gray-900 dark:text-white">Notes</p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-gray-50 dark:bg-gray-900/50 rounded-lg">
              <p className="text-2xl font-bold text-gray-900 dark:text-white">{notebooks.length}</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">Notebooks</p>
            </div>
            <div className="p-4 bg-gray-50 dark:bg-gray-900/50 rounded-lg">
              <p className="text-2xl font-bold text-gray-900 dark:text-white">{tags.length}</p>
              <p className="text-sm text-gray-500 dark:text-gray-400">Tags</p>
            </div>
          </div>
        </div>
      </section>

      {/* About section */}
      <section className="text-center text-sm text-gray-500 dark:text-gray-400">
        <p>Shizuha Notes v1.0.0</p>
        <p className="mt-1">Part of the Shizuha Platform</p>
      </section>
    </div>
  )
}
