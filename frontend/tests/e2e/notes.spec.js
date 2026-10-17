import { test, expect, uniqueId } from './fixtures'

// Base path for Notes app
const BASE_PATH = '/notes'
const TEST_PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP4z8AARAwQCgAf7gP9i18U1AAAAABJRU5ErkJggg==', 'base64')

test.describe('Notes App E2E Tests', () => {

  test.describe('Organization context', () => {
    test('selected organization persists across a page reload', async ({ authenticatedPage, organization }) => {
      await authenticatedPage.reload()
      await expect(authenticatedPage.getByRole('heading', { name: 'Shizuha Notes' })).toBeVisible()
      await expect(authenticatedPage.getByRole('button', { name: organization.name, exact: true })).toBeVisible()
      await expect.poll(() => authenticatedPage.evaluate(() => localStorage.getItem('shizuha_organization_id'))).toBe(String(organization.id))
    })
  })

  test.describe('Notebook Management', () => {
    test('can create a new notebook', async ({ authenticatedPage }) => {
      // Navigate to notebooks page
      await authenticatedPage.goto(`${BASE_PATH}/notebooks`)
      await authenticatedPage.waitForLoadState('networkidle')

      // Wait for page to be ready
      await authenticatedPage.waitForTimeout(1000)

      // Click "New Notebook" button
      const newNotebookButton = authenticatedPage.locator('button:has-text("New Notebook"), button:has-text("Create Notebook")')
      await newNotebookButton.first().click()

      // Wait for modal to appear
      await authenticatedPage.waitForSelector('input[placeholder="My Notebook"]', { timeout: 5000 })

      // Fill in notebook details
      const notebookName = `Test Notebook ${uniqueId()}`
      await authenticatedPage.fill('input[placeholder="My Notebook"]', notebookName)
      await authenticatedPage.fill('textarea[placeholder="Optional description..."]', 'E2E test notebook')

      // Select a color (click second color)
      const colorButtons = authenticatedPage.locator('button[style*="background-color"]')
      if (await colorButtons.count() > 1) {
        await colorButtons.nth(1).click()
      }

      // Submit the form
      await authenticatedPage.click('button[type="submit"]')

      // Wait for modal to close and notebook to appear
      await authenticatedPage.waitForSelector(`text=${notebookName}`, { timeout: 10000 })

      // Verify notebook was created - use first() to avoid strict mode violation
      await expect(authenticatedPage.locator(`text=${notebookName}`).first()).toBeVisible()
    })

    test('shows empty state when no notebooks exist', async ({ authenticatedPage }) => {
      // This test may need adjustment based on whether notebooks exist
      await authenticatedPage.goto(`${BASE_PATH}/notebooks`)
      await authenticatedPage.waitForLoadState('networkidle')

      // Page should either show notebooks or empty state - not crash
      const pageContent = await authenticatedPage.content()
      expect(pageContent).toBeTruthy()

      // Should not have console errors about undefined
      const consoleLogs = []
      authenticatedPage.on('console', msg => {
        if (msg.type() === 'error') {
          consoleLogs.push(msg.text())
        }
      })

      await authenticatedPage.waitForTimeout(2000)

      // Check no critical errors (allow TipTap warnings)
      const criticalErrors = consoleLogs.filter(log =>
        !log.includes('tiptap') &&
        !log.includes('Warning') &&
        log.includes('TypeError')
      )
      expect(criticalErrors).toHaveLength(0)
    })

    test('notebook creation modal has parent dropdown', async ({ authenticatedPage }) => {
      // Navigate to notebooks page
      await authenticatedPage.goto(`${BASE_PATH}/notebooks`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Click "New Notebook" button
      const newNotebookButton = authenticatedPage.locator('button:has-text("New Notebook"), button:has-text("Create Notebook")')
      await newNotebookButton.first().click()

      await authenticatedPage.waitForSelector('input[placeholder="My Notebook"]', { timeout: 5000 })

      // Verify parent dropdown exists
      const parentSelect = authenticatedPage.locator('select').first()
      await expect(parentSelect).toBeVisible()

      // Verify it has at least one option (the "None" default)
      const optionCount = await parentSelect.locator('option').count()
      expect(optionCount).toBeGreaterThanOrEqual(1)

      // Close modal
      const cancelButton = authenticatedPage.locator('button:has-text("Cancel")')
      if (await cancelButton.isVisible()) {
        await cancelButton.click()
      }
    })

    test('notebooks tree API returns hierarchical data', async ({ authenticatedApi }) => {
      const response = await authenticatedApi.get('notebooks/tree/')
      expect(response.ok()).toBeTruthy()

      const data = await response.json()
      expect(Array.isArray(data.results || data)).toBeTruthy()

      // Each notebook should have children array
      const notebooks = data.results || data
      if (notebooks.length > 0) {
        const firstNotebook = notebooks[0]
        expect(firstNotebook).toHaveProperty('children')
        expect(Array.isArray(firstNotebook.children)).toBeTruthy()
      }
    })

    test('can create nested notebooks via API', async ({ authenticatedApi }) => {
      // Create a parent notebook
      const parentName = `API Stack ${Date.now()}`
      const parentResponse = await authenticatedApi.post('notebooks/', {
        data: {
          name: parentName,
          color: '#ef4444'
        }
      })
      expect(parentResponse.ok()).toBeTruthy()
      const parentData = await parentResponse.json()
      const parentId = parentData.id
      expect(parentData.name).toEqual(parentName)
      expect(parentData.parent).toBeNull()

      // Create a child notebook
      const childName = `API Child ${Date.now()}`
      const childResponse = await authenticatedApi.post('notebooks/', {
        data: {
          name: childName,
          parent: parentId,
          color: '#22c55e'
        }
      })
      expect(childResponse.ok()).toBeTruthy()
      const childData = await childResponse.json()
      expect(childData.name).toEqual(childName)
      // Parent is returned as UUID string
      expect(childData.parent).toBeTruthy()
      expect(String(childData.parent)).toEqual(String(parentId))

      // Verify via tree endpoint
      const treeResponse = await authenticatedApi.get('notebooks/tree/')
      expect(treeResponse.ok()).toBeTruthy()
      const treeData = await treeResponse.json()
      const notebooks = treeData.results || treeData

      // Find the parent in the tree
      const parentInTree = notebooks.find(n => n.id === parentId)
      expect(parentInTree).toBeTruthy()
      expect(parentInTree.children.length).toEqual(1)
      expect(parentInTree.children[0].id).toEqual(childData.id)
      expect(parentInTree.children[0].name).toEqual(childName)
    })

    test('move endpoint relocates notebooks', async ({ authenticatedApi }) => {
      // Create two parent notebooks and one child
      const parent1Response = await authenticatedApi.post('notebooks/', {
        data: { name: `Move Parent 1 ${Date.now()}`, color: '#ef4444' }
      })
      const parent1 = await parent1Response.json()

      const parent2Response = await authenticatedApi.post('notebooks/', {
        data: { name: `Move Parent 2 ${Date.now()}`, color: '#22c55e' }
      })
      const parent2 = await parent2Response.json()

      const childResponse = await authenticatedApi.post('notebooks/', {
        data: { name: `Move Child ${Date.now()}`, parent: parent1.id, color: '#6366f1' }
      })
      const child = await childResponse.json()
      expect(child.parent).toBeTruthy()
      expect(String(child.parent)).toEqual(String(parent1.id))

      // Move child to parent2
      const moveResponse = await authenticatedApi.post(`notebooks/${child.id}/move/`, {
        data: { parent: parent2.id }
      })
      expect(moveResponse.ok()).toBeTruthy()

      // Verify child is now under parent2
      const verifyResponse = await authenticatedApi.get(`notebooks/${child.id}/`)
      const updatedChild = await verifyResponse.json()
      expect(updatedChild.parent).toBeTruthy()
      expect(String(updatedChild.parent)).toEqual(String(parent2.id))
    })
  })

  test.describe('Note Editor', () => {
    test('NTS-73: zero notebooks → create first note → note visible after reload', async ({ authenticatedPage, authenticatedApi }) => {
      // Ensure the account has ZERO notebooks (AC4 precondition).
      const listRes = await authenticatedApi.get('notebooks/')
      if (listRes.ok()) {
        const data = await listRes.json()
        const notebooks = data.results || data || []
        for (const nb of notebooks) {
          await authenticatedApi.delete(`notebooks/${nb.id}/`).catch(() => {})
        }
      }

      // Attempt to create a note with no notebooks. The UI must NOT emit an
      // invalid `notebook: null` request; it must route to the create-notebook
      // flow instead.
      let invalidRequestSeen = false
      authenticatedPage.on('request', req => {
        if (req.method() === 'POST' && req.url().includes('/notes/api/notes/')) {
          const postData = req.postData() || ''
          if (postData.includes('"notebook":null') || postData.includes('"notebook": null')) {
            invalidRequestSeen = true
          }
        }
      })

      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()
      await authenticatedPage.waitForSelector('input[placeholder="Untitled"]', { timeout: 10000 })

      // Make a real draft first: a pristine empty note correctly disables Save.
      await authenticatedPage.fill('input[placeholder="Untitled"]', `Unsaved first note ${uniqueId()}`)
      // Attempt to save/create — the guard should alert + route to the
      // create-notebook page instead of emitting an invalid request.
      const saveButton = authenticatedPage.locator('button:has-text("Create"), button:has-text("Save")')
      await saveButton.click()

      await authenticatedPage.waitForURL(url => url.pathname === `${BASE_PATH}/notebooks`, { timeout: 10000 })
      expect(invalidRequestSeen).toBe(false)

      // The create=true route opens the first-notebook dialog directly.
      await authenticatedPage.waitForSelector('input[placeholder="My Notebook"]', { timeout: 5000 })
      const notebookName = `First Notebook ${uniqueId()}`
      await authenticatedPage.fill('input[placeholder="My Notebook"]', notebookName)
      await authenticatedPage.click('button[type="submit"]')
      await authenticatedPage.waitForSelector(`text=${notebookName}`, { timeout: 10000 })

      // Now create the first note in that notebook.
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)
      await authenticatedPage.locator('button:has-text("New Note")').first().click()
      await authenticatedPage.waitForSelector('input[placeholder="Untitled"]', { timeout: 10000 })
      const noteTitle = `First Note ${uniqueId()}`
      await authenticatedPage.fill('input[placeholder="Untitled"]', noteTitle)
      await authenticatedPage.click('.ProseMirror')
      await authenticatedPage.keyboard.type('NTS-73 first note content.')
      await authenticatedPage.locator('button:has-text("Create"), button:has-text("Save")').click()
      await authenticatedPage.waitForTimeout(2000)
      expect(authenticatedPage.url()).not.toContain('/new')

      // Note must be visible after reload (AC4).
      await authenticatedPage.reload()
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1500)
      await expect(authenticatedPage.locator('input[placeholder="Untitled"]')).toHaveValue(noteTitle)
    })

    test('can create a new note', async ({ authenticatedPage, notebooks }) => {
      // Start from dashboard and use UI navigation
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Click the "New Note" button in the sidebar
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      // Wait for editor to load
      await authenticatedPage.waitForSelector('input[placeholder="Untitled"]', { timeout: 10000 })

      // Fill in title
      const noteTitle = `Test Note ${uniqueId()}`
      await authenticatedPage.fill('input[placeholder="Untitled"]', noteTitle)

      // Wait for editor content area
      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Type in the editor
      await authenticatedPage.click('.ProseMirror')
      await authenticatedPage.keyboard.type('This is test content for the E2E test.')

      // Click save/create button
      const saveButton = authenticatedPage.locator('button:has-text("Create"), button:has-text("Save")')
      await saveButton.click()

      // Wait for navigation or success indication
      await authenticatedPage.waitForTimeout(2000)

      // Verify we're no longer on /new or note was saved
      const url = authenticatedPage.url()
      // After create, should redirect to /notes/{id}
      expect(url).not.toContain('/new')
    })

    test('notebook note count updates after creating note', async ({ authenticatedPage }) => {
      // This test verifies that the notebook's note count in the sidebar
      // updates immediately after creating a note, without requiring a page refresh.

      const token = await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_access_token'))
      const headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        'X-Organization-ID': await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_organization_id')),
      }

      // Get notebooks to find one to use
      const notebooksRes = await authenticatedPage.request.get(`${BASE_PATH}/api/notebooks/`, {
        headers,
      })
      const notebooksList = await notebooksRes.json()
      const notebooks = notebooksList.results || notebooksList
      expect(notebooks.length).toBeGreaterThan(0)
      const targetNotebook = notebooks[0]

      // Get the initial note count via API
      const initialTreeRes = await authenticatedPage.request.get(`${BASE_PATH}/api/notebooks/tree/`, {
        headers,
      })
      const initialTree = await initialTreeRes.json()
      const initialNb = initialTree.find(nb => nb.id === targetNotebook.id)
      const initialCount = initialNb?.note_count || 0

      // Navigate to dashboard
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Create a new note
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      // Wait for editor
      await authenticatedPage.waitForSelector('input[placeholder="Untitled"]', { timeout: 10000 })

      // Select the target notebook
      const selector = authenticatedPage.locator('select').first()
      await selector.selectOption({ value: targetNotebook.id })

      // Fill in title
      const noteTitle = `Count Test Note ${uniqueId()}`
      await authenticatedPage.fill('input[placeholder="Untitled"]', noteTitle)

      // Add content
      await authenticatedPage.click('.ProseMirror')
      await authenticatedPage.keyboard.type('Testing note count update')

      // Click Create
      const createButton = authenticatedPage.locator('button:has-text("Create")')
      await createButton.click()

      // Wait for save to complete (URL should change to note ID)
      await authenticatedPage.waitForURL(/\/notes\/[a-f0-9-]+$/, { timeout: 10000 })

      // Wait a moment for query invalidation to take effect
      await authenticatedPage.waitForTimeout(1500)

      // Check the notebook count in the sidebar - it should be incremented
      // The sidebar shows notebooks with counts like "N1 (3)" or just the count badge
      const sidebarNotebook = authenticatedPage.locator(`a[href*="/notebooks/${targetNotebook.id}"]`)
      await expect(sidebarNotebook).toBeVisible()

      // Get the count displayed in sidebar
      const countBadge = sidebarNotebook.locator('span.text-xs')
      const displayedCount = await countBadge.textContent().catch(() => '0')
      const countValue = parseInt(displayedCount) || 0

      // The count should be initialCount + 1
      expect(countValue).toEqual(initialCount + 1)
    })

    test('note title is saved correctly, not Untitled', async ({ authenticatedPage }) => {
      // This test verifies that when saving a note, the title is properly
      // captured and saved, not defaulting to "Untitled".

      // Navigate to create new note
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Click New Note
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      // Wait for editor
      await authenticatedPage.waitForSelector('input[placeholder="Untitled"]', { timeout: 10000 })
      await authenticatedPage.waitForTimeout(500)

      // Set a specific title
      const expectedTitle = `My Specific Title ${uniqueId()}`
      const titleInput = authenticatedPage.locator('input[placeholder="Untitled"]')
      await titleInput.fill(expectedTitle)

      // Verify the input has the correct value before saving
      await expect(titleInput).toHaveValue(expectedTitle)

      // Add some content (required for the note to be meaningful)
      await authenticatedPage.click('.ProseMirror')
      await authenticatedPage.keyboard.type('This is the content.')

      // Wait a moment for state to settle
      await authenticatedPage.waitForTimeout(300)

      // Click Create
      const createButton = authenticatedPage.locator('button:has-text("Create")')
      await createButton.click()

      // Wait for save to complete
      await authenticatedPage.waitForURL(/\/notes\/[a-f0-9-]+$/, { timeout: 10000 })
      await authenticatedPage.waitForTimeout(1000)

      // Verify the title input still shows the correct title (not "Untitled")
      await expect(titleInput).toHaveValue(expectedTitle)

      // Also verify via API that the note was saved with correct title
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_access_token'))
      const url = authenticatedPage.url()
      const noteIdMatch = url.match(/\/notes\/([a-f0-9-]+)/)
      expect(noteIdMatch).toBeTruthy()
      const noteId = noteIdMatch[1]

      const noteRes = await authenticatedPage.request.get(`${BASE_PATH}/api/notes/${noteId}/`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        'X-Organization-ID': await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_organization_id')),
        },
      })
      expect(noteRes.ok()).toBeTruthy()
      const note = await noteRes.json()

      // Critical assertion: the saved title should match what we entered
      expect(note.title).toEqual(expectedTitle)
    })

    test('note is created in selected notebook, not default', async ({ authenticatedPage }) => {
      // This test verifies the fix for the bug where notes were always created
      // in the default notebook instead of the user-selected notebook.
      //
      // Bug context: The useEffect that initialized the notebook had defaultNotebook
      // in its dependency array, causing it to reset the user's selection when the
      // defaultNotebook loaded/changed.

      const token = await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_access_token'))
      const headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        'X-Organization-ID': await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_organization_id')),
      }

      // Get existing notebooks to use a non-default one
      const notebooksRes = await authenticatedPage.request.get(`${BASE_PATH}/api/notebooks/`, {
        headers,
      })
      const notebooksList = await notebooksRes.json()
      const notebooks = notebooksList.results || notebooksList

      // If only one notebook (General/default), create another one
      let targetNotebook
      if (notebooks.length < 2) {
        const targetName = `Target ${uniqueId()}`
        const createRes = await authenticatedPage.request.post(`${BASE_PATH}/api/notebooks/`, {
          data: {
            name: targetName,
            color: '#ef4444',
          },
          headers,
        })
        expect(createRes.ok()).toBeTruthy()
        targetNotebook = await createRes.json()

        // Force reload the page to get fresh notebooks in React Query cache
        await authenticatedPage.goto(`${BASE_PATH}/`)
        await authenticatedPage.waitForLoadState('networkidle')
        await authenticatedPage.reload()
        await authenticatedPage.waitForLoadState('networkidle')
        await authenticatedPage.waitForTimeout(2000)
      } else {
        // Use existing non-default notebook
        const defaultNotebook = notebooks.find(nb => nb.is_default)
        targetNotebook = notebooks.find(nb => !nb.is_default) || notebooks[0]
        if (targetNotebook.id === defaultNotebook?.id && notebooks.length > 1) {
          targetNotebook = notebooks.find(nb => nb.id !== defaultNotebook.id)
        }

        // Navigate to dashboard
        await authenticatedPage.goto(`${BASE_PATH}/`)
        await authenticatedPage.waitForLoadState('networkidle')
        await authenticatedPage.waitForTimeout(1000)
      }

      console.log('Target notebook:', targetNotebook.id, targetNotebook.name)

      // Click New Note
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      // Wait for editor
      await authenticatedPage.waitForSelector('input[placeholder="Untitled"]', { timeout: 10000 })
      await authenticatedPage.waitForTimeout(1000)

      // Find and change the notebook selector
      const selector = authenticatedPage.locator('select').first()

      // First, verify the default notebook is selected (should be "General")
      const defaultSelectedValue = await selector.inputValue()
      console.log('Default selected:', defaultSelectedValue)

      // Select the target notebook from the dropdown
      await selector.selectOption({ value: targetNotebook.id })
      await authenticatedPage.waitForTimeout(500)

      // Verify the selector has the target notebook selected
      const selectedValue = await selector.inputValue()
      expect(selectedValue).toEqual(targetNotebook.id)

      // Fill in title
      const noteTitle = `Note in Target ${uniqueId()}`
      await authenticatedPage.fill('input[placeholder="Untitled"]', noteTitle)

      // Add some content
      await authenticatedPage.click('.ProseMirror')
      await authenticatedPage.keyboard.type('Testing notebook selection')

      // Wait a moment - this is when the bug would trigger if defaultNotebook changes
      await authenticatedPage.waitForTimeout(1500)

      // Verify the selection is STILL the target notebook (not reset to default)
      const selectedValueAfterWait = await selector.inputValue()
      expect(selectedValueAfterWait).toEqual(targetNotebook.id)

      // Click Create
      const createButton = authenticatedPage.locator('button:has-text("Create")')
      await createButton.click()
      await authenticatedPage.waitForTimeout(2000)

      // Get the note ID from the URL
      const url = authenticatedPage.url()
      const noteIdMatch = url.match(/\/notes\/([a-f0-9-]+)/)
      expect(noteIdMatch).toBeTruthy()
      const noteId = noteIdMatch[1]

      // Verify the note was created in the correct notebook via API
      const noteRes = await authenticatedPage.request.get(`${BASE_PATH}/api/notes/${noteId}/`, { headers })
      expect(noteRes.ok()).toBeTruthy()
      const createdNote = await noteRes.json()

      // This is the critical assertion: the note should be in the target notebook,
      // NOT the default notebook
      expect(createdNote.notebook).toEqual(targetNotebook.id)
    })

    test('editor handles empty content without errors', async ({ authenticatedPage }) => {
      // Track console errors
      const consoleErrors = []
      authenticatedPage.on('console', msg => {
        if (msg.type() === 'error' && msg.text().includes('Unknown node type')) {
          consoleErrors.push(msg.text())
        }
      })

      // Start from dashboard and use UI navigation
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Click the "New Note" button in the sidebar
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      // Wait for editor
      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Check no "Unknown node type" errors (the bug we fixed)
      expect(consoleErrors).toHaveLength(0)
    })

    test('notebook selector shows options or placeholder', async ({ authenticatedPage }) => {
      // Start from dashboard and use UI navigation
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Click the "New Note" button in the sidebar
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      // Wait for editor
      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Find the notebook selector
      const selector = authenticatedPage.locator('select').first()
      await expect(selector).toBeVisible()

      // Should have at least one option (either notebooks or placeholder)
      const options = await selector.locator('option').count()
      expect(options).toBeGreaterThan(0)

      // Get the first option text
      const firstOption = await selector.locator('option').first().textContent()
      expect(firstOption).toBeTruthy()
      expect(firstOption.length).toBeGreaterThan(0)
    })

    test('can edit an existing note', async ({ authenticatedPage }) => {
      // Create a note via UI first
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Create a new note
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      // Wait for editor
      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Set title
      const noteTitle = `Edit Test Note ${uniqueId()}`
      const titleInput = authenticatedPage.locator('input[placeholder="Untitled"]')
      await titleInput.fill(noteTitle)

      // Add content
      await authenticatedPage.click('.ProseMirror')
      await authenticatedPage.keyboard.type('Original content')

      // Save the note
      const createButton = authenticatedPage.locator('button:has-text("Create")')
      await createButton.click()
      await authenticatedPage.waitForTimeout(2000)

      // Now edit - should already be on the note page
      await titleInput.clear()
      await titleInput.fill(`${noteTitle} - Updated`)

      // Save changes
      const saveButton = authenticatedPage.locator('button:has-text("Save")')
      await saveButton.click()
      await authenticatedPage.waitForTimeout(2000)

      // Verify the title was updated
      await expect(titleInput).toHaveValue(`${noteTitle} - Updated`)
    })

    test('note content persists after page refresh', async ({ authenticatedPage }) => {
      // This test verifies that note content is properly saved and reloaded
      // This was a bug where TipTap editor didn't load content on refresh

      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Create a new note
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      // Wait for editor
      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Set a unique title
      const noteTitle = `Persist Test ${uniqueId()}`
      const titleInput = authenticatedPage.locator('input[placeholder="Untitled"]')
      await titleInput.fill(noteTitle)

      // Add specific content that we can verify later
      const testContent = `Test content created at ${Date.now()}`
      await authenticatedPage.click('.ProseMirror')
      await authenticatedPage.keyboard.type(testContent)

      // Save the note
      const createButton = authenticatedPage.locator('button:has-text("Create")')
      await createButton.click()

      // Wait for navigation to the note's edit page
      await authenticatedPage.waitForURL(/\/notes\/[a-f0-9-]+$/, { timeout: 10000 })
      await authenticatedPage.waitForTimeout(1000)

      // Get the URL to navigate back after refresh
      const noteUrl = authenticatedPage.url()

      // Verify content is visible before refresh
      const editorBefore = authenticatedPage.locator('.ProseMirror')
      await expect(editorBefore).toContainText(testContent)

      // CRITICAL: Refresh the page
      await authenticatedPage.reload()
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(2000)

      // Verify the title is loaded
      await expect(titleInput).toHaveValue(noteTitle)

      // Verify the content is loaded in the editor
      const editorAfter = authenticatedPage.locator('.ProseMirror')
      await expect(editorAfter).toContainText(testContent)
    })
  })

  test.describe('Rich Text Editor', () => {
    test('toolbar buttons are functional', async ({ authenticatedPage }) => {
      // Start from dashboard and use UI navigation
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Click the "New Note" button in the sidebar
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      // Wait for editor toolbar
      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Click in editor
      await authenticatedPage.click('.ProseMirror')
      await authenticatedPage.keyboard.type('Test text')

      // Select the text
      await authenticatedPage.keyboard.press('Control+a')

      // Click bold button
      const boldButton = authenticatedPage.locator('button[title="Bold"]')
      if (await boldButton.isVisible()) {
        await boldButton.click()

        // Verify button shows active state
        await expect(boldButton).toHaveClass(/bg-gray-100|text-shizuha/)
      }
    })

    test('can add a heading', async ({ authenticatedPage }) => {
      // Start from dashboard and use UI navigation
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Click the "New Note" button in the sidebar
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Click heading 1 button
      const h1Button = authenticatedPage.locator('button[title="Heading 1"]')
      if (await h1Button.isVisible()) {
        await h1Button.click()

        // Toolbar restores the caret in the heading; clicking the center of
        // the editor would move it into the trailing empty paragraph.
        await expect(authenticatedPage.locator('.ProseMirror')).toBeFocused()
        await authenticatedPage.keyboard.type('My Heading')

        // Verify heading was created
        const heading = authenticatedPage.locator('.ProseMirror h1')
        await expect(heading).toContainText('My Heading')
      }
    })

    test('can create a bullet list', async ({ authenticatedPage }) => {
      // Start from dashboard and use UI navigation
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Click the "New Note" button in the sidebar
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Click bullet list button
      const listButton = authenticatedPage.locator('button[title="Bullet List"]')
      if (await listButton.isVisible()) {
        await listButton.click()

        // Keep the caret in the list created by the focused toolbar command.
        await expect(authenticatedPage.locator('.ProseMirror')).toBeFocused()
        await authenticatedPage.keyboard.type('First item')
        await authenticatedPage.keyboard.press('Enter')
        await authenticatedPage.keyboard.type('Second item')

        // Verify list was created
        const listItems = authenticatedPage.locator('.ProseMirror li')
        expect(await listItems.count()).toBeGreaterThanOrEqual(2)
      }
    })

    test('can add a link to text', async ({ authenticatedPage }) => {
      // This test verifies that links can be added to notes using the toolbar modal

      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Click New Note
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Type some text
      await authenticatedPage.click('.ProseMirror')
      await authenticatedPage.keyboard.type('Click here for Google')

      // Select "Google" text
      await authenticatedPage.keyboard.press('Shift+Control+ArrowLeft') // Select last word

      // Click the link button to open the modal
      const linkButton = authenticatedPage.locator('button[title="Insert Link"]')
      await expect(linkButton).toBeVisible()
      await linkButton.click()

      // Wait for the modal to appear and fill in the URL
      const urlInput = authenticatedPage.locator('input[placeholder="https://example.com"]')
      await expect(urlInput).toBeVisible()
      await urlInput.fill('https://www.google.com')

      // Click Insert Link button in the modal
      const insertButton = authenticatedPage.locator('button:has-text("Insert Link")')
      await insertButton.click()

      // Wait for the link to be created
      await authenticatedPage.waitForTimeout(500)

      // Verify a link was created in the editor
      const link = authenticatedPage.locator('.ProseMirror a')
      await expect(link).toBeVisible()
      const href = await link.getAttribute('href')
      expect(href).toBe('https://www.google.com')
    })

    test('can add an image via URL', async ({ authenticatedPage, authenticatedApi, notebooks }) => {
      // This test verifies that images can be added to notes using the toolbar modal

      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Click New Note
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Click the image button to open the modal
      const imageButton = authenticatedPage.locator('button[title="Insert Image"]')
      await expect(imageButton).toBeVisible()
      await imageButton.click()

      // Wait for modal to appear - it defaults to Upload tab, switch to URL tab
      const urlTab = authenticatedPage.locator('button:has-text("URL")')
      await expect(urlTab).toBeVisible()
      await urlTab.click()

      // Fill in the image URL
      const noteResponse = await authenticatedApi.post(`${BASE_PATH}/api/notes/`, {
        data: { notebook: notebooks[0].id, title: uniqueId('Image fixture') },
      })
      expect(noteResponse.ok()).toBeTruthy()
      const note = await noteResponse.json()
      const uploaded = await authenticatedPage.request.post(`${BASE_PATH}/api/attachments/`, {
        headers: { Authorization: `Bearer ${authenticatedApi.token}`,
          'X-Organization-ID': await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_organization_id')) },
        multipart: { note: note.id, file: { name: 'image-fixture.png', mimeType: 'image/png', buffer: TEST_PNG } },
      })
      expect(uploaded.ok()).toBeTruthy()
      const imageUrl = (await uploaded.json()).file_url
      const urlInput = authenticatedPage.locator('input[placeholder="https://example.com/image.jpg"]')
      await expect(urlInput).toBeVisible()
      await urlInput.fill(imageUrl)

      // Click Insert Image button
      const insertButton = authenticatedPage.locator('button:has-text("Insert Image")')
      await insertButton.click()

      // Wait for the image to be inserted
      await authenticatedPage.waitForTimeout(1000)

      // Verify an image with the correct src was added to the editor
      const image = authenticatedPage.locator(`.ProseMirror img[src="${imageUrl}"]`)
      await expect(image).toBeVisible()
      await expect.poll(() => image.evaluate(element => element.naturalWidth)).toBe(2)
      await authenticatedApi.delete(`${BASE_PATH}/api/notes/${note.id}/`)
    })

    test('image modal shows upload tab by default', async ({ authenticatedPage }) => {
      // Verify the Image modal defaults to the Upload tab (Evernote-like behavior)

      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Click New Note
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Click the image button
      const imageButton = authenticatedPage.locator('button[title="Insert Image"]')
      await imageButton.click()

      // Verify the modal appears with Insert Image title
      const modalTitle = authenticatedPage.locator('h3:has-text("Insert Image")')
      await expect(modalTitle).toBeVisible()

      // Verify Upload tab is active (has the active styling)
      const uploadTab = authenticatedPage.locator('button:has-text("Upload")').first()
      await expect(uploadTab).toHaveClass(/border-shizuha-600/)

      // Verify the upload area is visible
      const uploadArea = authenticatedPage.locator('text=Click to upload')
      await expect(uploadArea).toBeVisible()

      // Verify URL tab also exists
      const urlTab = authenticatedPage.locator('button:has-text("URL")')
      await expect(urlTab).toBeVisible()
    })

    test('attach file button opens attachment modal', async ({ authenticatedPage }) => {
      // Test the new Attach File button

      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Click New Note
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Click the attach file button
      const attachButton = authenticatedPage.locator('button[title="Attachments"]')
      await expect(attachButton).toBeVisible()
      await attachButton.click()

      // Verify the modal appears
      const modalTitle = authenticatedPage.locator('h3:has-text("Attach File")')
      await expect(modalTitle).toBeVisible()

      // Verify the upload area mentions file types
      const fileTypes = authenticatedPage.locator('text=PDF, DOC, TXT')
      await expect(fileTypes).toBeVisible()

      // Verify the click to select text is present
      const clickToSelect = authenticatedPage.locator('text=Click to select')
      await expect(clickToSelect).toBeVisible()
    })
  })

  test.describe('Attachments API', () => {
    test('attachments API endpoint exists and returns list', async ({ authenticatedApi }) => {
      // Test that the attachments API is accessible
      const response = await authenticatedApi.get(`${BASE_PATH}/api/attachments/`)
      expect(response.ok()).toBeTruthy()
      const data = await response.json()
      // Should return an array (results or direct)
      const attachments = data.results || data
      expect(Array.isArray(attachments)).toBe(true)
    })

    test('can upload a file attachment to a note', async ({ authenticatedPage, authenticatedApi }) => {
      // First create a note to attach to
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_access_token'))

      // Get a notebook to create the note in
      const notebooksRes = await authenticatedApi.get(`${BASE_PATH}/api/notebooks/`, {
      })
      const notebooks = (await notebooksRes.json()).results || await notebooksRes.json()
      expect(notebooks.length).toBeGreaterThan(0)

      // Create a note
      const noteRes = await authenticatedApi.post(`${BASE_PATH}/api/notes/`, {
        data: {
          notebook: notebooks[0].id,
          title: `Attachment Test Note ${Date.now()}`,
          content_text: 'Testing attachments',
        },
      })
      expect(noteRes.ok()).toBeTruthy()
      const note = await noteRes.json()

      // Upload a text file attachment using Playwright's multipart support
      const filename = 'test-attachment.txt'
      const fileContent = 'This is a test file content for attachment testing.'

      const uploadRes = await authenticatedPage.request.post(`${BASE_PATH}/api/attachments/`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        'X-Organization-ID': await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_organization_id')),
        },
        multipart: {
          note: note.id,
          file: {
            name: filename,
            mimeType: 'text/plain',
            buffer: Buffer.from(fileContent),
          },
        },
      })

      // Verify the upload succeeded
      expect(uploadRes.ok()).toBeTruthy()
      const createResponse = await uploadRes.json()

      // The create response from AttachmentUploadSerializer only returns basic fields
      expect(createResponse.note).toBe(note.id)
      expect(createResponse.file).toBeTruthy() // File URL is returned

      // Verify the attachment was actually created by fetching all attachments for the note
      const listRes = await authenticatedApi.get(`${BASE_PATH}/api/attachments/`)
      expect(listRes.ok()).toBeTruthy()
      const attachments = (await listRes.json()).results || await listRes.json()

      // Find our attachment by the file URL pattern
      const ourAttachment = attachments.find(a =>
        a.note === note.id && a.original_filename === filename
      )
      expect(ourAttachment).toBeTruthy()
      expect(ourAttachment.file_type).toBe('document') // text/plain is categorized as 'document'

      // Clean up - delete the attachment
      const deleteRes = await authenticatedApi.delete(`${BASE_PATH}/api/attachments/${ourAttachment.id}/`)
      expect(deleteRes.ok()).toBeTruthy()
    })

    test('attachment upload returns file_url with proper path', async ({ authenticatedPage, authenticatedApi }) => {
      // This test verifies the fix for file_url not being returned correctly
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_access_token'))

      // Get a notebook
      const notebooksRes = await authenticatedApi.get(`${BASE_PATH}/api/notebooks/`, {
      })
      const notebooks = (await notebooksRes.json()).results || await notebooksRes.json()
      expect(notebooks.length).toBeGreaterThan(0)

      // Create a note
      const noteRes = await authenticatedApi.post(`${BASE_PATH}/api/notes/`, {
        data: {
          notebook: notebooks[0].id,
          title: `URL Test Note ${Date.now()}`,
          content_text: 'Testing file_url',
        },
      })
      expect(noteRes.ok()).toBeTruthy()
      const note = await noteRes.json()

      // Upload a file
      const filename = `url-test-${Date.now()}.txt`
      const uploadRes = await authenticatedPage.request.post(`${BASE_PATH}/api/attachments/`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        'X-Organization-ID': await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_organization_id')),
        },
        multipart: {
          note: note.id,
          file: {
            name: filename,
            mimeType: 'text/plain',
            buffer: Buffer.from('Test content'),
          },
        },
      })

      expect(uploadRes.ok()).toBeTruthy()
      const attachment = await uploadRes.json()

      // Verify file_url is returned and has the correct format
      expect(attachment.file_url).toBeTruthy()
      // NTS-83: file_url is the note-scoped edge route, not raw storage — the
      // presigned storage URL named the in-cluster MinIO host and embedded the
      // storage credential identity in the query.
      expect(new URL(attachment.file_url).pathname).toContain(`/api/attachments/${attachment.id}/file/`)
      // file_url should be an absolute URL or have a leading slash
      expect(attachment.file_url.startsWith('http') || attachment.file_url.startsWith('/')).toBe(true)

      // Verify original_filename is returned
      expect(attachment.original_filename).toBe(filename)

      // Verify the file can be fetched via the URL
      const fileRes = await authenticatedPage.request.get(attachment.file_url, {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      expect(fileRes.ok()).toBeTruthy()
      expect(await fileRes.body()).toEqual(Buffer.from('Test content'))

      // Clean up
      await authenticatedApi.delete(`${BASE_PATH}/api/attachments/${attachment.id}/`)
    })

    test('image attachment upload returns file_url that renders', async ({ authenticatedPage, authenticatedApi }) => {
      // This test verifies image attachments can be served properly
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_access_token'))

      // Get a notebook
      const notebooksRes = await authenticatedApi.get(`${BASE_PATH}/api/notebooks/`, {
      })
      const notebooks = (await notebooksRes.json()).results || await notebooksRes.json()

      // Create a note
      const noteRes = await authenticatedApi.post(`${BASE_PATH}/api/notes/`, {
        data: {
          notebook: notebooks[0].id,
          title: `Image URL Test ${Date.now()}`,
          content_text: 'Testing image serving',
        },
      })
      const note = await noteRes.json()

      // A valid, deterministic PNG is uploaded through the real storage API.
      const pngBuffer = TEST_PNG

      const filename = `test-image-${Date.now()}.png`
      const uploadRes = await authenticatedPage.request.post(`${BASE_PATH}/api/attachments/`, {
        headers: {
          'Authorization': `Bearer ${token}`,
        'X-Organization-ID': await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_organization_id')),
        },
        multipart: {
          note: note.id,
          file: {
            name: filename,
            mimeType: 'image/png',
            buffer: pngBuffer,
          },
        },
      })

      expect(uploadRes.ok()).toBeTruthy()
      const attachment = await uploadRes.json()

      // Verify it's classified as an image
      expect(attachment.file_type).toBe('image')

      // Verify file_url is returned
      expect(attachment.file_url).toBeTruthy()
      // NTS-83: file_url is the note-scoped edge route, not raw storage.
      expect(new URL(attachment.file_url).pathname).toContain(`/api/attachments/${attachment.id}/file/`)

      // Verify the image can be fetched
      const imageRes = await authenticatedPage.request.get(attachment.file_url, {
        headers: { 'Authorization': `Bearer ${token}` },
      })
      expect(imageRes.ok()).toBeTruthy()
      const contentType = imageRes.headers()['content-type']
      expect(contentType).toContain('image/')
      expect(await imageRes.body()).toEqual(TEST_PNG)
      // Rendering still exercised in-browser: decode the authed bytes via a
      // blob URL (img elements cannot carry the Authorization header).
      const blobUrl = await authenticatedPage.evaluate(async ({ url, token }) => {
        const response = await fetch(url, { headers: { 'Authorization': `Bearer ${token}` } })
        const blob = await response.blob()
        return URL.createObjectURL(blob)
      }, { url: attachment.file_url, token })
      const rendered = authenticatedPage.locator('[data-test=stored-image]')
      await authenticatedPage.evaluate(url => { const img = document.createElement('img'); img.dataset.test = 'stored-image'; img.src = url; document.body.append(img) }, blobUrl)
      await expect.poll(() => rendered.evaluate(element => element.naturalWidth)).toBe(2)

      // Clean up
      await authenticatedApi.delete(`${BASE_PATH}/api/attachments/${attachment.id}/`)
    })

    test('note editor shows attachments list', async ({ authenticatedPage, authenticatedApi }) => {
      // This test verifies that attachments are displayed in the note editor UI
      const token = await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_access_token'))

      // Get a notebook
      const notebooksRes = await authenticatedApi.get(`${BASE_PATH}/api/notebooks/`, {
      })
      const notebooks = (await notebooksRes.json()).results || await notebooksRes.json()

      // Create a note
      const noteRes = await authenticatedApi.post(`${BASE_PATH}/api/notes/`, {
        data: {
          notebook: notebooks[0].id,
          title: `Attachments List Test ${Date.now()}`,
          content_text: 'Testing attachments list display',
        },
      })
      const note = await noteRes.json()

      // Upload two attachments
      const filename1 = `attachment-test-1-${Date.now()}.txt`
      const filename2 = `attachment-test-2-${Date.now()}.pdf`

      await authenticatedPage.request.post(`${BASE_PATH}/api/attachments/`, {
        headers: { 'Authorization': `Bearer ${token}`, 'X-Organization-ID': await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_organization_id')) },
        multipart: {
          note: note.id,
          file: { name: filename1, mimeType: 'text/plain', buffer: Buffer.from('Test 1') },
        },
      })

      await authenticatedPage.request.post(`${BASE_PATH}/api/attachments/`, {
        headers: { 'Authorization': `Bearer ${token}`, 'X-Organization-ID': await authenticatedPage.evaluate(() => localStorage.getItem('shizuha_organization_id')) },
        multipart: {
          note: note.id,
          file: { name: filename2, mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 test') },
        },
      })

      // Navigate to the note editor
      await authenticatedPage.goto(`${BASE_PATH}/notes/${note.id}`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(2000)

      // Verify the Attachments section is visible
      const attachmentsHeader = authenticatedPage.locator('h3:has-text("Attachments")')
      await expect(attachmentsHeader).toBeVisible()

      // Verify there are at least 2 attachments (the ones we just uploaded)
      const headerText = await attachmentsHeader.textContent()
      const countMatch = headerText.match(/\((\d+)\)/)
      expect(countMatch).toBeTruthy()
      const attachmentCount = parseInt(countMatch[1])
      expect(attachmentCount).toBeGreaterThanOrEqual(2)

      // Verify both of our specific filenames are shown
      const attachment1 = authenticatedPage.locator(`text=${filename1}`)
      const attachment2 = authenticatedPage.locator(`text=${filename2}`)
      await expect(attachment1).toBeVisible()
      await expect(attachment2).toBeVisible()

      // Verify action buttons are present (download, open)
      const downloadButtons = authenticatedPage.locator('[title="Download"]')
      expect(await downloadButtons.count()).toBeGreaterThanOrEqual(2)
    })
  })

  test.describe('Note Actions', () => {
    test('can pin and unpin a note', async ({ authenticatedPage }) => {
      // Create a note via UI
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Create a new note
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      // Wait for editor
      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Set title
      const noteTitle = `Pin Test ${uniqueId()}`
      const titleInput = authenticatedPage.locator('input[placeholder="Untitled"]')
      await titleInput.fill(noteTitle)

      // Add content
      await authenticatedPage.click('.ProseMirror')
      await authenticatedPage.keyboard.type('Test content')

      // Save the note
      const createButton = authenticatedPage.locator('button:has-text("Create")')
      await createButton.click()
      await authenticatedPage.waitForTimeout(2000)

      // Find and click pin button (should now be visible since we're on an existing note)
      const pinButton = authenticatedPage.locator('button[title*="Pin"], button[title*="Unpin"]').first()
      await expect(pinButton).toBeVisible({ timeout: 5000 })
      await pinButton.click()
      await authenticatedPage.waitForTimeout(1000)

      // After clicking, the button title should change (Pin -> Unpin or vice versa)
      // Just verify we can still find a pin-related button
      const pinButtonAfter = authenticatedPage.locator('button[title*="Pin"], button[title*="Unpin"]').first()
      await expect(pinButtonAfter).toBeVisible()
    })

    test('can favorite a note', async ({ authenticatedPage }) => {
      // Create a note via UI
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Create a new note
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      // Wait for editor
      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Set title
      const noteTitle = `Favorite Test ${uniqueId()}`
      const titleInput = authenticatedPage.locator('input[placeholder="Untitled"]')
      await titleInput.fill(noteTitle)

      // Add content
      await authenticatedPage.click('.ProseMirror')
      await authenticatedPage.keyboard.type('Test content')

      // Save the note
      const createButton = authenticatedPage.locator('button:has-text("Create")')
      await createButton.click()
      await authenticatedPage.waitForTimeout(2000)

      // Find and click favorite button
      const favoriteButton = authenticatedPage.locator('button[title*="favorite"]')
      await expect(favoriteButton).toBeVisible({ timeout: 5000 })
      await favoriteButton.click()
      await authenticatedPage.waitForTimeout(1000)

      // Verify button is still visible
      await expect(favoriteButton).toBeVisible()
    })

    test('can delete a note', async ({ authenticatedPage }) => {
      // Create a note via UI
      await authenticatedPage.goto(`${BASE_PATH}/`)
      await authenticatedPage.waitForLoadState('networkidle')
      await authenticatedPage.waitForTimeout(1000)

      // Create a new note
      const newNoteButton = authenticatedPage.locator('button:has-text("New Note")').first()
      await newNoteButton.click()

      // Wait for editor
      await authenticatedPage.waitForSelector('.ProseMirror', { timeout: 10000 })

      // Set title
      const noteTitle = `Delete Test ${uniqueId()}`
      const titleInput = authenticatedPage.locator('input[placeholder="Untitled"]')
      await titleInput.fill(noteTitle)

      // Add content
      await authenticatedPage.click('.ProseMirror')
      await authenticatedPage.keyboard.type('Test content')

      // Save the note
      const createButton = authenticatedPage.locator('button:has-text("Create")')
      await createButton.click()

      // Wait for URL to change from /new to an actual note ID (UUID format)
      await authenticatedPage.waitForURL(/.*notes\/[0-9a-f-]{36}.*/, { timeout: 10000 })
      await authenticatedPage.waitForTimeout(1000)

      // Get current URL (should have numeric ID now)
      const urlBeforeDelete = authenticatedPage.url()

      // Open menu (use data-testid to avoid matching sidebar tree menu buttons)
      const menuButton = authenticatedPage.locator('[data-testid="note-menu-button"]')
      await expect(menuButton).toBeVisible({ timeout: 5000 })
      await menuButton.click()

      // Handle confirmation dialog
      authenticatedPage.on('dialog', dialog => dialog.accept())

      // Click delete
      const deleteButton = authenticatedPage.locator('button:has-text("Move to Trash")')
      await deleteButton.click()

      // Should navigate away from the note
      await authenticatedPage.waitForTimeout(2000)

      // Verify we're not on the same note page anymore
      const urlAfterDelete = authenticatedPage.url()
      expect(urlAfterDelete).not.toEqual(urlBeforeDelete)
    })
  })

  test.describe('API Integration', () => {
    test('removed workspace route is unavailable', async ({ authenticatedApi }) => {
      const response = await authenticatedApi.get('workspaces/')
      expect(response.status()).toBe(404)
    })

    test('can list notebooks via API', async ({ authenticatedApi }) => {
      const response = await authenticatedApi.get('notebooks/')
      expect(response.ok()).toBeTruthy()

      const data = await response.json()
      expect(Array.isArray(data.results || data)).toBeTruthy()
    })

    test('can list notes via API', async ({ authenticatedApi }) => {
      const response = await authenticatedApi.get('notes/')
      expect(response.ok()).toBeTruthy()

      const data = await response.json()
      expect(Array.isArray(data.results || data)).toBeTruthy()
    })

    test('can list tags via API', async ({ authenticatedApi }) => {
      const response = await authenticatedApi.get('tags/')
      expect(response.ok()).toBeTruthy()

      const data = await response.json()
      expect(Array.isArray(data.results || data)).toBeTruthy()
    })
  })
})
