// @ts-check
const { test: base, expect } = require('@playwright/test');

// Support both docker-compose (shizuha-nginx) and local dev (localhost:18080 via BASE_URL)
const DEFAULT_BASE = process.env.BASE_URL || 'http://localhost:18080';
const API_BASE = process.env.API_BASE || `${DEFAULT_BASE}/notes/api`;
const SHIZUHA_ID_API = process.env.SHIZUHA_ID_API || (process.env.SHIZUHA_ID_BASE ? process.env.SHIZUHA_ID_BASE + '/api' : `${DEFAULT_BASE}/id/api`);

/**
 * Extended test with authentication helpers
 */
const test = base.extend({
  /**
   * Authenticated page - sets JWT token in localStorage and ensures workspace exists
   */
  authenticatedPage: async ({ page, request }, use) => {
    // Login via API to get JWT token
    const loginResponse = await request.post(`${SHIZUHA_ID_API}/auth/login/`, {
      data: {
        username: 'testuser',
        password: 'TestPass123',
      },
    });

    if (!loginResponse.ok()) {
      throw new Error(`Login failed: ${await loginResponse.text()}`);
    }

    const loginData = await loginResponse.json();
    const accessToken = loginData.tokens?.access || loginData.access;
    const refreshToken = loginData.tokens?.refresh || loginData.refresh;

    if (!accessToken) {
      throw new Error('No access token received from login');
    }

    // Ensure workspace exists via API
    const authHeaders = { Authorization: `Bearer ${accessToken}` };

    // Check for existing workspaces
    const workspacesResponse = await request.get(`${API_BASE}/workspaces/`, {
      headers: authHeaders,
    });

    let workspaces = [];
    if (workspacesResponse.ok()) {
      const data = await workspacesResponse.json();
      workspaces = data.results || data;
    }

    // Create default workspace if none exists
    if (workspaces.length === 0) {
      const createWorkspaceResponse = await request.post(`${API_BASE}/workspaces/`, {
        headers: authHeaders,
        data: {
          name: 'Personal',
          workspace_type: 'personal',
        },
      });
      if (createWorkspaceResponse.ok()) {
        const newWorkspace = await createWorkspaceResponse.json();
        workspaces = [newWorkspace];
      }
    }

    // Create default notebook if none exists
    if (workspaces.length > 0) {
      const notebooksResponse = await request.get(`${API_BASE}/notebooks/`, {
        headers: authHeaders,
      });

      let notebooks = [];
      if (notebooksResponse.ok()) {
        const data = await notebooksResponse.json();
        notebooks = data.results || data;
      }

      if (notebooks.length === 0) {
        await request.post(`${API_BASE}/notebooks/`, {
          headers: authHeaders,
          data: {
            workspace: workspaces[0].id,
            name: 'Default',
            is_default: true,
          },
        });
      }
    }

    // Navigate to the app first (to set localStorage on the correct domain)
    await page.goto('/notes/');

    // Set tokens in localStorage (matching the AuthContext storage keys)
    await page.evaluate(({ access, refresh, user, workspaceSlug }) => {
      localStorage.setItem('shizuha_access_token', access);
      localStorage.setItem('shizuha_refresh_token', refresh);
      localStorage.setItem('shizuha_user', JSON.stringify(user));
      if (workspaceSlug) {
        localStorage.setItem('shizuha_current_workspace', workspaceSlug);
      }
    }, {
      access: accessToken,
      refresh: refreshToken,
      user: loginData.user,
      workspaceSlug: workspaces[0]?.slug,
    });

    // Navigate with retry for flaky auth redirect
    let retries = 3;
    while (retries > 0) {
      try {
        await page.goto('/notes/', { waitUntil: 'domcontentloaded', timeout: 10000 });
        // Check if we're not redirected to login
        const url = page.url();
        if (!url.includes('/id/login')) {
          break;
        }
        // Re-set tokens if redirected
        await page.evaluate(({ access, refresh, user, workspaceSlug }) => {
          localStorage.setItem('shizuha_access_token', access);
          localStorage.setItem('shizuha_refresh_token', refresh);
          localStorage.setItem('shizuha_user', JSON.stringify(user));
          if (workspaceSlug) {
            localStorage.setItem('shizuha_current_workspace', workspaceSlug);
          }
        }, {
          access: accessToken,
          refresh: refreshToken,
          user: loginData.user,
          workspaceSlug: workspaces[0]?.slug,
        });
      } catch (e) {
        // Navigation error, retry
      }
      retries--;
      await page.waitForTimeout(500);
    }

    // Wait for React to hydrate
    await page.waitForTimeout(1000);

    await use(page);
  },
});

module.exports = { test, expect };
