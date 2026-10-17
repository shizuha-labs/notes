import { test as base, expect } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { join } from 'node:path'

/**
 * Test fixtures for Shizuha Notes E2E tests
 * Provides authenticated user context, test data helpers, and API access
 */

// The isolated acceptance harness supplies a fresh disposable password.
// Standalone E2E callers must explicitly provision their own test account.
export const TEST_USER = {
  username: process.env.TEST_USER_USERNAME || 'testuser',
  password: process.env.TEST_USER_PASSWORD,
  email: 'testuser@example.com'
}
if (!TEST_USER.password) throw new Error('TEST_USER_PASSWORD is required for Notes E2E')

// Extend base test with authentication and data fixtures
export const test = base.extend({
  // Organization membership is provisioned through Admin by the test harness.
  // Notes removed its independent workspace model; writes require this context.
  organization: async ({ playwright }, use) => {
    const baseUrl = process.env.BASE_URL || 'http://shizuha-nginx'
    const request = await playwright.request.newContext({ baseURL: baseUrl })
    const login = await request.post('/id/api/auth/login/', {
      data: { username: TEST_USER.username, password: TEST_USER.password },
    })
    expect(login.ok()).toBeTruthy()
    const { tokens } = await login.json()
    const response = await request.get('/admin/api/organizations/', {
      headers: { Authorization: `Bearer ${tokens.access}` },
    })
    expect(response.ok()).toBeTruthy()
    const body = await response.json()
    const organizations = body.results || body
    const organization = process.env.TEST_ORGANIZATION_ID
      ? organizations.find(value => String(value.id) === process.env.TEST_ORGANIZATION_ID)
      : organizations[0]
    expect(organization, 'E2E account must belong to a test organization').toBeTruthy()
    await use(organization)
    await request.dispose()
  },

  // Authenticated page fixture - logs in via Shizuha ID
  authenticatedPage: async ({ page, organization }, use) => {
    // Go to Shizuha ID login page with next parameter
    await page.goto('/id/login?continue=/notes/')

    // Wait for form to be ready
    await page.waitForSelector('input[id="username"]', { timeout: 10000 })

    // Fill in credentials
    await page.fill('input[id="username"]', TEST_USER.username)
    await page.fill('input[id="password"]', TEST_USER.password)

    // Register the response listener before submitting; a fast local server
    // can complete login before click() returns.
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/auth/login/') && response.ok()),
      page.click('button[type="submit"]'),
    ])

    // Wait for redirect to Notes
    await page.waitForURL(/.*notes.*/, { timeout: 30000 })

    // Wait for page to fully load and React to hydrate
    await page.waitForLoadState('networkidle', { timeout: 20000 })
    await page.waitForTimeout(1000)

    // Verify we're on the notes app - check we're not still on login
    const url = page.url()
    if (url.includes('/id/login')) {
      throw new Error('Still on login page after authentication')
    }

    await expect(page.getByRole('heading', { name: 'Shizuha Notes' })).toBeVisible()
    await page.getByRole('button', { name: 'All Organizations', exact: true }).click()
    await page.getByRole('button', { name: organization.name, exact: true }).click()
    await expect.poll(() => page.evaluate(() => localStorage.getItem('shizuha_organization_id'))).toBe(String(organization.id))

    await page.waitForLoadState('networkidle')
    if (process.env.SHIZUHA_BROWSER_EVIDENCE_DIR) {
      await mkdir(process.env.SHIZUHA_BROWSER_EVIDENCE_DIR, { recursive: true })
      await page.screenshot({ path: join(process.env.SHIZUHA_BROWSER_EVIDENCE_DIR, 'notes.png'), fullPage: true })
    }

    // Use the authenticated page
    await use(page)
  },

  // Authenticated API context - uses Shizuha ID for login
  authenticatedApi: async ({ playwright, organization }, use) => {
    const baseUrl = process.env.BASE_URL || 'http://shizuha-nginx'
    const notesApiUrl = process.env.API_URL || `${baseUrl}/notes/api/`
    const normalizedApiUrl = notesApiUrl.endsWith('/') ? notesApiUrl : notesApiUrl + '/'
    const idApiUrl = process.env.ID_API_URL || `${baseUrl}/id/api/`

    const apiContext = await playwright.request.newContext({
      baseURL: idApiUrl,
      extraHTTPHeaders: {
        'Content-Type': 'application/json',
      },
    })

    // Login via Shizuha ID to get token
    const loginResponse = await apiContext.post('auth/login/', {
      data: {
        username: TEST_USER.username,
        password: TEST_USER.password
      }
    })

    if (!loginResponse.ok()) {
      const text = await loginResponse.text()
      throw new Error(`Login failed: ${loginResponse.status()} - ${text.substring(0, 200)}`)
    }

    const { tokens } = await loginResponse.json()

    // Create new context with auth header for Notes API
    const authContext = await playwright.request.newContext({
      baseURL: normalizedApiUrl,
      extraHTTPHeaders: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${tokens.access}`,
        'X-Organization-ID': String(organization.id),
      },
    })

    authContext.token = tokens.access

    await use(authContext)

    await apiContext.dispose()
    await authContext.dispose()
  },

  // Fixture to get notebooks
  notebooks: async ({ authenticatedApi }, use) => {
    const response = await authenticatedApi.get('notebooks/')
    let notebooks = []

    if (response.ok()) {
      const data = await response.json()
      notebooks = data.results || data || []
    }

    await use(notebooks)
  },
})

export { expect } from '@playwright/test'

/**
 * Helper function to create unique test data
 */
export function uniqueId(prefix = 'test') {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`
}
