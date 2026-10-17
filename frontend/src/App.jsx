import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './contexts/AuthContext'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Dashboard from './pages/Dashboard'
import Notes from './pages/Notes'
import NoteEditor from './pages/NoteEditor'
import Notebooks from './pages/Notebooks'
import NotebookView from './pages/NotebookView'
import Tags from './pages/Tags'
import Search from './pages/Search'
import Trash from './pages/Trash'
import Login from './pages/Login'
import Settings from './pages/Settings'
import LoadingSpinner from './components/LoadingSpinner'
import { ShizuhaChatWidget } from './components/chat'

function App() {
  const { isLoading, isAuthenticated } = useAuth()

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100 dark:bg-gray-900">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  return (
    <>
      <Routes>
        {/* Standalone login — "Sign in with Shizuha ID" (PLAT-352) */}
        <Route path="/login" element={<Login />} />
        {/* Protected routes */}
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="notes" element={<Notes />} />
          <Route path="notes/new" element={<NoteEditor />} />
          <Route path="notes/:id" element={<NoteEditor />} />
          <Route path="notebooks" element={<Notebooks />} />
          <Route path="notebooks/:id" element={<NotebookView />} />
          <Route path="tags" element={<Tags />} />
          <Route path="search" element={<Search />} />
          <Route path="trash" element={<Trash />} />
          <Route path="settings" element={<Settings />} />
        </Route>

        {/* Redirect unknown routes */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <ShizuhaChatWidget
        sourceService="notes"
        welcomeMessage="Hi there! I can help you organize notes, search your content, and create new notes."
        showToolCalls={true}
      />
    </>
  )
}

export default App
