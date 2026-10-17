// @ts-check
const { test, expect } = require('./fixtures');

test.describe('Notes App', () => {
  test('should load dashboard when authenticated', async ({ authenticatedPage: page }) => {
    // Should be on notes page (not redirected to login)
    await expect(page).toHaveURL(/\/notes/);

    // Should show welcome message or dashboard content
    await expect(page.locator('text=Welcome').first()).toBeVisible({ timeout: 10000 });
  });

  test('should display navigation sidebar', async ({ authenticatedPage: page }) => {
    // Should have navigation links
    const nav = page.locator('nav, [role="navigation"], aside');
    await expect(nav.first()).toBeVisible();
  });

  test('should show create note option', async ({ authenticatedPage: page }) => {
    // Should have a way to create new notes (look for links containing "new" or Create text)
    const createButton = page.locator('a:has-text("Create"), a:has-text("New Note")').first();
    await expect(createButton).toBeVisible();
  });

  test('should display stats cards', async ({ authenticatedPage: page }) => {
    // Dashboard should show stats like Total Notes, Notebooks, etc.
    await expect(page.locator('text=Total Notes').first()).toBeVisible({ timeout: 10000 });
  });

  test('should show Recent Notes section', async ({ authenticatedPage: page }) => {
    // Dashboard should have Recent Notes section
    await expect(page.locator('text=Recent Notes').first()).toBeVisible({ timeout: 10000 });
  });
});
